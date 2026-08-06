"""On-demand Policy Radar lookup: answer an operator's ad-hoc policy question LIVE.

The always-on watcher (``policy_watch.py`` + ``workers/tasks/policy.py``) diffs a
curated set of Google sources on a beat. This is its on-DEMAND twin: an operator types
a topic and we answer it right now with PURE Claude generation - the Anthropic Messages
API answering from its OWN current expert knowledge:

    Anthropic messages.create (NO tools, NO web) -> Claude synthesizes a cited,
    structured answer from what it already knows about Google Search policy.

This is a deliberate move OFF web-search grounding: the web-search-grounded results were
returning WRONG guidance while Claude's direct answers were correct, so the whole Policy
path now runs entirely on the Cloud API with pure generation. (The dormant web-search
``Researcher`` seam in ``integrations/llm.py`` is left in place but is no longer used by
this flow.)

The core (:func:`run_policy_ask`) is PURE - the summarizer and the cost gate are injected
- so it unit-tests with a fake ``SystemSummarizer`` + a fake gate: NO network, NO DB, NO
real provider. It reuses the EXISTING ``policy`` money-dial (no new dial): the ACTUAL spend
committed after the call is the Anthropic TOKEN cost ONLY (``pricing.anthropic_cost`` from
the returned usage) - there is NO web-search cost term any more.

Degrade, never crash. Every seam that cannot run returns a clean, structured "degraded"
answer (a clear message, ``urgency='informational'``, no rules, no sources):

* no Anthropic key / no ``[ai]`` SDK (``summarizer is None``) -> keyless degrade; the gate
  is NOT consulted.
* a cost-gate block (dial off / by-hand, client cap, global spend halt) -> NO provider
  call happens and the gate is NEVER bypassed.
* the summarize call fails (transport error, SDK issue) -> a clean degrade with no spend
  committed (usage is unknown, so nothing is billed).
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
from integrations.llm import AnthropicSummarizer, SystemSummarizer

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

# Frozen, factual system prompt for the on-demand lookup. Claude answers the operator's
# Google-Search policy/algorithm question from its OWN current expert knowledge - NO tools,
# NO web - as STRICT JSON so the parse below is deterministic.
_ASK_SYSTEM_PROMPT = (
    "You are a senior SEO and Google Search policy expert advising an agency operator. "
    "Answer the operator's question about Google Search ranking, algorithm, spam, "
    "structured-data, or helpful-content policy from your OWN current, expert knowledge. "
    "Do NOT use any tools and do NOT browse the web - rely only on what you already know. "
    "Respond with STRICT JSON ONLY - no prose, no markdown, no code fences - with EXACTLY "
    "these keys: answer (a concise 2-4 sentence plain-language answer to the operator's "
    'question), urgency (one of "urgent" or "informational" - "urgent" ONLY if the '
    "operator should act soon, e.g. an active rollout, a newly required change, or a "
    "manual-action risk), key_rules (an array of short strings, each a concrete rule or "
    "requirement), sources (an array of authoritative URLs you can cite from your own "
    "knowledge, e.g. Google Search Central documentation - may be empty if you are not "
    "certain of an exact URL). Never invent a URL you are not confident is real."
)


# --------------------------------------------------------------------------- #
# Provider wiring (key-gated builders; None == degrade)
# --------------------------------------------------------------------------- #
def build_ask_summarizer(settings: Settings) -> SystemSummarizer | None:
    """The key-gated pure-generation summarizer, or ``None`` (degraded) when unconfigured.

    Reuses the SAME optional ``anthropic_api_key`` every other AI seam gates on; a missing
    key OR an absent ``[ai]`` SDK returns ``None`` (degrade, never crash). It NEVER logs
    the secret, only the reason. The Sonnet ``policy_research_model`` rides in as the
    ``model_heavy`` tier so an on-demand answer is genuinely in-depth.
    """
    key = settings.anthropic_api_key
    if not key:
        logger.info("policy_ask_degraded", reason=DEGRADE_NO_ANTHROPIC)
        return None
    try:
        return AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_heavy=settings.policy_research_model,
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
# Pure helpers: the user prompt + the JSON parse
# --------------------------------------------------------------------------- #
def build_ask_user_prompt(topic: str) -> str:
    """The user turn for one on-demand topic (the system prompt carries the JSON contract
    + the from-knowledge instruction; this is the concrete question)."""
    cleaned = " ".join(topic.split())
    return f'Answer this Google Search policy / algorithm question for the operator: "{cleaned}".'


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
    """Parse the model's reply into a ``PolicyAsk``, DEGRADING defensively.

    The reply SHOULD be strict JSON (``answer`` / ``urgency`` / ``key_rules`` /
    ``sources``); on any parse miss the answer is NOT lost - the cleaned raw text becomes
    the answer with a heuristic urgency. There is no web retrieval any more, so
    ``web_sources`` is passed empty by ``run_policy_ask``; only the JSON-declared
    ``sources`` (URLs Claude can cite from its own knowledge) flow through, deduped and
    bounded. The parameter is kept so any future retrieval seam can lead the source list."""
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
        "lookup runs once the key is activated; the detected change-events and the "
        "knowledge base below still answer from what the watcher has already found."
    )


def _blocked_message(outcome: str) -> str:
    return (
        f"Policy lookup is paused by the money-dial ({outcome}). Adjust the 'policy' "
        "dial or the budget, or read the change-events and knowledge base below."
    )


def _research_failed_message() -> str:
    return (
        "The live policy lookup could not complete just now. Try again shortly, or read "
        "the change-events and knowledge base below."
    )


def run_policy_ask(
    topic: str,
    *,
    summarizer: SystemSummarizer | None,
    gate: CostGate,
    settings: Settings,
) -> AskResult:
    """Answer ONE on-demand policy topic via PURE Claude generation. Pure; degrades.

    The gate contract is reused verbatim (evaluate -> call -> commit): on any non-allowed
    outcome NO provider call happens and the gate is not bypassed. The single paid call
    (the Anthropic Messages generation) is metered under the ``policy`` dial, and the
    ACTUAL cost committed after the call is the TOKEN cost ONLY (no web-search term).
    """
    clean_topic = " ".join(topic.split())

    # Anthropic is the WHOLE answer engine now; without it we cannot answer at all, so a
    # missing key is the only keyless degrade. The gate is NOT touched.
    if summarizer is None:
        return _degraded(clean_topic, DEGRADE_NO_ANTHROPIC, _keyless_message("Anthropic"))

    model = settings.policy_research_model

    # One pre-check estimate: the flat token-analysis estimate (usage is not yet known).
    # The COMMITTED value below is the real token spend.
    estimate = settings.policy_analysis_cost_estimate
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

    # The single paid call: Claude answers from its own expert knowledge (no tools/web).
    try:
        result = summarizer.summarize(
            build_ask_user_prompt(clean_topic),
            model=model,
            max_tokens=_ANSWER_MAX_TOKENS,
            system=_ASK_SYSTEM_PROMPT,
        )
    except Exception:  # transport / SDK failure: degrade, don't crash
        logger.info("policy_ask_generation_failed")
        return _degraded(clean_topic, DEGRADE_RESEARCH_FAILED, _research_failed_message())

    # Commit the ACTUAL spend: the Anthropic TOKEN cost only (no web-search cost).
    token_cost = pricing.anthropic_cost(
        settings, model=model, input_tokens=result.input_tokens, output_tokens=result.output_tokens
    )
    gate.commit(ctx, token_cost)

    ask = parse_research(result.text, web_sources=[], topic=clean_topic)
    return AskResult(
        topic=clean_topic,
        status="ok",
        answer=ask.answer,
        urgency=ask.urgency,
        rules=ask.rules,
        sources=ask.sources,
    )
