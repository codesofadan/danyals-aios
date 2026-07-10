"""Claude-powered narrative report writer.

Takes the deterministic audit output (findings, scores, crawl metadata) and
asks Claude to fuse it into a single consulting-grade Markdown report. Every
claim must cite a check_id from the findings array — the prompt enforces
the anti-hallucination rule from CLAUDE.md ("every finding has evidence").

Backend: Anthropic API via the official SDK. Uses prompt caching on the
findings payload so re-rendering the same audit is cheap.

Falls back gracefully:
- No ANTHROPIC_API_KEY -> log + skip, do not crash the audit.
- API error -> log + skip, deterministic MD/HTML/PDF still write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audit_engine.config import get_branding, get_keys
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)


NARRATIVE_MODEL = "claude-opus-4-7"
MAX_TOKENS_OUT = 16000

SYSTEM_PROMPT = """You are the senior SEO consultant at __BRAND__ writing the final unified audit report.

Voice: McKinsey / Bain / iPullRank / Aleyda Solis. Specific, evidence-backed, no marketing fluff, no emojis, no em dashes.

Hard rules:
1. EVERY claim must cite a check_id from the findings array. Format: `(ON-041)` or `(LOC-032)` after each claim. If you cannot cite a check_id, do not make the claim.
2. Use exact numbers from evidence. Never round, never approximate. If a title is 103 characters, say 103 — not "around 100".
3. No hallucination. If the findings do not support a claim, omit it. Better to leave a section thin than to invent.
4. No em dash (U+2014). Use hyphens or rewrite.
5. Times in PKT (Asia/Karachi, UTC+5).
6. Specific remediations. "Change the H1 on /category/sofas from missing to '<specific suggestion based on the page title>'", not "fix headings".
7. Consulting register, not blog tone. Active voice. No "we hope" or "in conclusion".

Output structure (Markdown, in this exact order):

# SEO Audit | {domain}

## Executive Summary
A 4-6 sentence judgment of where the site stands, leading with the overall score and the single biggest risk. Name the top 3 issues by severity + impact, each with a check_id cite. End with the one quick win the client should ship this week.

## Scorecard
Render the score table the deterministic pipeline produced. Then 1-2 sentences interpreting each non-null dimension (what good/bad looks like at that score).

## Top Findings
For each of the top 8-12 findings (sorted critical -> major -> minor, then by score asc within severity), produce:
### `{check_id}` {check_name} | {severity}
**Evidence.** What the audit found, with exact numbers from the evidence JSON.
**Why it matters.** 2-3 sentences of SEO consequence (rankings, AI citations, conversion, etc.) tied to the specific evidence.
**Fix.** Specific, actionable. Reference the affected URL or element. If a remediation field is present on the finding, build on it; do not repeat it verbatim.

## Findings by Category
For each of on-page / technical / off-page / local-seo that has findings, produce a 2-3 sentence narrative summary that names the 2-3 most representative issues by check_id and what they collectively reveal about the site.

## Strengths
3-5 things this site already does well, each cited with a passing check_id. No fabrication; pull from findings with status=pass and high scores.

## 30-60-90 Day Plan
Three labeled phases.
- **0-30 days:** P0 issues, name 3-5 specific tasks with the check_id each fixes.
- **30-60 days:** P1 work.
- **60-90 days:** strategic items.

## Methodology
Pages crawled, integrations used (only those that actually returned data), checks evaluated, gate results if present. 4-6 lines max.

