"""On-demand Policy Radar lookup: answer an operator's ad-hoc policy question LIVE.

The always-on watcher (``policy_watch.py`` + ``workers/tasks/policy.py``) diffs a
curated set of Google sources on a beat. This is its on-DEMAND twin: an operator types
a topic and we answer it right now by letting Claude do the WEB SEARCH ITSELF.

    Anthropic messages.create with the SERVER-SIDE web_search tool -> Claude searches
    the web, reads the pages, and synthesizes a cited, structured answer.

This replaces the old scrape-one-page pipeline (Serper -> pick top result -> SSRF-fetch
its text -> Haiku summarize), which returned useless "the document does not contain that
info" answers whenever the picked page was JS-rendered (e.g. developers.google.com serves
only nav/header HTML to a plain fetch). Serper + the SSRF fetcher are DROPPED from this
feature; they still power the always-on watcher (``policy_watch.py``), untouched.

The core (:func:`run_policy_ask`) is PURE - the researcher and the cost gate are injected
- so it unit-tests with a ``FakeResearcher`` + a fake gate: NO network, NO DB, NO real
provider. It reuses the EXISTING ``policy`` money-dial (no new dial): the ACTUAL spend is
committed after the call as the Anthropic TOKEN cost (``pricing.anthropic_cost`` from the
returned usage) PLUS the WEB-SEARCH cost (``pricing.web_search_cost`` x the number of
searches Claude ran, read from ``usage.server_tool_use.web_search_requests``; if the SDK
doesn't surface it, ``max_uses`` is used as a defensive high estimate).

Degrade, never crash. Every seam that cannot run returns a clean, structured "degraded"
answer (a clear message, ``urgency='informational'``, no rules, no sources):

* no Anthropic key / no ``[ai]`` SDK (``researcher is None``) -> keyless degrade; the gate
  is NOT consulted.
* a cost-gate block (dial off / by-hand, client cap, global spend halt) -> NO provider
  call happens and the gate is NEVER bypassed.
* the research call fails (transport error, or a model/SDK that can't web-search) -> a
  clean degrade with no spend committed (usage is unknown, so nothing is billed).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import AnthropicResearcher, Researcher

logger = get_logger("app.services.policy_ask")

# The EXISTING Policy-Radar money-dial (schemas/cost.py) - reused, no new dial. The one
# provider this flow spends on; ``job_type`` groups the cost-log rows.
_FEATURE = "policy"
_PROVIDER_ANTHROPIC = "Anthropic"
_JOB_TYPE = "policy_ask"

# Bound the reply and the distilled fields. The token ceiling is generous so an
# on-demand answer can be genuinely IN-DEPTH (paired with the Sonnet research model).
_ANSWER_MAX_TOKENS = 2048
_MAX_RULES = 10
_MAX_SOURCES = 6

# Stable, machine-branchable degrade reasons surfaced on the response.
DEGRADE_NO_ANTHROPIC = "anthropic_unconfigured"
DEGRADE_RESEARCH_FAILED = "research_failed"

_URGENCIES = frozenset({"urgent", "informational"})


# --------------------------------------------------------------------------- #
# Provider wiring (key-gated builders; None == degrade)
# --------------------------------------------------------------------------- #
def build_ask_researcher(settings: Settings) -> Researcher | None:
    """The key-gated web-search researcher, or ``None`` (degraded) when unconfigured.

    Reuses the SAME optional ``anthropic_api_key`` every other AI seam gates on; a missing
    key OR an absent ``[ai]`` SDK returns ``None`` (degrade, never crash). It NEVER logs
    the secret, only the reason.
    """
    key = settings.anthropic_api_key
    if not key:
        logger.info("policy_ask_degraded", reason=DEGRADE_NO_ANTHROPIC)
        return None
    try:
        return AnthropicResearcher(
            api_key=key.get_secret_value(),
            model=settings.policy_research_model,
        )
    except ProviderNotConfiguredError:
        logger.info("policy_ask_degraded", reason="anthropic_sdk_absent")
        return None


class _NullAskCache:
    """A no-op ``CostCache``: each ask is a unique live lookup, never a cache hit; the
    dial + budgets still gate it. ``cache_key`` is always ``None`` here, so the gate never
    actually touches this cache - it only satisfies the ``CostGate`` constructor."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def build_ask_gate() -> CostGate:
    """The real cost gate over the Postgres cost store (no cache - see ``_NullAskCache``)."""
    return CostGate(PostgresCostStore(), _NullAskCache())


