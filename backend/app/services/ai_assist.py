"""P9-5: the web in-product AI-assist surface's routing + cost-gated summarizer core.

The dashboard/portal sends a plain-language request to OUR backend; the backend -
never the client - calls Claude through the EXISTING summarizer seam
(``integrations/llm.py``), metered by the EXISTING cost gate under a new
``ai_assist`` money-dial feature. The client never holds an Anthropic key.

This is the web twin of the local skills: a skill run and a dashboard assist both
land on the SAME backend engines behind the SAME guards. The heavy per-module
generation is NOT reinvented here - a real workflow (content drafting, report sync,
policy radar) already lives in that module's own service/endpoint. ``/ai/assist``
only INTERPRETS the request into a bounded, structured summary and POINTS the
operator at the module that owns the real work (the thin "router + summarizer" the
plan calls for).

The core (:func:`run_assist`) is PURE - the summarizer and the gate are injected -
so it unit-tests with the deterministic ``FakeSummarizer`` + a fake ``CostStore``,
exactly like the context module. Degrade, never crash:

* no Anthropic key (``summarizer is None``) -> a keyless stub; the gate is never
  consulted and no provider call happens.
* a cost-gate block (dial off / by-hand, client cap, org daily spend-stop) -> a
  blocked stub; NO provider call happens and the gate is NEVER bypassed.

In both cases the surface returns 200 with ``status='degraded'``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from app.schemas.ai_assist import AiAssistSurface, AssistStatus
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import AnthropicSummarizer, Summarizer

logger = get_logger("app.services.ai_assist")

# The money-dial feature key + provider label these calls gate against (must match
# the ``ai_assist`` DialFeatureMeta in app/schemas/cost.py). ``job_type`` groups the
# cost-log rows, mirroring the context module's ``"context"`` job type.
_FEATURE = "ai_assist"
_PROVIDER = "Anthropic"
_JOB_TYPE = "ai_assist"

# Degrade reasons surfaced on the response (stable, machine-branchable strings).
DEGRADE_KEYLESS = "anthropic_unconfigured"


@dataclass(frozen=True)
class _SurfaceRoute:
    """Static per-surface routing: the engine label, the REAL endpoint that owns the
    heavy workflow (``""`` for the general assistant), and the framing prepended to
    the operator's prompt so the summarizer answers in the right register."""

    workflow: str
    endpoint: str
    framing: str


# Each surface maps to the module that owns the real work. /ai/assist never does the
# heavy generation itself - it interprets + points here.
_ROUTES: dict[str, _SurfaceRoute] = {
    "content": _SurfaceRoute(
        "Content pipeline",
        "/api/v1/content/jobs",
        "You are triaging a content request for an SEO agency operator. Restate it as a "
        "crisp content brief (page type, topic, target) they can submit to the content pipeline.",
    ),
    "report": _SurfaceRoute(
        "Reports module",
        "/api/v1/reports/sync",
        "You are helping an SEO agency operator interpret a reporting request. Summarize "
        "what to pull and which workbook / report type it maps to.",
    ),
    "radar": _SurfaceRoute(
        "Policy radar",
        "/api/v1/policy/changes",
        "You are helping an SEO agency operator interpret an algorithm / policy-radar "
        "question. Summarize the relevant change signal and its practical implication.",
    ),
    "general": _SurfaceRoute(
        "General assistant",
        "",
        "You are an SEO agency operations assistant. Answer the operator's question "
        "concisely and factually, without inventing client data.",
    ),
}

# The closed surface set, derived from the routes so the two never drift.
SURFACES: tuple[str, ...] = tuple(_ROUTES)


@dataclass(frozen=True)
class AssistResult:
    """The verdict of one :func:`run_assist` run (a small, comparable value)."""

    surface: AiAssistSurface
    status: AssistStatus
    routed_to: str
    endpoint: str
    result: str
    reason: str = ""


