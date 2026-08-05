"""Daily Policy-Radar GENERATOR: produce N current SEO policy items via Anthropic.

This REPLACES the Google-scrape watcher (``policy_watch.py`` + the ``watch_policy_sources``
beat) as the DEFAULT source of the Policy-Radar feed. Instead of diffing a curated set of
Google URLs by content hash, it lets Claude research the CURRENT, most important Google
Search ranking / policy / algorithm developments an agency must act on and return them as
``count`` structured, cited items:

    Anthropic messages.create with the SERVER-SIDE web_search tool -> Claude searches the
    web, reads the pages, and returns a STRICT-JSON ``{"items": [...]}`` array.

The core (:func:`run_policy_generation`) is PURE - the researcher and the cost gate are
injected - so it unit-tests with a ``FakeResearcher`` + a fake gate: NO network, NO DB, NO
real provider. It reuses the EXISTING ``policy`` money-dial (no new dial): the ACTUAL spend
committed after the call is the Anthropic TOKEN cost (``pricing.anthropic_cost``) PLUS the
WEB-SEARCH cost (``pricing.web_search_cost`` x searches). Each parsed item is clamped to the
0019 enum vocabulary by REUSING ``policy_watch.parse_analysis`` (one item at a time), so a
hallucinated label can never break the downstream insert.

Degrade, never crash (same contract as ``run_policy_ask``):

* no Anthropic key / no ``[ai]`` SDK (``researcher is None``) -> keyless degrade; the gate
  is NOT consulted, nothing is written.
* a cost-gate block (dial off / by-hand, client cap, global spend halt) -> NO provider call
  happens and the gate is NEVER bypassed.
* the research call fails (transport / SDK / model-not-web-search-capable) -> a clean
  degrade with no spend committed (usage is unknown, so nothing is billed).

The worker (``workers/tasks/policy.py``) owns the DB writes + the once-per-day idempotency
guard + the Celery entry point; this module is DB-free and Celery-free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext
from app.services.policy_watch import PolicyAnalysis, parse_analysis
from integrations.llm import Researcher

logger = get_logger("app.services.policy_generate")

# The EXISTING Policy-Radar money-dial (schemas/cost.py) - reused, no new dial.
_FEATURE = "policy"
_PROVIDER_ANTHROPIC = "Anthropic"
_JOB_TYPE = "policy_generate"

# Bound the reply (N rich items + JSON overhead) and the total item count.
_GEN_MAX_TOKENS = 3600
_MAX_ITEMS = 12

# Stable, machine-branchable degrade reasons.
DEGRADE_NO_ANTHROPIC = "anthropic_unconfigured"
DEGRADE_GENERATION_FAILED = "generation_failed"

# Frozen, factual system prompt for the daily brief. Instructs Claude to research the
# CURRENT top Google-Search developments and return a STRICT-JSON N-item array whose item
# shape matches ``policy_watch.PolicyAnalysis`` + a cited source_name/source_url.
_GENERATE_SYSTEM_PROMPT = (
    "You are a senior SEO and Google Search policy expert briefing an agency's operators. "
    "Use the web_search tool to research the CURRENT, most important Google Search ranking, "
    "algorithm, spam-policy, structured-data, and helpful-content developments an agency "
    "should act on right now - recent core / spam updates, guideline changes, SERP or "
    "AI-Overview shifts, and, when nothing is actively breaking, the highest-impact evergreen "
    "best practices. Prefer Google's official surfaces (developers.google.com / Search "
    "Central, blog.google, the Search Status dashboard, the Search Quality Rater Guidelines) "
    "and reputable SEO press. Respond with STRICT JSON ONLY - no prose, no markdown, no code "
    'fences - as an object {"items": [ ... ]} whose "items" is an array of DISTINCT policy '
    "items. Each item is an object with EXACTLY these keys: title (string), summary (2-4 "
    "plain-language sentences an operator can act on), severity (one of "
    '"critical"|"major"|"minor"|"info"), category (one of '
    '"algorithm"|"policy"|"technical"|"content"|"local"|"geo"), region (one of '
    '"global"|"national"), region_label (string, e.g. "Global"), source_name (string, the '
    "publication you took it from), source_url (string, a real URL you actually retrieved), "
    "rec_title (string, a short recommended action), rec_why (string), rec_action (string, "
    'the concrete step), target_module (one of "audit"|"content"|"portal"). Ground every '
    "item in a source you actually retrieved; never invent a URL."
)


def build_generate_prompt(count: int) -> str:
    """The user turn asking for ``count`` current policy items (the system prompt carries
    the JSON contract + the research instruction)."""
    n = max(1, int(count))
    return (
        f"Research and return the {n} most important, current Google Search policy and "
        f"algorithm developments an SEO agency should act on today. Return EXACTLY {n} "
        "distinct items in the JSON contract. Search the web for current, authoritative "
        "guidance before answering."
    )


@dataclass(frozen=True)
class GeneratedItem:
    """One generated policy item: the clamped analysis + its citation snapshots."""

    analysis: PolicyAnalysis
    source_name: str
    source_url: str


@dataclass(frozen=True)
class GenerationResult:
    """The verdict of one :func:`run_policy_generation` run."""

    status: str  # ok | degraded
    items: list[GeneratedItem]
    reason: str = ""


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from a model reply, tolerating surrounding
    prose / code fences by slicing the outermost ``{...}``. ``None`` on failure."""
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _clean_str(value: object, *, limit: int) -> str:
    """Whitespace-normalized, length-bounded string (empty on a falsy value)."""
    return " ".join(str(value or "").split())[:limit]


