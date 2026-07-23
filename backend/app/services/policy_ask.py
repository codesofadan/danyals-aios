"""On-demand Policy Radar lookup: answer an operator's ad-hoc policy question LIVE.

The always-on watcher (``policy_watch.py`` + ``workers/tasks/policy.py``) diffs a
curated set of Google sources on a beat. This is its on-DEMAND twin: an operator types
a topic and we answer it right now by

    Serper search (scoped to Google's official surfaces) -> pick the top authoritative
    result -> SSRF-guarded fetch of its text -> Claude Haiku distils a structured answer

The core (:func:`run_policy_ask`) is PURE - the searcher, fetcher, summarizer and cost
gate are all injected - so it unit-tests with a fake searcher + a ``FakeSummarizer`` +
a fake gate: NO network, NO DB, NO real provider. It reuses the EXISTING ``policy``
money-dial (no new dial): BOTH paid calls (the Serper query + the Haiku call) are
metered through the SAME gate, and the ACTUAL spend (``pricing.serper_cost`` +
``pricing.anthropic_cost``) is committed after the call.

Degrade, never crash. Every seam that cannot run simply returns a clean, structured
"degraded" answer (a clear message, ``urgency='informational'``, no rules, no sources):

* no Serper key (``searcher is None``)      -> keyless degrade; the gate is NOT consulted.
* no Anthropic key (``summarizer is None``) -> keyless degrade; the gate is NOT consulted.
* a cost-gate block (dial off / by-hand, client cap, org daily spend-stop) -> NO
  provider call happens and the gate is NEVER bypassed.
* the search finds no authoritative source, or the source is unreachable -> the Serper
  query's real cost is still committed (it was spent), then a clean degrade.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from app.config import Settings
from app.core.security import PrivateAddressError, extract_host
from app.logging_setup import get_logger
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from app.services.policy_watch import PolicyFetcher
from integrations.content_research import OrganicResult, SerperResearcher, SerpResearcher, SerpResult
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import AnthropicSummarizer, Summarizer

logger = get_logger("app.services.policy_ask")

# The EXISTING Policy-Radar money-dial (schemas/cost.py) - reused, no new dial. The two
# providers this flow spends on; ``job_type`` groups the cost-log rows.
_FEATURE = "policy"
_PROVIDER_SERPER = "Serper"
_PROVIDER_ANTHROPIC = "Anthropic"
_JOB_TYPE = "policy_ask"

# The official Google surfaces we trust as authoritative for a policy answer. A result
# host must equal one of these or be a subdomain of it (``developers.google.com`` and
# ``status.search.google.com`` both fold under ``google.com``; the rater guidelines
# live on ``raterhub.com``).
_AUTHORITATIVE_HOSTS: tuple[str, ...] = (
    "developers.google.com",
    "blog.google",
    "google.com",
    "raterhub.com",
)

# Bound the Haiku reply + the fetched text we feed it (a policy page can be large).
_ANSWER_MAX_TOKENS = 700
_PROMPT_MAX_CHARS = 12_000
_MAX_RULES = 8
_MAX_SOURCES = 6

# Stable, machine-branchable degrade reasons surfaced on the response.
DEGRADE_NO_SERPER = "serper_unconfigured"
DEGRADE_NO_ANTHROPIC = "anthropic_unconfigured"
DEGRADE_NO_SOURCE = "no_authoritative_source"
DEGRADE_UNREACHABLE = "source_unreachable"
DEGRADE_SERPER_ERROR = "serper_error"

_URGENCIES = frozenset({"urgent", "informational"})


# --------------------------------------------------------------------------- #
# Provider wiring (key-gated builders; None == degrade)
# --------------------------------------------------------------------------- #
def build_ask_searcher(settings: Settings) -> SerpResearcher | None:
    """The key-gated Serper researcher, or ``None`` (degraded) when unconfigured.

    Reuses the SAME ``serper_api_key`` the content module gates on. A missing key OR
    an unbuildable client returns ``None`` so the lookup degrades rather than raising -
    it NEVER logs the secret, only the reason.
    """
    key = settings.serper_api_key
    if not key:
        logger.info("policy_ask_degraded", reason=DEGRADE_NO_SERPER)
        return None
    try:
        return SerperResearcher(api_key=key.get_secret_value())
    except ProviderNotConfiguredError:
        logger.info("policy_ask_degraded", reason="serper_unavailable")
        return None


def build_ask_summarizer(settings: Settings) -> Summarizer | None:
    """The key-gated Claude Haiku summarizer, or ``None`` (degraded) when unconfigured.

    Reuses the SAME optional ``anthropic_api_key`` every other AI seam gates on; a
    missing key OR an absent ``[ai]`` SDK returns ``None`` (degrade, never crash).
    """
    key = settings.anthropic_api_key
    if not key:
        logger.info("policy_ask_degraded", reason=DEGRADE_NO_ANTHROPIC)
        return None
    try:
        return AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
        )
    except ProviderNotConfiguredError:
        logger.info("policy_ask_degraded", reason="anthropic_sdk_absent")
        return None


class _NullAskCache:
    """A no-op ``CostCache``: each ask is a unique live distillation, never a cache hit;
    the dial + budgets still gate it. ``cache_key`` is always ``None`` here, so the gate
    never actually touches this cache - it only satisfies the ``CostGate`` constructor."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def build_ask_gate() -> CostGate:
    """The real cost gate over the Postgres cost store (no cache - see ``_NullAskCache``)."""
    return CostGate(PostgresCostStore(), _NullAskCache())