# --------------------------------------------------------------------------- #
# Pure helpers: the research prompt + the JSON parse
# --------------------------------------------------------------------------- #
def build_research_prompt(topic: str) -> str:
    """The user turn for one on-demand topic (the system prompt carries the JSON contract
    + the research instruction; this is the concrete question)."""
    cleaned = " ".join(topic.split())
    return (
        "Research this Google Search policy / algorithm topic and answer the operator's "
        f'question: "{cleaned}". Search the web for current, authoritative guidance before '
        "answering."
    )


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


def _clamp_urgency(value: object) -> str:
    """Lower-case + validate against ``urgent|informational``; default informational."""
    text = str(value or "").strip().lower()
    return text if text in _URGENCIES else "informational"


def _string_list(value: object, *, limit: int) -> list[str]:
    """Coerce a model value into a bounded list of non-empty stripped strings."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


# Words that flip an answer to "act soon" when the model gave no urgency (best-effort;
# the JSON path gets its urgency straight from the model instead).
_URGENT_HINTS: tuple[str, ...] = (
    "manual action", "penalty", "deindex", "deadline", "rolling out", "rollout",
    "enforcement", "required change", "core update", "spam policy",
)


def _heuristic_urgency(topic: str, answer: str) -> str:
    """Cheap urgency signal for a non-JSON answer: urgent if it smells time-sensitive."""
    blob = f"{topic} {answer}".lower()
    return "urgent" if any(hint in blob for hint in _URGENT_HINTS) else "informational"


@dataclass(frozen=True)
class PolicyAsk:
    """One distilled answer: the prose, its urgency, the key rules, the source URLs."""

    answer: str
    urgency: str
    rules: list[str]
    sources: list[str]


def _no_answer_message() -> str:
    return (
        "The lookup ran but returned no usable answer for that topic. Try rephrasing it "
        "(e.g. name the specific policy, update, or feature)."
    )


def parse_research(raw: str, *, web_sources: list[str], topic: str) -> PolicyAsk:
    """Parse the researcher's reply into a ``PolicyAsk``, DEGRADING defensively.

    The reply SHOULD be strict JSON (``answer`` / ``urgency`` / ``key_rules`` /
    ``sources``); on any parse miss the answer is NOT lost - the cleaned raw text becomes
    the answer with a heuristic urgency. ``web_sources`` are the URLs Claude actually
    retrieved via web_search (the authoritative citations); they lead the source list,
    then any JSON-declared URLs, deduped and bounded."""
    data = _extract_json(raw)
    if data is not None:
        answer = str(data.get("answer") or "").strip()
        rules = _string_list(data.get("key_rules") or data.get("rules"), limit=_MAX_RULES)
        json_sources = _string_list(data.get("sources"), limit=_MAX_SOURCES)
        urgency = _clamp_urgency(data.get("urgency"))
    else:
        answer = " ".join(raw.split()).strip()
        rules, json_sources = [], []
        urgency = _heuristic_urgency(topic, answer)

    sources: list[str] = []
    for url in [*web_sources, *json_sources]:
        cleaned = url.strip()
        if cleaned and cleaned not in sources:
            sources.append(cleaned)
        if len(sources) >= _MAX_SOURCES:
            break

    return PolicyAsk(
        answer=answer or _no_answer_message(),
        urgency=urgency,
        rules=rules,
        sources=sources[:_MAX_SOURCES],
    )


# --------------------------------------------------------------------------- #
# The result + the pure, injectable core
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AskResult:
    """The verdict of one :func:`run_policy_ask` run (a small, comparable value)."""

    topic: str
    status: str  # ok | degraded
    answer: str
    urgency: str
    rules: list[str]
    sources: list[str]
    reason: str = ""


def _degraded(topic: str, reason: str, message: str) -> AskResult:
    return AskResult(
        topic=topic,
        status="degraded",
        answer=message,
        urgency="informational",
        rules=[],
        sources=[],
        reason=reason,
    )


def _keyless_message(provider: str) -> str:
    return (
        f"Policy lookup is degraded: no {provider} key is configured. The live topic "
        "research runs once the key is activated; the detected change-events and the "
        "knowledge base below still answer from what the watcher has already found."
    )


def _blocked_message(outcome: str) -> str:
    return (
        f"Policy lookup is paused by the money-dial ({outcome}). Adjust the 'policy' "
        "dial or the budget, or read the change-events and knowledge base below."
    )


def _research_failed_message() -> str:
    return (
        "The live web research could not complete just now. Try again shortly, or read "
        "the change-events and knowledge base below."
    )


def run_policy_ask(
    topic: str,
    *,
    researcher: Researcher | None,
    gate: CostGate,
    settings: Settings,
) -> AskResult:
    """Research ONE on-demand policy topic via server-side web search. Pure; degrades.

    The gate contract is reused verbatim (evaluate -> call -> commit): on any non-allowed
    outcome NO provider call happens and the gate is not bypassed. The single paid call
    (the Anthropic web-search research) is metered under the ``policy`` dial, and the
    ACTUAL cost committed after the call is the TOKEN cost + the WEB-SEARCH cost.
    """
    clean_topic = " ".join(topic.split())

    # Anthropic (with web search) is the WHOLE answer engine now; without it we cannot
    # answer at all, so a missing key is the only keyless degrade. The gate is NOT touched.
    if researcher is None:
        return _degraded(clean_topic, DEGRADE_NO_ANTHROPIC, _keyless_message("Anthropic"))

    max_searches = max(1, int(settings.policy_research_max_searches))
    model = settings.policy_research_model

    # One pre-check estimate: the token-analysis estimate plus the worst-case web-search
    # spend (every allowed search used). The COMMITTED value below is the real spend.
    estimate = settings.policy_analysis_cost_estimate + pricing.web_search_cost(
        settings, searches=max_searches
    )
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,  # org-level staff lookup; still under the global spend halt
        provider=_PROVIDER_ANTHROPIC,
        estimated_cost=float(estimate),
        job_type=_JOB_TYPE,
        cache_key=None,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # dial off / by-hand, client cap, or the global spend halt: NO provider call.
        return _degraded(clean_topic, f"cost_gate:{decision.outcome}", _blocked_message(decision.outcome))

    # The single paid call: Claude searches the web itself and returns a cited answer.
    try:
        research = researcher.research(
            build_research_prompt(clean_topic),
            model=model,
            max_tokens=_ANSWER_MAX_TOKENS,
            max_searches=max_searches,
        )
    except Exception:  # transport / SDK / model-not-web-search-capable: degrade, don't crash
        logger.info("policy_ask_research_failed")
        return _degraded(clean_topic, DEGRADE_RESEARCH_FAILED, _research_failed_message())

    # Commit the ACTUAL spend: the Anthropic TOKEN cost + the WEB-SEARCH cost. The number
    # of searches is read from usage when the SDK surfaces it, else estimated at max_uses.
    token_cost = pricing.anthropic_cost(
        settings, model=model, input_tokens=research.input_tokens, output_tokens=research.output_tokens
    )
    searches = research.searches if research.searches is not None else max_searches
    search_cost = pricing.web_search_cost(settings, searches=searches)
    gate.commit(ctx, token_cost + search_cost)

    ask = parse_research(research.text, web_sources=research.sources, topic=clean_topic)
    return AskResult(
        topic=clean_topic,
        status="ok",
        answer=ask.answer,
        urgency=ask.urgency,
        rules=ask.rules,
        sources=ask.sources,
    )