def parse_generation(raw: str, *, count: int, web_sources: list[str]) -> list[GeneratedItem]:
    """Parse the researcher's reply into a bounded list of ``GeneratedItem``, DEGRADING
    defensively.

    The reply SHOULD be strict JSON ``{"items": [ {..PolicyAnalysis fields..}, ... ]}``.
    A non-JSON reply, a missing / non-list ``items``, or a non-dict item all drop cleanly
    (that item is skipped; the whole reply -> ``[]``). Each item's enums are clamped to
    the 0019 vocabulary by REUSING ``policy_watch.parse_analysis``. ``web_sources`` (the
    URLs Claude actually retrieved) backstop an item that omitted its own ``source_url``.
    The result is capped at ``min(count, _MAX_ITEMS)``."""
    data = _extract_json(raw)
    if not data:
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    cap = min(max(1, int(count)), _MAX_ITEMS)
    fallback_url = web_sources[0] if web_sources else ""
    out: list[GeneratedItem] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        analysis = parse_analysis(
            json.dumps(raw_item),
            fallback_title="Google Search policy update",
            fallback_summary="A current Google Search policy or algorithm development.",
        )
        source_name = _clean_str(raw_item.get("source_name"), limit=120) or "Google Search Central"
        source_url = _clean_str(raw_item.get("source_url"), limit=500) or fallback_url
        out.append(GeneratedItem(analysis=analysis, source_name=source_name, source_url=source_url))
        if len(out) >= cap:
            break
    return out


def run_policy_generation(
    *,
    researcher: Researcher | None,
    gate: CostGate,
    settings: Settings,
    count: int | None = None,
) -> GenerationResult:
    """Generate ``count`` current policy items via server-side web search. Pure; degrades.

    The gate contract is reused verbatim (evaluate -> call -> commit): on any non-allowed
    outcome NO provider call happens and the gate is not bypassed. The single paid call is
    metered under the ``policy`` dial, and the ACTUAL cost committed after the call is the
    TOKEN cost + the WEB-SEARCH cost. ``count`` defaults to ``settings.policy_daily_count``.
    """
    n = int(count if count is not None else settings.policy_daily_count)

    # Anthropic (with web search) is the whole engine; a missing key is a keyless degrade
    # BEFORE the gate is touched (mirrors run_policy_ask).
    if researcher is None:
        logger.info("policy_generate_degraded", reason=DEGRADE_NO_ANTHROPIC)
        return GenerationResult(status="degraded", items=[], reason=DEGRADE_NO_ANTHROPIC)

    max_searches = max(1, int(settings.policy_research_max_searches))
    model = settings.policy_generate_model

    estimate = settings.policy_analysis_cost_estimate + pricing.web_search_cost(
        settings, searches=max_searches
    )
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,  # org-level daily brief; still under the global spend halt
        provider=_PROVIDER_ANTHROPIC,
        estimated_cost=float(estimate),
        job_type=_JOB_TYPE,
        cache_key=None,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("policy_generate_blocked", outcome=decision.outcome)
        return GenerationResult(status="degraded", items=[], reason=f"cost_gate:{decision.outcome}")

    try:
        research = researcher.research(
            build_generate_prompt(n),
            model=model,
            max_tokens=_GEN_MAX_TOKENS,
            max_searches=max_searches,
            system=_GENERATE_SYSTEM_PROMPT,
        )
    except Exception:  # transport / SDK / model-not-web-search-capable: degrade, don't crash
        logger.info("policy_generate_research_failed")
        return GenerationResult(status="degraded", items=[], reason=DEGRADE_GENERATION_FAILED)

    token_cost = pricing.anthropic_cost(
        settings, model=model, input_tokens=research.input_tokens, output_tokens=research.output_tokens
    )
    searches = research.searches if research.searches is not None else max_searches
    gate.commit(ctx, token_cost + pricing.web_search_cost(settings, searches=searches))

    items = parse_generation(research.text, count=n, web_sources=research.sources)
    logger.info("policy_generate_done", requested=n, produced=len(items))
    return GenerationResult(status="ok", items=items)