def build_assist_summarizer(settings: Settings) -> Summarizer | None:
    """The key-gated summarizer, or ``None`` (degraded) when Anthropic is unconfigured.

    Reuses the module's optional ``anthropic_api_key`` (the SAME key the context
    module gates on). A missing key OR an absent ``[ai]`` SDK returns ``None`` so the
    surface degrades rather than raising - it NEVER logs the secret, only the reason.
    """
    key = settings.anthropic_api_key
    if not key:
        logger.info("ai_assist_degraded", reason=DEGRADE_KEYLESS)
        return None
    try:
        return AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
            model_heavy=settings.anthropic_model_heavy,
        )
    except ProviderNotConfiguredError:
        # Key present but the optional SDK is absent: still degrade, never crash.
        logger.info("ai_assist_degraded", reason="anthropic_sdk_absent")
        return None


class _NullAssistCache:
    """A no-op ``CostCache``: assist prompts are unique, so nothing is cached.

    ``GateContext.cache_key`` is always ``None`` here, so the gate never actually
    touches this cache - it exists only to satisfy the ``CostGate`` constructor.
    """

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def build_assist_gate() -> CostGate:
    """The real cost gate over the Postgres cost store (no cache - see ``_NullAssistCache``)."""
    return CostGate(PostgresCostStore(), _NullAssistCache())


def _compose_prompt(route: _SurfaceRoute, prompt: str, context_ref: str | None) -> str:
    """Frame the operator's prompt for the summarizer (surface framing + optional ref)."""
    parts = [route.framing, f"Request: {prompt.strip()}"]
    if context_ref:
        parts.append(f"Context ref: {context_ref}")
    return "\n".join(parts)


def _keyless_message(route: _SurfaceRoute) -> str:
    tail = f" ({route.endpoint})" if route.endpoint else ""
    return (
        "AI assist is degraded: no Anthropic key is configured. Use the "
        f"{route.workflow}{tail} directly until the key is activated."
    )


def _blocked_message(route: _SurfaceRoute, outcome: str) -> str:
    return (
        f"AI assist is paused by the money-dial ({outcome}). Adjust the ai_assist dial "
        f"or budget, or use the {route.workflow} directly."
    )


def _degraded(route: _SurfaceRoute, surface: AiAssistSurface, reason: str, message: str) -> AssistResult:
    return AssistResult(
        surface=surface,
        status="degraded",
        routed_to=route.workflow,
        endpoint=route.endpoint,
        result=message,
        reason=reason,
    )


def run_assist(
    surface: AiAssistSurface,
    prompt: str,
    context_ref: str | None,
    *,
    summarizer: Summarizer | None,
    gate: CostGate,
    settings: Settings,
) -> AssistResult:
    """Route + gate + summarize ONE assist request. Pure; degrades, never crashes.

    ``surface`` is already validated by the pydantic ``Literal`` at the edge. The
    three-step gate contract is reused verbatim (evaluate -> call -> commit): on any
    non-``call`` outcome NO provider call happens and the gate is not bypassed.
    """
    route = _ROUTES[surface]

    # Keyless: degrade WITHOUT consulting the gate or a provider.
    if summarizer is None:
        return _degraded(route, surface, DEGRADE_KEYLESS, _keyless_message(route))

    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,  # org-level staff assist; still under the org daily spend-stop
        provider=_PROVIDER,
        estimated_cost=settings.ai_assist_cost_estimate,
        job_type=_JOB_TYPE,
        cache_key=None,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # dial off / by-hand, client cap, or daily spend-stop: NO provider call.
        return _degraded(route, surface, f"cost_gate:{decision.outcome}", _blocked_message(route, decision.outcome))

    composed = _compose_prompt(route, prompt, context_ref)
    llm = summarizer.summarize(
        composed, model=settings.anthropic_model_summary, max_tokens=settings.ai_assist_max_tokens
    )
    gate.commit(ctx, ctx.estimated_cost)
    return AssistResult(
        surface=surface,
        status="ok",
        routed_to=route.workflow,
        endpoint=route.endpoint,
        result=llm.text,
    )
