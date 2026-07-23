"""Single source of truth for provider UNIT prices + RUNTIME cost computation.

Every cost that the cost gate LOGS/commits is computed here at RUNTIME from the
ACTUAL usage a caller incurred (tokens generated, queries issued, images made,
calls placed) multiplied by a real provider UNIT price. There is NO flat
per-CALL dollar constant used as the logged cost -- the flat ``*_cost_estimate``
settings survive ONLY as the upfront ``GateContext.estimated_cost`` a pre-check
needs before usage is known; the COMMITTED value always comes through one of
these functions.

Unit prices live in ``Settings`` (env-overridable, 12-factor). This module is
pure: given usage numbers + a ``Settings`` it returns a ``float`` USD cost, so
each computation is unit-testable against a ``Settings`` built from explicit
overrides. It knows nothing about the gate -- the gate stays provider-agnostic.
"""

from __future__ import annotations

from typing import Any, Literal

from app.config import Settings

# Anthropic price tiers. A model string maps to a tier by substring so a dated or
# aliased id (e.g. ``claude-haiku-4-5-20251001``) still resolves to a real price.
AnthropicTier = Literal["haiku", "sonnet", "opus"]

_MTOK = 1_000_000.0  # tokens per "per-million-tokens" price unit
_CHARS_PER_TOKEN = 4  # deterministic ~tokens estimate (matches FakeSummarizer)


def anthropic_tier(model: str) -> AnthropicTier:
    """Map an Anthropic model id to its price tier.

    Substring match so dated/aliased ids resolve; an UNRECOGNISED model falls to
    ``opus`` (the top tier) so a mystery model is never mispriced cheap -- the
    logged spend errs high, never silently free.
    """
    m = model.lower()
    if "haiku" in m:
        return "haiku"
    if "sonnet" in m:
        return "sonnet"
    return "opus"


def anthropic_prices(settings: Settings, tier: AnthropicTier) -> tuple[float, float]:
    """The ``(input, output)`` USD price per 1M tokens for a tier."""
    if tier == "haiku":
        return (
            settings.price_anthropic_haiku_input_per_mtok,
            settings.price_anthropic_haiku_output_per_mtok,
        )
    if tier == "sonnet":
        return (
            settings.price_anthropic_sonnet_input_per_mtok,
            settings.price_anthropic_sonnet_output_per_mtok,
        )
    return (
        settings.price_anthropic_opus_input_per_mtok,
        settings.price_anthropic_opus_output_per_mtok,
    )


def anthropic_cost(
    settings: Settings, *, model: str, input_tokens: int, output_tokens: int
) -> float:
    """ACTUAL Anthropic spend for one call from its reported token usage.

    ``(input_tokens x input_price + output_tokens x output_price) / 1e6``, priced
    at the model's tier. ``LLMResult.input_tokens`` / ``output_tokens`` (see
    ``integrations/llm.py``) feed this directly.
    """
    in_price, out_price = anthropic_prices(settings, anthropic_tier(model))
    cost = (max(input_tokens, 0) * in_price + max(output_tokens, 0) * out_price) / _MTOK
    return round(cost, 6)


def serper_cost(settings: Settings, *, queries: int = 1) -> float:
    """ACTUAL Serper spend = number of queries issued x the per-query price."""
    return round(max(queries, 0) * settings.price_serper_per_query, 6)


def google_api_cost(settings: Settings, *, calls: int = 1) -> float:
    """ACTUAL Google paid-API spend (Places/geocode) = calls x per-call price."""
    return round(max(calls, 0) * settings.price_google_per_call, 6)


def image_cost(settings: Settings, *, images: int = 1) -> float:
    """ACTUAL image-generation spend = images generated x per-image price."""
    return round(max(images, 0) * settings.price_image_per_image, 6)


def dataforseo_cost(settings: Settings, *, calls: int = 1) -> float:
    """ACTUAL DataForSEO spend = API calls placed x per-call price."""
    return round(max(calls, 0) * settings.price_dataforseo_per_call, 6)


def approx_tokens(*texts: str) -> int:
    """A deterministic ~4-chars/token estimate over one or more texts.

    Used where a provider seam does not surface a real token count (the Voyage
    embedder), so the derived cost still scales with the ACTUAL text processed.
    """
    total = sum(len(t) for t in texts)
    return max(1, total // _CHARS_PER_TOKEN)


def voyage_embed_cost(settings: Settings, *, tokens: int) -> float:
    """ACTUAL Voyage embedding spend = tokens embedded x per-1M-token price.

    The ``Embedder`` Protocol returns vectors only (no provider token count), so
    the embed caller derives ``tokens`` from the ACTUAL embedded text via
    ``approx_tokens`` -- a runtime figure scaled by real work, never a flat
    per-call constant.
    """
    return round(max(tokens, 0) * settings.price_voyage_per_mtok / _MTOK, 6)


def _int(value: Any) -> int:
    """Coerce a run.json value to a non-negative int (0 on anything unparseable)."""
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def audit_cost(
    settings: Settings, *, pages_crawled: int, mode: str, usage: dict[str, Any] | None = None
) -> float:
    """RUNTIME-derived cost of one external audit-engine run.

    The engine is a subprocess; it reports observables in ``run.json``, never a $
    figure. This turns those observables into a real cost -- NEVER the flat
    ``audit_paid_cost_estimate`` (which is only the upfront pre-check number).

    * ``mode == "free"`` -> ``0.0`` (a free run fires no paid provider).
    * PRECISE path -- when the engine writes a ``usage`` block with real token
      counts, the Anthropic spend is those tokens x the model's unit price (priced
      at ``usage["model"]``, else the configured summary model), plus
      ``serper_queries`` x the per-query price and ``places_calls`` x the Google
      per-call price. This is genuine usage x unit price.
    * DERIVED fallback -- an older engine build reports only ``pages_crawled`` +
      ``mode``, so the cost is ``pages_crawled x per-page unit`` (crawl/Serper/PSI
      work scales per page) + the ``agent_calls`` fan-out priced at the haiku unit
      from per-agent token estimates. Still scaled by real run outputs.
    """
    if mode == "free":
        return 0.0

    usage = usage or {}
    input_tokens = _int(usage.get("input_tokens"))
    output_tokens = _int(usage.get("output_tokens"))

    if input_tokens or output_tokens:
        model = usage.get("model") or settings.anthropic_model_summary
        cost = anthropic_cost(
            settings, model=str(model), input_tokens=input_tokens, output_tokens=output_tokens
        )
        cost += serper_cost(settings, queries=_int(usage.get("serper_queries")))
        cost += google_api_cost(settings, calls=_int(usage.get("places_calls")))
        return round(cost, 6)

    # Derived fallback: no engine-reported token usage.
    per_agent = anthropic_cost(
        settings,
        model=settings.anthropic_model_summary,
        input_tokens=settings.audit_agent_tokens_in,
        output_tokens=settings.audit_agent_tokens_out,
    )
    cost = max(pages_crawled, 0) * settings.audit_cost_per_page
    cost += max(settings.audit_agent_calls, 0) * per_agent
    return round(cost, 6)
