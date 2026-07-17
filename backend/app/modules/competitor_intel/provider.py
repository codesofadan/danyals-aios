"""Competitor-intel provider seam (Part 8 Phase 2C): the two doors this module buys
from, and the pricing both the cost gate and the degrade path read.

The module deliberately spans BOTH house seams, because its two questions are
genuinely different:

* **Auto-discovery** asks "who else shows up on my client's terms?" - that is a live
  SERP read, one keyword at a time, which is exactly what the HOUSE SERPER seam
  (``integrations/content_research.SerpResearcher``) already does. It is reused as-is
  rather than re-wrapped: the on-page module builds ``SerperResearcher`` from the same
  key with the same degrade, and a second Serper client here would be a second thing
  to keep in step.
* **The gap analysis** asks "what does this rival rank for, in total?" - a
  DOMAIN-indexed question no ``/search`` call can answer, so it goes through the
  SHARED ``KeywordDataProvider`` seam (``integrations/keyword_data``), which is the
  platform's documented DataForSEO exception. That seam was EXTENDED with
  ``ranked_keywords`` for this module; it was not forked.

Both are key-gated and BOTH degrade to their deterministic fake rather than to
``None`` or an exception: a keyless deploy still renders the whole module with stable,
reproducible data, and ``live`` reports False so the degrade is legible to ops instead
of quietly looking like real competitive intelligence.

``estimated_cost`` is what the cost gate pre-checks. Discovery prices the WHOLE run
(``n_keywords x per-SERP``) in one context, because that is what the client is actually
about to be billed - gating each SERP separately would let a 20-keyword sweep walk
past a cap that a single 20-SERP charge would have been refused for.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.logging_setup import get_logger
from integrations.content_research import (
    FakeSerpResearcher,
    SerperResearcher,
    SerpResearcher,
)
from integrations.keyword_data import (
    KeywordDataProvider,
    keyword_data_provider_from_settings,
)

logger = get_logger("modules.competitor_intel.provider")


@dataclass(frozen=True)
class ProviderPricing:
    """What one paid call costs + whether the vendor behind it is LIVE.

    ``live`` False means the fake is answering: the numbers are deterministic and
    plausible but they are NOT competitive intelligence, and every cost logged against
    them is an honest $0.
    """

    provider: str
    cost: float
    live: bool


def serp_source_from_settings(settings: Settings) -> tuple[SerpResearcher, bool]:
    """The SERP researcher auto-discovery mines, and whether it is LIVE.

    Reuses the house Serper seam (the on-page module's key-gate pattern). Degrades to
    the deterministic fake - never ``None`` - so discovery is unit-testable and a
    keyless deploy proposes stable candidates instead of erroring.
    """
    key = settings.serper_api_key
    if key and key.get_secret_value():
        return SerperResearcher(api_key=key.get_secret_value()), True
    logger.info("competitor_serp_source_degraded", reason="missing_serper_key")
    return FakeSerpResearcher(), False


def keyword_source_from_settings(settings: Settings) -> tuple[KeywordDataProvider, bool]:
    """The ranked-keyword provider the gap analysis pulls, and whether it is LIVE.

    Delegates the key-gate + degrade to the SHARED seam's own factory rather than
    re-deciding it here - the seam already returns the fake when the DataForSEO
    credential pair is absent, and duplicating that rule is how the two drift.
    """
    provider = keyword_data_provider_from_settings(settings)
    live = bool(settings.dataforseo_login and settings.dataforseo_password)
    return provider, live


def discovery_pricing(settings: Settings, *, keywords: int) -> ProviderPricing:
    """Price ONE discovery run: ``keywords x the per-SERP estimate``.

    The whole run is priced as one call (see the module docstring). A degraded run
    prices at $0 - it makes no billable call, and quoting a real number for simulated
    data is how a client ends up disputing an invoice.
    """
    _source, live = serp_source_from_settings(settings)
    per_serp = float(settings.competitor_intel_serp_cost_estimate)
    cost = round(per_serp * max(keywords, 0), 6) if live else 0.0
    return ProviderPricing(provider="serper" if live else "fake", cost=cost, live=live)


def analysis_pricing(settings: Settings) -> ProviderPricing:
    """Price ONE gap analysis (a single ``ranked_keywords`` pull)."""
    _provider, live = keyword_source_from_settings(settings)
    cost = float(settings.competitor_intel_cost_estimate) if live else 0.0
    return ProviderPricing(provider="dataforseo" if live else "fake", cost=cost, live=live)