# --------------------------------------------------------------------------- #
# Pure helpers: the query, the authoritative-result picker, the JSON parse
# --------------------------------------------------------------------------- #
def build_query(topic: str) -> str:
    """The Serper query for ``topic``, scoped to Google's official policy surfaces."""
    cleaned = " ".join(topic.split())
    return f"google search {cleaned} policy site:developers.google.com OR site:blog.google"


def _is_authoritative(url: str) -> bool:
    """Whether ``url``'s host is an official Google surface (DNS-free host parse)."""
    try:
        host = extract_host(url)
    except PrivateAddressError:
        return False
    return any(host == h or host.endswith("." + h) for h in _AUTHORITATIVE_HOSTS)


def pick_source(serp: SerpResult) -> OrganicResult | None:
    """The result to fetch: the first authoritative organic hit, else the top organic
    result (the site-scoped query already biases toward official surfaces; the fallback
    keeps a resilient answer, and the fetch is SSRF-guarded either way)."""
    for result in serp.organic:
        if result.link and _is_authoritative(result.link):
            return result
    for result in serp.organic:
        if result.link:
            return result
    return None


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


@dataclass(frozen=True)
class PolicyAsk:
    """One distilled answer: the prose, its urgency, the key rules, the source URLs."""

    answer: str
    urgency: str
    rules: list[str]
    sources: list[str]


def parse_ask(raw: str, *, fallback_answer: str, source_url: str) -> PolicyAsk:
    """Parse Haiku's reply into a ``PolicyAsk``, DEGRADING defensively.

    On any parse failure (empty / non-JSON / missing keys) the answer is NOT lost: it
    falls back to the source snippet, urgency defaults to ``informational``, and the
    fetched source URL is always cited even if the model returned none."""
    data = _extract_json(raw) or {}
    answer = str(data.get("answer") or "").strip() or fallback_answer
    rules = _string_list(data.get("rules"), limit=_MAX_RULES)
    sources = _string_list(data.get("sources"), limit=_MAX_SOURCES)
    if source_url and source_url not in sources:
        sources.insert(0, source_url)
    return PolicyAsk(
        answer=answer,
        urgency=_clamp_urgency(data.get("urgency")),
        rules=rules,
        sources=sources[:_MAX_SOURCES],
    )


def build_ungrounded_prompt(topic: str) -> str:
    """A plain-prose instruction used when no authoritative Google source is fetched.

    The operator still gets a real answer from Claude's own knowledge of Google Search
    policies / SEO best practice, instead of a "no source found" dead end. Deliberately
    asks for PROSE (not JSON) - it matches the summarizer's prose-only system prompt, so
    the reply is used verbatim as the answer (no brittle JSON parse, no topic-echo)."""
    return (
        "You are a senior SEO and Google Search policy expert advising an agency operator. "
        f'Answer this question clearly and practically: "{topic}".\n\n'
        "Explain the current Google guidance / best practice, what matters, and what to do. "
        "Be concrete and concise (a short paragraph, up to ~6 sentences). If it involves a "
        "risk of a manual action or an active algorithm change, say so plainly. Answer in "
        "plain prose only - no headings, no JSON, no code fences. Do not invent specific "
        "client data; answer from established Google Search documentation and best practice."
    )


def build_ask_prompt(topic: str, source_name: str, source_url: str, text: str) -> str:
    """The strict-JSON instruction fed to Haiku for one on-demand topic."""
    body = " ".join(text.split())[:_PROMPT_MAX_CHARS]
    return (
        "An SEO agency operator is asking about a Google Search policy / algorithm "
        f'topic: "{topic}".\n\n'
        f"Below is the text of an authoritative Google source ({source_name}, "
        f"{source_url}). Answer the operator's question STRICTLY from this source; do "
        "not invent rules that are not stated in it.\n\n"
        f"CONTENT:\n{body}\n\n"
        "Respond with STRICT JSON only (no prose, no code fences), with EXACTLY these "
        "keys: answer (a concise 2-4 sentence plain-language answer), urgency (one of "
        "urgent|informational - 'urgent' ONLY if the operator should act soon, e.g. an "
        "active rollout, a newly required change, or a manual-action risk), rules (an "
        "array of short strings, each a concrete rule or requirement from the source), "
        "sources (an array of the source URLs you used)."
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
        "search runs once the key is activated; the detected change-events and the "
        "knowledge base below still answer from what the watcher has already found."
    )


def _blocked_message(outcome: str) -> str:
    return (
        f"Policy lookup is paused by the money-dial ({outcome}). Adjust the 'policy' "
        "dial or the budget, or read the change-events and knowledge base below."
    )


