"""Wave 5: the GMB post GENERATOR core - a PURE, cost-gated, writer-injected function
that drafts a Google Business Profile post that respects GBP content policy and best
practices (concise, a proper CTA, length-capped, NO em dashes).

Design mirrors ``app/services/ai_assist.py`` exactly: the summarizer + the cost gate
are INJECTED, so :func:`run_gmb_generation` unit-tests deterministically with a
``FakeSummarizer`` + a fake ``CostStore`` - zero network. Degrade, never crash:

* no Anthropic key (``summarizer is None``) -> a keyless degrade; the gate is never
  consulted and no provider call happens.
* a cost-gate block (dial ``gmb`` off / by-hand, client cap, org daily spend-stop) ->
  a blocked degrade; NO provider call happens and the gate is never bypassed.

The generated body is ALWAYS run through the content guard's ``strip_dashes`` (the
hard em/en-dash guarantee) and hard-capped to Google's character limit BEFORE the GBP
policy check scores it - so a returned ``ok`` post is dash-free and within limits.

NOTE: the ``gmb`` money-dial feature is not yet registered in ``app/schemas/cost.py``
(a reserved file). Until an operator adds it, ``dial_mode('gmb')`` resolves to ``off``
and every generation DEGRADES honestly (blocked) rather than spending - which is the
intended dormant state. This module references the key ``"gmb"`` as if it exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from app.modules.gmb.policy import GBP_MAX_CHARS, GbpPolicyReport, check_gbp_policy
from app.services import pricing
from app.services.content_guard import strip_dashes
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import AnthropicSummarizer, Summarizer

logger = get_logger("app.modules.gmb.service")

# The money-dial feature key + provider label these calls gate against. ``"gmb"`` is
# referenced as if registered; see the module docstring (dormant until an op adds it).
_FEATURE = "gmb"
_PROVIDER = "Anthropic"
_JOB_TYPE = "gmb"

# Upfront pre-check estimate + output bound (module constants - no reserved-config
# setting yet; a ``gmb_post_cost_estimate`` / ``gmb_max_tokens`` Setting is reported).
GMB_COST_ESTIMATE = 0.02
GMB_MAX_TOKENS = 600

DEGRADE_KEYLESS = "anthropic_unconfigured"

GenStatus = str  # "ok" | "degraded"


@dataclass(frozen=True)
class GmbGenerationResult:
    """The verdict of one :func:`run_gmb_generation` run.

    ``status`` is ``ok`` (a real draft) or ``degraded`` (keyless / gate-blocked, no
    provider call). ``body`` is the dash-free, length-capped post text; ``policy`` is
    its GBP policy report; ``reason`` explains a degrade; ``cost`` is the committed
    spend (0 on a degrade).
    """

    status: GenStatus
    body: str
    policy: GbpPolicyReport
    reason: str = ""
    cost: float = 0.0


def build_gmb_summarizer(settings: Settings) -> Summarizer | None:
    """The key-gated summarizer, or ``None`` (degraded) when Anthropic is unconfigured.

    Reuses the shared ``anthropic_api_key`` (the same key content + context gate on).
    A missing key OR an absent ``[ai]`` SDK returns ``None`` so the surface degrades
    rather than raising; the secret is NEVER logged, only the reason.
    """
    key = settings.anthropic_api_key
    if not key:
        logger.info("gmb_degraded", reason=DEGRADE_KEYLESS)
        return None
    try:
        return AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
            model_heavy=settings.anthropic_model_heavy,
        )
    except ProviderNotConfiguredError:
        logger.info("gmb_degraded", reason="anthropic_sdk_absent")
        return None


class _NullGmbCache:
    """A no-op ``CostCache`` (GBP prompts are unique; nothing is cached)."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def build_gmb_gate() -> CostGate:
    """The real cost gate over the Postgres cost store (no cache)."""
    return CostGate(PostgresCostStore(), _NullGmbCache())


def _compose_prompt(topic: str, *, post_type: str, client_name: str, facts: dict[str, str]) -> str:
    """Frame the operator's topic into a GBP-policy-aware drafting prompt."""
    lines = [
        f"Write ONE Google Business Profile post for {client_name or 'the business'}.",
        f"Topic: {topic.strip()}.",
        f"Post type: {post_type}.",
        "Follow Google Business Profile content policies: no prohibited, offensive, adult, "
        "dangerous, or misleading content; be specific, helpful, and honest.",
        "Keep it concise and scannable (ideally 100-300 characters, never over 1500).",
        "Write plain, direct, client-friendly local copy with one clear call to action.",
        "Do NOT use em dashes or en dashes. Do NOT put a phone number or a URL in the text "
        "(the call-to-action button carries the link).",
        "Return ONLY the post text, no preamble.",
    ]
    if facts:
        lines.append("Grounded facts you may use (invent nothing else): " + "; ".join(
            f"{k}: {v}" for k, v in list(facts.items())[:5]
        ))
    return "\n".join(lines)


def _truncate(text: str, max_chars: int) -> str:
    """Hard-cap ``text`` to ``max_chars`` on a word boundary (GBP's character limit)."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return (cut or text[:max_chars]).rstrip()


def run_gmb_generation(
    topic: str,
    *,
    post_type: str,
    cta_type: str,
    cta_url: str,
    title: str,
    client_id: str | None,
    client_name: str,
    facts: dict[str, str] | None = None,
    summarizer: Summarizer | None,
    gate: CostGate,
    settings: Settings,
) -> GmbGenerationResult:
    """Generate ONE GBP post: gate -> draft -> dash-strip -> cap -> policy-check. Pure;
    degrades (never crashes) on a keyless deploy or a money-dial block.

    The three-step gate contract is reused verbatim (evaluate -> call -> commit); on any
    non-``call`` outcome NO provider call happens and the gate is not bypassed.
    """
    # Keyless: degrade WITHOUT consulting the gate or a provider.
    if summarizer is None:
        return GmbGenerationResult(
            status="degraded",
            body="",
            policy=check_gbp_policy("", cta_type=cta_type, cta_url=cta_url, post_type=post_type, title=title),
            reason=DEGRADE_KEYLESS,
        )

    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=client_id,
        provider=_PROVIDER,
        estimated_cost=GMB_COST_ESTIMATE,
        job_type=_JOB_TYPE,
        client_name=client_name,
        cache_key=None,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # dial off / by-hand, client cap, or daily spend-stop: NO provider call.
        return GmbGenerationResult(
            status="degraded",
            body="",
            policy=check_gbp_policy("", cta_type=cta_type, cta_url=cta_url, post_type=post_type, title=title),
            reason=f"cost_gate:{decision.outcome}",
        )

    prompt = _compose_prompt(topic, post_type=post_type, client_name=client_name, facts=facts or {})
    llm = summarizer.summarize(prompt, model=settings.anthropic_model_summary, max_tokens=GMB_MAX_TOKENS)
    # Commit the ACTUAL spend from the call's real token usage x the model's unit price.
    cost = pricing.anthropic_cost(
        settings,
        model=settings.anthropic_model_summary,
        input_tokens=llm.input_tokens,
        output_tokens=llm.output_tokens,
    )
    gate.commit(ctx, cost)

    # The hard em/en-dash guarantee + Google's character cap, THEN the policy score.
    body = _truncate(strip_dashes(llm.text.strip()), GBP_MAX_CHARS)
    policy = check_gbp_policy(body, cta_type=cta_type, cta_url=cta_url, post_type=post_type, title=title)
    return GmbGenerationResult(status="ok", body=body, policy=policy, cost=round(cost, 6))
