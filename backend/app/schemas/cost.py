"""Cost-control request/response models in the frontend shapes (cost.ts)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.util.timefmt import relative_ago

# The dial/cost-log provider vocabulary. "AuditEngine" is the local audit engine
# itself: a paid COMPREHENSIVE run's spend is derived at runtime from the run's own
# observables (tokens + Serper queries + Places calls), so it has no flat unit price -
# see `provider_pricing` below and `app/services/pricing.audit_cost`.
Provider = Literal[
    "Serper", "DataForSEO", "Anthropic", "PageSpeed", "Places", "Voyage", "Google", "AuditEngine"
]
DialMode = Literal["api", "byhand", "off"]
JobType = Literal["audit", "content", "backlinks"]


class DialFeatureMeta(BaseModel):
    """Static per-feature dial metadata (mode is stored; this is the rest)."""

    key: str
    label: str
    icon: str
    provider: Provider
    note: str
    default_mode: DialMode


# Mirrored from frontend dial_seed. Mode is mutable (persisted in cost_dial);
# everything else is reference data merged in at response time.
DIAL_FEATURES: tuple[DialFeatureMeta, ...] = (
    DialFeatureMeta(key="tech_audit", label="Technical Audit", icon="troubleshoot", provider="DataForSEO", note="Live crawl + rank data", default_mode="api"),
    # P0-2 - the PUBLIC free-audit funnel, on its OWN dial rather than sharing
    # "tech_audit" with the paid audit. Two reasons it must be separate: the funnel
    # is UNAUTHENTICATED (its abuse profile is nothing like an authenticated audit's),
    # and an operator needs to be able to switch the lead magnet off during an abuse
    # episode WITHOUT also disabling the paid product every client is paying for.
    # A condensed free run makes no paid-provider call, so this dial is about
    # AVAILABILITY and blast radius, not spend - but it still routes through the same
    # gate, so the agency-global spend halt reaches it like everything else.
    DialFeatureMeta(key="public_audit", label="Free Audit Funnel", icon="campaign", provider="AuditEngine", note="Public lead magnet — condensed, no paid providers", default_mode="api"),
    DialFeatureMeta(key="cwv", label="Core Web Vitals", icon="speed", provider="PageSpeed", note="Free tier — always on", default_mode="api"),
    DialFeatureMeta(key="content", label="Content Pipeline", icon="article", provider="Anthropic", note="Claude drafting — billed per token", default_mode="api"),
    DialFeatureMeta(key="backlinks", label="Backlink Manager", icon="hub", provider="Serper", note="Paid — review before pull", default_mode="byhand"),
    # 7B-4 — citation/Web2 SUBMISSION (building new listings/posts) is a distinct
    # spend from "backlinks" (which meters MONITORING pulls + Web2 publish calls,
    # both effectively free/near-free). A citation submission run spends real money
    # on CAPTCHA-solves + proxy bandwidth, so it gets its own dial + its own budget
    # visibility rather than hiding inside the backlinks dial's numbers. Defaults to
    # API per the client's explicit 2026-07-23 decision ("no approval gate — a
    # queued campaign submits immediately"); the dial + per-client budget caps +
    # the global manual spend halt still bound the spend, and an operator can turn it
    # back to byhand/off at any time.
    DialFeatureMeta(key="citations", label="Citation Builder", icon="add_location_alt", provider="Serper", note="Auto-submits queued directories (CAPTCHA + proxy spend)", default_mode="api"),
    DialFeatureMeta(key="local_seo", label="Local SEO", icon="storefront", provider="Places", note="GBP + map-pack lookups", default_mode="byhand"),
    DialFeatureMeta(key="keywords", label="Keyword Research", icon="search", provider="Serper", note="Paused this cycle", default_mode="off"),
    # Part 6B — the Client-Context / AI-memory module's two AI spends. Both flow
    # through the SAME gate as every other paid call (P6B-4's Gated* wrappers), so
    # ops can throttle context AI to off/byhand/api on the money-dial and no
    # context spend can bypass the budget caps / the global spend halt.
    DialFeatureMeta(key="context", label="Client Context", icon="psychology", provider="Anthropic", note="Living-summary prose (Claude)", default_mode="api"),
    DialFeatureMeta(key="context_embed", label="Context Embeddings", icon="memory", provider="Voyage", note="Context vectors (Voyage)", default_mode="api"),
    # Part 7 (P7A-3) — the Content module's SERP keyword & intent RESEARCH spend
    # (the top-10 teardown + keyword metrics). It flows through the SAME gate as
    # every other paid call (the GatedResearcher wrapper), so ops can throttle
    # content research to off/byhand/api on the money-dial; a block DEGRADES the
    # brief (partial / low-confidence) rather than crashing. Aggressively cached
    # by (keyword, geo, serp_date), so a cluster/city sprint reuses one pull.
    DialFeatureMeta(key="content_research", label="Content Research", icon="manage_search", provider="Serper", note="SERP + top-10 teardown (Serper)", default_mode="api"),
    # Part 9 (P9-5) - the web Dashboard/Portal IN-PRODUCT AI assist. The dashboard
    # calls OUR backend, which calls Claude through the summarizer seam wrapped in
    # THIS gate (the client never holds a key), so ops throttle it off/byhand/api on
    # the money-dial exactly like context; a block DEGRADES the reply, never crashes.
    DialFeatureMeta(key="ai_assist", label="In-Product AI", icon="assistant", provider="Anthropic", note="Dashboard AI assist (Claude)", default_mode="api"),
    # Part 7 Module 05 — the Policy Radar change-detection WATCHER's analysis spend.
    # When a watched Google policy/algorithm source changes, the watcher distils it
    # into a KB entry + recommendation via a cost-gated Claude Haiku call. It flows
    # through the SAME gate as every other paid call (analyze_change), so ops throttle
    # it off/byhand/api on the money-dial; a block (or no key) DEGRADES the analysis —
    # the change_event still stands, the KB is just not enriched — never a crash. This
    # registration is MANDATORY: an unregistered key is unswitchable-on (dead on
    # arrival) — dial_mode() falls back to "off" and PATCH /cost/dials rejects it.
    DialFeatureMeta(key="policy", label="Policy Radar", icon="policy", provider="Anthropic", note="Change analysis (Claude Haiku)", default_mode="api"),
    # GMB post drafting (Claude). Defaults to byhand: an operator reviews each generated
    # Google Business Profile post before use (Google posting itself is approval-gated /
    # dormant). Same MANDATORY-registration rule as every dial above.
    DialFeatureMeta(key="gmb", label="GMB Posts", icon="storefront", provider="Anthropic", note="GBP post drafting (Claude)", default_mode="byhand"),
    # Part 8 - the tool modules' paid spends. EVERY key a module passes to the gate
    # MUST be registered here: dial_mode() falls back to "off" for an unknown key
    # (cost_store.py) AND the PATCH /cost/dials guard rejects a key not in DIAL_KEYS
    # (routers/cost.py), so an unregistered module is not merely defaulted-off - it is
    # UNSWITCHABLE-ON, i.e. dead on arrival. Two Part-8 modules deliberately reuse the
    # dials that already describe their product concept rather than minting a twin:
    # keyword_research -> "keywords" and local_seo -> "local_seo".
    #
    # rank_tracker is the platform's first STANDING per-client cost (audits/content are
    # on-demand; rank checks recur nightly forever) and the CLIENT pays for it, so it
    # defaults OFF: switching it on is an explicit ops decision, and the module prices
    # the monthly commitment before a lead can subscribe to it.
    DialFeatureMeta(key="rank_tracker", label="Rank Tracker", icon="trending_up", provider="Serper", note="Nightly rank checks — recurring", default_mode="off"),
    DialFeatureMeta(key="on_page", label="On-Page Optimizer", icon="tune", provider="Anthropic", note="Entity-coverage scoring (Claude)", default_mode="off"),
    DialFeatureMeta(key="competitor_intel", label="Competitor Intel", icon="insights", provider="Serper", note="Gap + share-of-voice pulls", default_mode="off"),
    # 7C — live Google Search Console + GA4 reads. Free-tier (mirrors "cwv"): the
    # dial still gates every call for spend-visibility parity with every other
    # module (the e8964de lesson — an unregistered key is unswitchable-on), it just
    # never actually costs anything.
    DialFeatureMeta(key="site_analytics", label="Site Analytics (GSC/GA4)", icon="query_stats", provider="Google", note="Search Console + GA4 — free tier", default_mode="api"),
)

DIAL_KEYS: frozenset[str] = frozenset(f.key for f in DIAL_FEATURES)


class ClientBudgetResponse(BaseModel):
    """A per-client budget in the frontend ``ClientBudget`` shape.

    ``cap``/``spent`` are USD amounts. They are ``float`` (not ``int``) because
    0044 made the columns ``numeric(10,2)``: month-to-date ``spent`` accumulates
    sub-dollar charges, so truncating it to whole dollars would misreport how
    close a client is to its cap. The frontend ``ClientBudget`` types both as
    ``number``, so this is contract-compatible (the lock checks field names).
    """

    id: str
    cn: str
    tier: str
    cap: float
    spent: float
    c: str


class BudgetUpdate(BaseModel):
    cap: float = Field(ge=0)


class DialFeatureResponse(BaseModel):
    """A dial row in the frontend ``DialFeature`` shape."""

    key: str
    label: str
    icon: str
    provider: Provider
    mode: DialMode
    note: str


class DialUpdate(BaseModel):
    mode: DialMode


class CostEntryResponse(BaseModel):
    """A cost-log row in the frontend ``CostEntry`` shape."""

    id: str
    client: str
    type: str
    provider: str
    cost: float
    cached: bool
    time: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CostEntryResponse:
        return cls(
            id=row.get("job_id", ""),
            client=row.get("client_name", ""),
            type=row.get("job_type", ""),
            provider=row.get("provider", ""),
            cost=float(row.get("cost", 0) or 0),
            cached=bool(row.get("cached", False)),
            time=relative_ago(row.get("created_at"), empty="just now"),
        )


class SpendStopResponse(BaseModel):
    """The org-wide manual API-spend HALT state + today's/this-month's live paid spend.

    ``halted`` is the single agency-global kill-switch (owner/admin). ``today_spent``
    is day-to-date paid spend, kept purely informational (there is no per-day dollar
    THRESHOLD any more - the manual halt replaced it). ``month_spent`` is REAL
    calendar-month-to-date paid spend (summed from ``cost_log.created_at``) - unlike
    ``client_budgets.spent`` (an all-time cumulative counter), this actually resets
    each calendar month, so it is what a "Spend this month" UI tile should read."""

    halted: bool
    today_spent: float = Field(serialization_alias="todaySpent")
    month_spent: float = Field(serialization_alias="monthSpent")


class SpendStopUpdate(BaseModel):
    """Toggle the global spend halt on/off (owner/admin only)."""

    halted: bool


def merge_dial(stored_modes: dict[str, str]) -> list[DialFeatureResponse]:
    """Merge the static dial features with any persisted mode overrides."""
    out: list[DialFeatureResponse] = []
    for f in DIAL_FEATURES:
        mode = stored_modes.get(f.key, f.default_mode)
        out.append(
            DialFeatureResponse(
                key=f.key, label=f.label, icon=f.icon, provider=f.provider,
                mode=mode, note=f.note,  # type: ignore[arg-type]
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Provider unit pricing (GET /cost/pricing)
# --------------------------------------------------------------------------- #
# The UI used to render hardcoded unit prices ("$0.30 / search", "$0.75 / task").
# Every one of them was wrong by two to three orders of magnitude against the
# prices the cost gate actually bills at. These models expose the SAME
# ``Settings`` values ``app.services.pricing`` computes real spend from, so an
# operator reads the number the platform charges itself - and it moves when the
# env var moves. No price is ever written in the frontend again.


class ProviderPriceLine(BaseModel):
    """One priced dimension of a provider (a provider may have several).

    ``amount`` is USD. ``basis`` names what one ``amount`` buys, in the provider's
    own billing unit - never rescaled for display, so the figure is checkable
    against the provider's price sheet.
    """

    label: str
    amount: float
    basis: str


class ProviderPricingResponse(BaseModel):
    """Live unit pricing for one provider, with the settings key it came from.

    ``paid`` distinguishes a provider that bills from one that is free-tier: a
    free-tier provider still passes the cost gate (for spend visibility and dial
    parity) but commits $0. ``source`` names the ``Settings`` field(s) behind the
    numbers so any figure on screen is traceable to a configured value.
    """

    provider: str
    paid: bool
    source: str
    lines: list[ProviderPriceLine]


def provider_pricing(settings: Any) -> list[ProviderPricingResponse]:
    """Build the live unit-price table from ``Settings``.

    Ordered to match the dial. Anthropic carries six lines (three model tiers x
    input/output) because that is genuinely how it bills - collapsing it to a
    single "per page" figure is what produced the fabricated number this replaces.
    """
    return [
        ProviderPricingResponse(
            provider="Serper", paid=True, source="price_serper_per_query",
            lines=[
                ProviderPriceLine(
                    label="SERP query", amount=settings.price_serper_per_query,
                    basis="per query",
                )
            ],
        ),
        ProviderPricingResponse(
            provider="DataForSEO", paid=True, source="price_dataforseo_per_call",
            lines=[
                ProviderPriceLine(
                    label="API call", amount=settings.price_dataforseo_per_call,
                    basis="per call",
                )
            ],
        ),
        ProviderPricingResponse(
            provider="Anthropic", paid=True,
            source="price_anthropic_*_per_mtok, price_web_search_per_search",
            lines=[
                ProviderPriceLine(label="Haiku input", amount=settings.price_anthropic_haiku_input_per_mtok, basis="per 1M tokens"),
                ProviderPriceLine(label="Haiku output", amount=settings.price_anthropic_haiku_output_per_mtok, basis="per 1M tokens"),
                ProviderPriceLine(label="Sonnet input", amount=settings.price_anthropic_sonnet_input_per_mtok, basis="per 1M tokens"),
                ProviderPriceLine(label="Sonnet output", amount=settings.price_anthropic_sonnet_output_per_mtok, basis="per 1M tokens"),
                ProviderPriceLine(label="Opus input", amount=settings.price_anthropic_opus_input_per_mtok, basis="per 1M tokens"),
                ProviderPriceLine(label="Opus output", amount=settings.price_anthropic_opus_output_per_mtok, basis="per 1M tokens"),
                ProviderPriceLine(label="Web search", amount=settings.price_web_search_per_search, basis="per search"),
            ],
        ),
        ProviderPricingResponse(
            provider="Places", paid=True, source="price_google_per_call",
            lines=[
                ProviderPriceLine(
                    label="Places / geocode lookup", amount=settings.price_google_per_call,
                    basis="per call",
                )
            ],
        ),
        ProviderPricingResponse(
            provider="Voyage", paid=True, source="price_voyage_per_mtok",
            lines=[
                ProviderPriceLine(
                    label="Embedding", amount=settings.price_voyage_per_mtok,
                    basis="per 1M tokens",
                )
            ],
        ),
        ProviderPricingResponse(
            provider="AuditEngine", paid=True,
            source="derived at runtime — app/services/pricing.audit_cost",
            # Deliberately NO price lines. A comprehensive audit's cost is whatever
            # that particular run actually consumed (its reported token usage, Serper
            # queries and Places calls); there is no per-run constant, and inventing
            # one is exactly the "~$1.50 / run" figure this endpoint replaced. A free
            # run costs 0 because it calls no paid provider.
            lines=[],
        ),
        ProviderPricingResponse(
            provider="ImageGen", paid=True, source="price_image_per_image",
            lines=[
                ProviderPriceLine(
                    label="Generated image", amount=settings.price_image_per_image,
                    basis="per image",
                )
            ],
        ),
        # Free-tier providers. They are gated for spend VISIBILITY, not because
        # they bill; the gate commits $0 for them. Stated explicitly so the UI can
        # say "free tier" as a fact rather than as an unpriced blank.
        ProviderPricingResponse(
            provider="PageSpeed", paid=False, source="free tier (no configured price)",
            lines=[ProviderPriceLine(label="PageSpeed Insights", amount=0.0, basis="free tier")],
        ),
        ProviderPricingResponse(
            provider="Google", paid=False, source="free tier (no configured price)",
            lines=[ProviderPriceLine(label="Search Console + GA4", amount=0.0, basis="free tier")],
        ),
    ]