# Words that flip an ungrounded answer to "act soon" (best-effort; the grounded path
# gets its urgency straight from the model's JSON instead).
_URGENT_HINTS: tuple[str, ...] = (
    "manual action", "penalty", "deindex", "deadline", "rolling out", "rollout",
    "enforcement", "required change", "core update", "spam policy",
)


def _heuristic_urgency(topic: str, answer: str) -> str:
    """Cheap urgency signal for an ungrounded answer: urgent if it smells time-sensitive."""
    blob = f"{topic} {answer}".lower()
    return "urgent" if any(hint in blob for hint in _URGENT_HINTS) else "informational"


def _no_source_message() -> str:
    return (
        "No authoritative Google source was found for that topic. Try rephrasing it "
        "(e.g. name the specific policy, update, or feature)."
    )


def _unreachable_message() -> str:
    return (
        "Found a Google source for that topic but could not read it right now. Try "
        "again shortly, or open the source directly."
    )


def run_policy_ask(
    topic: str,
    *,
    searcher: SerpResearcher | None,
    fetcher: PolicyFetcher,
    summarizer: Summarizer | None,
    gate: CostGate,
    settings: Settings,
) -> AskResult:
    """Search + fetch + summarize ONE on-demand policy topic. Pure; degrades, never crashes.

    The gate contract is reused verbatim (evaluate -> call -> commit): on any non-``call``
    outcome NO provider call happens and the gate is not bypassed. Both paid calls (the
    Serper query + the Haiku analysis) are metered under the SAME ``policy`` dial, and the
    ACTUAL cost is committed per provider after the call.
    """
    clean_topic = " ".join(topic.split())

    # Anthropic is the ANSWER engine: it answers from a fetched Google source when one is
    # found, else from its own Google-policy knowledge. Without it we cannot answer at all,
    # so that is the ONLY hard keyless degrade. Serper is now OPTIONAL grounding.
    if summarizer is None:
        return _degraded(clean_topic, DEGRADE_NO_ANTHROPIC, _keyless_message("Anthropic"))

    # One pre-check. The estimate covers the Claude call, plus the Serper query only when a
    # searcher is configured (grounding is best-effort; a missing Serper key just skips it).
    estimate = settings.policy_analysis_cost_estimate
    if searcher is not None:
        estimate += settings.content_research_cost_estimate
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,  # org-level staff lookup; still under the org daily spend-stop
        provider=_PROVIDER_ANTHROPIC,
        estimated_cost=float(estimate),
        job_type=_JOB_TYPE,
        cache_key=None,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # dial off / by-hand, client cap, or daily spend-stop: NO provider call.
        return _degraded(clean_topic, f"cost_gate:{decision.outcome}", _blocked_message(decision.outcome))

    # 1) BEST-EFFORT grounding: a live Serper search of Google's official surfaces, then an
    #    SSRF-guarded fetch of the top authoritative hit. Any miss (no key, provider error,
    #    no source, unreachable) falls through to an Anthropic-only answer - never a dead end.
    source: OrganicResult | None = None
    source_text = ""
    serper_spend = 0.0
    if searcher is not None:
        try:
            serp = searcher.serp(build_query(clean_topic))
            serper_spend = pricing.serper_cost(settings, queries=1)
            picked = pick_source(serp)
            if picked is not None:
                fetched = fetcher.fetch(picked.link)
                if fetched:
                    source, source_text = picked, fetched
        except Exception:  # transport / provider failure: skip grounding, still answer
            logger.info("policy_ask_serp_failed")

    # 2) Claude answers - GROUNDED strictly from the fetched source when we have one, else
    #    from its own established Google-policy knowledge.
    grounded = source is not None
    prompt = (
        build_ask_prompt(clean_topic, source.title, source.link, source_text)
        if grounded and source is not None
        else build_ungrounded_prompt(clean_topic)
    )
    llm = summarizer.summarize(
        prompt, model=settings.anthropic_model_summary, max_tokens=_ANSWER_MAX_TOKENS
    )
    anthropic_spend = pricing.anthropic_cost(
        settings,
        model=settings.anthropic_model_summary,
        input_tokens=llm.input_tokens,
        output_tokens=llm.output_tokens,
    )
    # Commit the ACTUAL spend per provider (only Serper if it actually ran).
    if serper_spend:
        gate.commit(replace(ctx, provider=_PROVIDER_SERPER), serper_spend)
    gate.commit(ctx, anthropic_spend)

    if grounded and source is not None:
        ask = parse_ask(llm.text, fallback_answer=source.snippet or clean_topic, source_url=source.link)
        return AskResult(
            topic=clean_topic, status="ok", answer=ask.answer,
            urgency=ask.urgency, rules=ask.rules, sources=ask.sources,
        )

    # Ungrounded: the model's prose IS the answer (no JSON parse -> no topic-echo fallback).
    answer = " ".join(llm.text.split()).strip() or _no_source_message()
    return AskResult(
        topic=clean_topic, status="ok", answer=answer,
        urgency=_heuristic_urgency(clean_topic, answer), rules=[], sources=[],
    )