Length target: 1200-2500 words. Long enough to be useful, short enough to be read.
"""


@dataclass
class NarrativeContext:
    """The compact payload passed to Claude. Tightly capped to fit context cheaply."""

    domain: str
    run_uuid: str
    profile: str
    started_at: str
    duration_sec: float
    pages_crawled: int
    scores: dict[str, float | None]
    severity_counts: dict[str, int]
    findings: list[dict[str, Any]]
    extras: dict[str, Any]


SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def _compact_finding(f: dict[str, Any]) -> dict[str, Any]:
    """Strip a finding down to what Claude needs - keeps the API payload lean."""
    ev = f.get("evidence_json")
    if isinstance(ev, str) and ev:
        try:
            ev_obj = json.loads(ev)
            # cap large evidence dicts
            if isinstance(ev_obj, dict):
                ev_obj = {k: ev_obj[k] for k in list(ev_obj)[:6]}
        except json.JSONDecodeError:
            ev_obj = ev[:200]
    else:
        ev_obj = None
    return {
        "id": f.get("check_id"),
        "name": f.get("check_name"),
        "category": f.get("category"),
        "owner": f.get("owner_agent"),
        "status": f.get("status"),
        "severity": f.get("severity"),
        "score": f.get("score"),
        "evidence": ev_obj,
        "remediation": f.get("remediation"),
        "url": f.get("url"),
    }


def _select_findings(findings: list[dict[str, Any]], *, max_findings: int = 80) -> list[dict[str, Any]]:
    """Prioritize: all critical+major, then top-info by score asc. Cap at max."""
    crit_maj = [f for f in findings if f.get("severity") in ("critical", "major")]
    minor = [f for f in findings if f.get("severity") == "minor"]
    info = [f for f in findings if f.get("severity") == "info"]
    # Sort each bucket by score ascending (worst first) within severity
    crit_maj.sort(key=lambda f: (SEVERITY_RANK.get(f.get("severity", "info"), 99), f.get("score") or 0))
    minor.sort(key=lambda f: f.get("score") or 0)
    info.sort(key=lambda f: -(f.get("score") or 0))  # best passing first as strengths
    chosen = crit_maj + minor[:20] + info[:20]
    return [_compact_finding(f) for f in chosen[:max_findings]]


def build_context(
    *,
    domain: str,
    run_uuid: str,
    profile: str,
    started_at: str,
    duration_sec: float,
    pages_crawled: int,
    scores: dict[str, float | None],
    findings: list[dict[str, Any]],
    extras: dict[str, Any] | None = None,
) -> NarrativeContext:
    sev_counts: dict[str, int] = {}
    for f in findings:
        sev_counts[f.get("severity", "info")] = sev_counts.get(f.get("severity", "info"), 0) + 1
    return NarrativeContext(
        domain=domain,
        run_uuid=run_uuid,
        profile=profile,
        started_at=started_at,
        duration_sec=duration_sec,
        pages_crawled=pages_crawled,
        scores=scores,
        severity_counts=sev_counts,
        findings=_select_findings(findings),
        extras=extras or {},
    )


def _user_message(ctx: NarrativeContext) -> str:
    payload = {
        "domain": ctx.domain,
        "run_uuid": ctx.run_uuid,
        "profile": ctx.profile,
        "started_at_pkt": ctx.started_at,
        "duration_sec": ctx.duration_sec,
        "pages_crawled": ctx.pages_crawled,
        "scores": ctx.scores,
        "severity_counts": ctx.severity_counts,
        "extras": ctx.extras,
        "findings": ctx.findings,
    }
    return (
        "Write the final unified SEO audit report for the data below.\n"
        "Follow the system prompt's structure exactly. Cite a check_id after every claim.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )


def write_narrative(ctx: NarrativeContext, *, out_path: Path) -> Path | None:
    """Call Claude and write the narrative Markdown. Returns the path or None."""
    keys = get_keys()
    if not keys.anthropic:
        log.info("narrative_skipped_no_key")
        return None
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        log.warning("narrative_anthropic_sdk_missing", error=str(e))
        return None

    client = anthropic.Anthropic(api_key=keys.anthropic)
    try:
        msg = client.messages.create(
            model=NARRATIVE_MODEL,
            max_tokens=MAX_TOKENS_OUT,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT.replace("__BRAND__", get_branding().brand_name),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _user_message(ctx)}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("narrative_api_failed", error=f"{type(e).__name__}: {e}")
        return None

    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    body = "\n".join(parts).strip()
    if not body:
        log.warning("narrative_empty_response")
        return None

    cache_read = getattr(msg.usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
    log.info(
        "narrative_written",
        path=str(out_path),
        input_tokens=msg.usage.input_tokens,
        output_tokens=msg.usage.output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
    )
    out_path.write_text(body, encoding="utf-8")
    return out_path
