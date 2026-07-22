"""Parallel agent dispatcher.

Loads each agent definition from ``.claude/agents/**/*.md``, scopes work to
the YAML checks the agent owns, builds a compact JSON context, and calls
Anthropic in parallel. Each agent returns a JSON array of findings which we
validate and convert into ``Finding`` rows for persistence.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from audit_engine.config import CHECKLISTS_DIR, ROOT, get_keys
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)


AGENTS_DIR = ROOT / ".claude" / "agents"
# Overridable via AUDIT_AGENT_MODEL (the AIOS worker sets it in the container env).
# The old hard-coded "claude-sonnet-4-6" is stale; default to a current model.
DEFAULT_MODEL = os.getenv("AUDIT_AGENT_MODEL") or "claude-haiku-4-5"
MAX_TOKENS_OUT = 4000
MAX_PAGES_IN_CONTEXT = 25
MAX_BODY_CHARS_PER_PAGE = 1200
MAX_FINDINGS_PER_AGENT = 60


# ---------- Loading agent definitions ----------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class AgentDefinition:
    name: str          # e.g. a1-content-eeat-analyst
    short: str         # e.g. A1
    description: str
    body: str          # the markdown body after frontmatter
    team: str          # meta | onpage | technical | offpage | local
    path: Path


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end():]
    return fm, body


_SHORT_FROM_NAME = re.compile(r"^([a-zA-Z]\d+)")


def _short_id(name: str, path: Path) -> str:
    m = _SHORT_FROM_NAME.match(name or "")
    if m:
        return m.group(1).upper()
    # Fallback: derive from filename like "a1-content-eeat.md"
    m = _SHORT_FROM_NAME.match(path.stem)
    return m.group(1).upper() if m else path.stem


def load_agents() -> list[AgentDefinition]:
    """Read every .md in .claude/agents/{team}/*.md, return ordered list."""
    out: list[AgentDefinition] = []
    if not AGENTS_DIR.is_dir():
        return out
    for team_dir in sorted(AGENTS_DIR.iterdir()):
        if not team_dir.is_dir():
            continue
        team = team_dir.name
        for md in sorted(team_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(text)
            name = fm.get("name") or md.stem
            short = _short_id(name, md)
            out.append(
                AgentDefinition(
                    name=str(name),
                    short=short,
                    description=str(fm.get("description") or ""),
                    body=body.strip(),
                    team=team,
                    path=md,
                )
            )
    return out


# ---------- Loading YAML checks per agent ----------

@dataclass
class CheckSpec:
    id: str
    name: str
    category: str
    subcategory: str | None
    severity_default: str
    owner_agent: str
    automation: str


def load_check_specs() -> list[CheckSpec]:
    out: list[CheckSpec] = []
    for f in CHECKLISTS_DIR.glob("*.yaml"):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        category = d.get("category", f.stem)
        for c in d.get("checks", []):
            out.append(
                CheckSpec(
                    id=c["id"],
                    name=c.get("name", ""),
                    category=str(category),
                    subcategory=c.get("subcategory"),
                    severity_default=c.get("severity_default", "minor"),
                    owner_agent=c.get("owner_agent", ""),
                    automation=c.get("automation", "full"),
                )
            )
    return out


def checks_for_agent(agent_short: str, all_checks: list[CheckSpec]) -> list[CheckSpec]:
    """All ai-assisted checks the agent owns."""
    return [c for c in all_checks if c.owner_agent.upper() == agent_short.upper() and c.automation == "ai-assisted"]


# ---------- Compact context builder ----------

def _shape_page(cp: Any) -> dict[str, Any]:
    p = cp.parsed
    if not p:
        return {"url": getattr(cp, "url", "?"), "status": getattr(cp, "http_status", None), "parsed": False}
    schema_types: list[str] = []
    for block in p.schema_blocks:
        t = block.get("@type") if isinstance(block, dict) else None
        if isinstance(t, list):
            schema_types.extend(str(x) for x in t)
        elif t:
            schema_types.append(str(t))
    return {
        "url": cp.url,
        "status": getattr(cp, "http_status", None),
        "title": p.title,
        "meta_description": p.meta_description,
        "h1s": p.h1s,
        "headings": [{"level": h.level, "text": h.text} for h in p.headings[:30]],
        "word_count": p.word_count,
        "canonical": p.canonical,
        "noindex": p.has_noindex,
        "schema_types": sorted(set(schema_types)),
        "images_total": len(p.images),
        "images_no_alt": sum(1 for i in p.images if not (i.alt or "").strip()),
        "internal_links": sum(1 for l in p.links if l.is_internal),
        "external_links": sum(1 for l in p.links if not l.is_internal),
        "body_excerpt": (p.body_text or "")[:MAX_BODY_CHARS_PER_PAGE],
    }


def _shape_finding(f: dict[str, Any]) -> dict[str, Any]:
    ev = f.get("evidence_json")
    if isinstance(ev, str) and ev:
        try:
            ev = json.loads(ev)
        except json.JSONDecodeError:
            ev = ev[:200]
    return {
        "id": f.get("check_id"),
        "name": f.get("check_name"),
        "status": f.get("status"),
        "severity": f.get("severity"),
        "score": f.get("score"),
        "evidence": ev,
    }


def build_agent_context(
    *,
    agent: AgentDefinition,
    checks: list[CheckSpec],
    crawl_result: Any,
    deterministic_findings: list[dict[str, Any]],
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the JSON payload sent as the user message for one agent."""
    pages_payload: list[dict[str, Any]] = []
    for cp in crawl_result.pages[:MAX_PAGES_IN_CONTEXT]:
        pages_payload.append(_shape_page(cp))

    # Existing findings filtered to this agent's owned checks
    owned_ids = {c.id for c in checks}
    related = [
        _shape_finding(f)
        for f in deterministic_findings
        if f.get("check_id") in owned_ids
    ]

    robots = getattr(crawl_result, "robots", None)
    robots_summary = None
    if robots is not None:
        robots_summary = {
            "status": getattr(robots, "status_code", None),
            "sitemaps": getattr(robots, "sitemaps", [])[:5],
            "groups": [
                {
                    "agents": g.user_agents,
                    "allow": g.allow[:8],
                    "disallow": g.disallow[:8],
                }
                for g in (getattr(robots, "groups", []) or [])[:5]
            ],
        }

    return {
        "agent": {"short": agent.short, "name": agent.name, "team": agent.team},
        "site": {
            "domain": crawl_result.site_url,
            "pages_crawled": len(crawl_result.pages),
            "pages_discovered": len(getattr(crawl_result, "discovered_urls", []) or []),
        },
        "owned_checks": [
            {
                "id": c.id,
                "name": c.name,
                "subcategory": c.subcategory,
                "severity_default": c.severity_default,
            }
            for c in checks
        ],
        "robots": robots_summary,
        "pages": pages_payload,
        "deterministic_findings_for_owned_checks": related,
        "extras": extras or {},
    }


# ---------- Calling the API ----------

_OUTPUT_PROMPT = """
Return ONLY a JSON array. Each element is one finding row in this exact schema:

{
  "check_id": "ON-022",          // must be one of the owned_checks IDs
  "url": "https://...",           // page URL the finding applies to (or null for site-wide)
  "status": "fail" | "warn" | "pass" | "n_a",
  "severity": "critical" | "major" | "minor" | "info",
  "score": 0.0,                   // 0-10 scale; lower is worse
  "confidence": 0.0,              // 0.0-1.0
  "evidence": { ... },            // dict of key/value evidence, including literal quotes when relevant
  "remediation": "specific, actionable fix"
}

Rules:
- Cover every check in owned_checks. If a check is not applicable to this site, return status="n_a" with confidence and a 1-line reason in evidence.
- Cite literal extracts in evidence where possible (e.g., the actual title text, a quoted sentence, a numeric value lifted from page data).
- Never invent data not present in the payload. If you cannot judge a check from the data given, return status="n_a" with confidence <= 0.4 and explain in evidence.
- Do not include any prose outside the JSON array. No markdown fences, no commentary.
"""


def _build_system_prompt(agent: AgentDefinition) -> str:
    return (
        agent.body
        + "\n\n## Output format (MANDATORY)\n"
        + _OUTPUT_PROMPT.strip()
    )


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Be forgiving: strip code fences, find the outermost [...], parse."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # remove first and last fence
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1)
        cleaned = re.sub(r"\s*```$", "", cleaned, count=1)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        arr = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    return [x for x in arr if isinstance(x, dict)]


_VALID_STATUS = {"pass", "warn", "fail", "n_a"}
_VALID_SEVERITY = {"critical", "major", "minor", "info"}


def _validate_finding(raw: dict[str, Any], owned_ids: set[str]) -> dict[str, Any] | None:
    cid = raw.get("check_id")
    if not isinstance(cid, str) or cid not in owned_ids:
        return None
    status = str(raw.get("status", "")).lower()
    if status not in _VALID_STATUS:
        return None
    severity = str(raw.get("severity", "")).lower()
    if severity not in _VALID_SEVERITY:
        severity = "info"
    try:
        score = float(raw.get("score") if raw.get("score") is not None else 5.0)
    except (TypeError, ValueError):
        score = 5.0
    score = max(0.0, min(10.0, score))
    try:
        conf = float(raw.get("confidence") if raw.get("confidence") is not None else 0.7)
    except (TypeError, ValueError):
        conf = 0.7
    conf = max(0.0, min(1.0, conf))
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), (dict, list)) else {"note": str(raw.get("evidence") or "")[:300]}
    remediation = raw.get("remediation")
    remediation = str(remediation).strip() if remediation else None
    url = raw.get("url")
    return {
        "check_id": cid,
        "status": status,
        "severity": severity,
        "score": score,
        "confidence": conf,
        "evidence": evidence,
        "remediation": remediation,
        "url": str(url) if url else None,
    }


async def _call_agent(
    client: Any,
    agent: AgentDefinition,
    context: dict[str, Any],
    *,
    model: str,
) -> list[dict[str, Any]]:
    owned_ids = {c["id"] for c in context.get("owned_checks", [])}
    if not owned_ids:
        return []
    sys_prompt = _build_system_prompt(agent)
    user_payload = "Evaluate the owned_checks below using the data provided.\n\n```json\n" + json.dumps(context, default=str)[:160_000] + "\n```"
    try:
        msg = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS_OUT,
            system=[{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_payload}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("agent_call_failed", agent=agent.short, error=f"{type(e).__name__}: {e}")
        return []
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    parsed = _extract_json_array(text)
    valid: list[dict[str, Any]] = []
    for raw in parsed[:MAX_FINDINGS_PER_AGENT]:
        v = _validate_finding(raw, owned_ids)
        if v is not None:
            valid.append(v)
    cache_read = getattr(msg.usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
    log.info(
        "agent_call_complete",
        agent=agent.short,
        owned=len(owned_ids),
        emitted=len(valid),
        input_tokens=msg.usage.input_tokens,
        output_tokens=msg.usage.output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
    )
    return valid


# ---------- Public entrypoint ----------

@dataclass
class AgentRunResult:
    findings: list[dict[str, Any]]
    per_agent_counts: dict[str, int]
    skipped_agents: list[str]


async def dispatch_agents(
    *,
    crawl_result: Any,
    deterministic_findings: list[dict[str, Any]],
    teams: Iterable[str] | None = None,
    only_agents: Iterable[str] | None = None,
    model: str = DEFAULT_MODEL,
    extras: dict[str, Any] | None = None,
) -> AgentRunResult:
    """Run every applicable specialist agent in parallel.

    Returns a flat list of agent findings ready to be persisted alongside
    deterministic findings. Returns an empty result (no error) if no
    ANTHROPIC_API_KEY is set.

    `only_agents`: if provided (e.g. ["A5", "C4"]), restrict the run to those
    agent short codes - used by the "AI search only" fallback dispatch.
    """
    keys = get_keys()
    if not keys.anthropic:
        log.info("agent_dispatch_skipped_no_key")
        return AgentRunResult(findings=[], per_agent_counts={}, skipped_agents=[])
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        log.warning("agent_dispatch_anthropic_sdk_missing", error=str(e))
        return AgentRunResult(findings=[], per_agent_counts={}, skipped_agents=[])

    agents = load_agents()
    check_specs = load_check_specs()
    if teams is not None:
        teams_set = {t.lower() for t in teams}
        agents = [a for a in agents if a.team.lower() in teams_set]
    if only_agents is not None:
        wanted = {s.upper() for s in only_agents}
        agents = [a for a in agents if a.short.upper() in wanted]

    client = anthropic.AsyncAnthropic(api_key=keys.anthropic)
    tasks = []
    runnable: list[AgentDefinition] = []
    skipped: list[str] = []
    for agent in agents:
        checks = checks_for_agent(agent.short, check_specs)
        if not checks:
            # Agent has no ai-assisted checks today (meta agents, or all-deterministic)
            skipped.append(agent.short)
            continue
        ctx = build_agent_context(
            agent=agent,
            checks=checks,
            crawl_result=crawl_result,
            deterministic_findings=deterministic_findings,
            extras=extras,
        )
        runnable.append(agent)
        tasks.append(_call_agent(client, agent, ctx, model=model))

    if not tasks:
        return AgentRunResult(findings=[], per_agent_counts={}, skipped_agents=skipped)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_findings: list[dict[str, Any]] = []
    per_agent_counts: dict[str, int] = {}
    for agent, res in zip(runnable, results):
        if isinstance(res, Exception):
            log.warning("agent_exception", agent=agent.short, error=f"{type(res).__name__}: {res}")
            per_agent_counts[agent.short] = 0
            continue
        per_agent_counts[agent.short] = len(res)
        for finding in res:
            finding["_agent"] = agent.short
            all_findings.append(finding)

    return AgentRunResult(
        findings=all_findings,
        per_agent_counts=per_agent_counts,
        skipped_agents=skipped,
    )
