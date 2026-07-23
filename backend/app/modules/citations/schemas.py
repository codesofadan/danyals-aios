"""Citation-builder module request/response models (7B-4).

No frontend TS type exists YET for ``business_profiles``/``directories`` (the
existing ``Citation`` shape in ``frontend/lib/offpage.ts`` stays untouched - this
module only ADDS the campaign-dispatch + catalog-browse surface a new UI will read;
until that UI lands these are server-authoritative, covered by shape/enum unit tests
rather than a TS contract lock, per the module README's own rule for that case).

Every enum here is verbatim from ``db/migrations/0045_citation_web2_automation.sql``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BusinessMarket = Literal["US", "UK", "CA", "AU", "GLOBAL"]
DirectoryTier = Literal["aggregator", "api", "bot_fillable", "captcha_assisted", "manual_only"]
LinkRel = Literal["dofollow", "nofollow", "mixed", "unknown"]
CitationSubmitStatus = Literal[
    "not_started", "queued", "submitting", "submitted", "verified", "failed", "blocked"
]

AuthorityTier = Literal["core", "tier1", "tier2"]
DirectoryAccess = Literal["open", "apply_gated", "aggregator"]

_MARKETS: frozenset[str] = frozenset({"US", "UK", "CA", "AU", "GLOBAL"})
_TIERS: frozenset[str] = frozenset(
    {"aggregator", "api", "bot_fillable", "captcha_assisted", "manual_only"}
)
_AUTHORITY_TIERS: frozenset[str] = frozenset({"core", "tier1", "tier2"})
_ACCESS: frozenset[str] = frozenset({"open", "apply_gated", "aggregator"})
# The tiers a campaign may actually DISPATCH work to - manual_only never queues (no
# worker will ever claim a manual_only row; see service.automatable_directories).
AUTOMATABLE_TIERS: frozenset[str] = frozenset({"aggregator", "api", "bot_fillable", "captcha_assisted"})

# Reference-plan defaults for a campaign's strategy knobs (all overridable per run):
# ~40-50 clean citations beat 100+ scattergun (consistency > volume), and the sub-DA30
# spam tail adds risk more than rank. NULL-authority rows are UNSCORED, never dropped.
DEFAULT_CAMPAIGN_CAP: int = 45
DEFAULT_MIN_AUTHORITY: int = 30


class BusinessProfileResponse(BaseModel):
    """One canonical NAP location a client's citations submit against."""

    id: str
    client: str
    label: str
    business_name: str = Field(serialization_alias="businessName")
    address_line1: str = Field(serialization_alias="addressLine1")
    address_line2: str = Field(serialization_alias="addressLine2")
    city: str
    region: str
    postal_code: str = Field(serialization_alias="postalCode")
    market: BusinessMarket
    phone: str
    website_url: str = Field(serialization_alias="websiteUrl")
    categories: list[str]
    hours: dict[str, str]
    is_primary: bool = Field(serialization_alias="isPrimary")
    # Once locked, the canonical NAP cannot be edited until explicitly unlocked (0048).
    nap_locked: bool = Field(default=False, serialization_alias="napLocked")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> BusinessProfileResponse:
        market = row.get("market")
        hours = row.get("hours")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            label=row.get("label", ""),
            business_name=row.get("business_name", ""),
            address_line1=row.get("address_line1", ""),
            address_line2=row.get("address_line2", ""),
            city=row.get("city", ""),
            region=row.get("region", ""),
            postal_code=row.get("postal_code", ""),
            market=market if market in _MARKETS else "US",
            phone=row.get("phone", ""),
            website_url=row.get("website_url", ""),
            categories=list(row.get("categories") or []),
            hours=dict(hours) if isinstance(hours, dict) else {},
            is_primary=bool(row.get("is_primary", False)),
            nap_locked=bool(row.get("nap_locked", False)),
        )


class BusinessProfileRequest(BaseModel):
    """POST/PATCH body for a business profile (lead-only)."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1, alias="clientId")
    label: str = "Primary"
    business_name: str = Field(min_length=1, alias="businessName")
    address_line1: str = Field(default="", alias="addressLine1")
    address_line2: str = Field(default="", alias="addressLine2")
    city: str = ""
    region: str = ""
    postal_code: str = Field(default="", alias="postalCode")
    market: BusinessMarket = "US"
    phone: str = ""
    website_url: str = Field(default="", alias="websiteUrl")
    categories: list[str] = Field(default_factory=list)
    hours: dict[str, str] = Field(default_factory=dict)
    is_primary: bool = Field(default=True, alias="isPrimary")
    # Lock/unlock the canonical NAP. A locked profile rejects edits until a request
    # explicitly sets this back to false (see the router's update guard).
    nap_locked: bool = Field(default=False, alias="napLocked")


class DirectoryResponse(BaseModel):
    """One catalog row (``public.directories``) - reference data, not tenant data.

    Carries both the AUTOMATION vocabulary (``tier``/``submitMethod`` - how to submit)
    and the STRATEGY vocabulary (0048: ``authority``/``authorityTier``/``access``/
    ``isMarketplace``/``verticals`` - what to submit and in what order)."""

    id: str
    name: str
    url: str
    market: BusinessMarket
    tier: DirectoryTier
    submit_method: str = Field(serialization_alias="submitMethod")
    link_rel: LinkRel = Field(serialization_alias="linkRel")
    price_note: str = Field(serialization_alias="priceNote")
    automation_note: str = Field(serialization_alias="automationNote")
    active: bool
    # 0048 strategy layer
    authority: int | None = None
    authority_tier: AuthorityTier = Field(default="tier2", serialization_alias="authorityTier")
    access: DirectoryAccess = "open"
    is_marketplace: bool = Field(default=False, serialization_alias="isMarketplace")
    verticals: list[str] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DirectoryResponse:
        market, tier, link_rel = row.get("market"), row.get("tier"), row.get("link_rel")
        atier, access = row.get("authority_tier"), row.get("access")
        raw_da = row.get("authority")
        return cls(
            id=str(row["id"]),
            name=row.get("name", ""),
            url=row.get("url", ""),
            market=market if market in _MARKETS else "US",
            tier=tier if tier in _TIERS else "manual_only",
            submit_method=row.get("submit_method", ""),
            link_rel=link_rel if link_rel in {"dofollow", "nofollow", "mixed", "unknown"} else "unknown",
            price_note=row.get("price_note", ""),
            automation_note=row.get("automation_note", ""),
            active=bool(row.get("active", True)),
            authority=int(raw_da) if raw_da is not None else None,
            authority_tier=atier if atier in _AUTHORITY_TIERS else "tier2",
            access=access if access in _ACCESS else "open",
            is_marketplace=bool(row.get("is_marketplace", False)),
            verticals=list(row.get("verticals") or []),
        )


class CitationCampaignRequest(BaseModel):
    """POST /citation-builder/campaigns body: queue a submission run.

    The reference-plan strategy knobs (all optional - sensible defaults apply):
    * ``markets``/``tiers`` narrow the catalog by market + automation tier (default:
      the profile's own market + GLOBAL, every automatable tier). ``manual_only`` is
      ALWAYS excluded (no worker path).
    * ``vertical`` matches the client's industry - only general directories + this
      vertical's niche directories are queued. Omitted -> resolved from the client's
      ``industry`` server-side; unresolvable -> general directories only (never blast
      a plumber with Healthgrades).
    * ``cap`` bounds the batch (default ~45: consistency beats volume). ``0`` = no cap.
    * ``min_authority`` drops the sub-DA spam tail (default 30); UNSCORED rows are kept.
    * ``include_marketplaces`` toggles lead-gen marketplaces (Angi/Zillow/...) that
      compete for the client's own keywords (default: excluded - opt in deliberately).
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1, alias="clientId")
    # Optional: when omitted, the campaign auto-resolves (or DERIVES from the client's
    # own NAP) a submission profile, so "No business profile yet" never blocks a build.
    business_profile_id: str | None = Field(default=None, alias="businessProfileId")
    markets: list[BusinessMarket] | None = None
    tiers: list[DirectoryTier] | None = None
    vertical: str | None = None
    cap: int | None = Field(default=None, ge=0)
    min_authority: int | None = Field(default=None, ge=0, le=100, alias="minAuthority")
    include_marketplaces: bool = Field(default=False, alias="includeMarketplaces")


class CitationCampaignResponse(BaseModel):
    """The outcome of queuing a campaign: how many rows were queued/skipped, and the
    R5 cost estimate for the WHOLE batch (a lead reviews this before it runs - the
    ``citations`` dial defaults to ``byhand`` for exactly this reason)."""

    queued: int
    already_queued: int = Field(serialization_alias="alreadyQueued")
    skipped_manual_only: int = Field(serialization_alias="skippedManualOnly")
    estimated_cost: float = Field(serialization_alias="estimatedCost")
    citation_ids: list[str] = Field(serialization_alias="citationIds")
    # Strategy transparency: what the selection actually did (never a silent cap).
    resolved_vertical: str | None = Field(default=None, serialization_alias="resolvedVertical")
    excluded_off_vertical: int = Field(default=0, serialization_alias="excludedOffVertical")
    excluded_low_authority: int = Field(default=0, serialization_alias="excludedLowAuthority")
    excluded_marketplace: int = Field(default=0, serialization_alias="excludedMarketplace")
    capped: int = 0


# --- gap analysis ----------------------------------------------------------------


class CitationLiveUrl(BaseModel):
    """One live listing already earned: which directory and its proof/listing URL."""

    directory: str
    url: str
    status: str


class GapAnalysisResponse(BaseModel):
    """The reconciliation of a client's citations vs the automatable catalog: what is
    covered, what is still MISSING (the build target, in build order), the live URLs
    earned, and the honest per-status tallies. Also reports the resolved NAP so the UI
    can stop showing "No business profile yet" once one is derived from the client."""

    client: str
    has_nap: bool = Field(serialization_alias="hasNap")
    nap_source: Literal["submission_profile", "client_profile", "none"] = Field(
        serialization_alias="napSource"
    )
    business_profile_id: str | None = Field(default=None, serialization_alias="businessProfileId")
    resolved_vertical: str | None = Field(default=None, serialization_alias="resolvedVertical")
    existing_count: int = Field(serialization_alias="existingCount")
    covered_count: int = Field(serialization_alias="coveredCount")
    missing_count: int = Field(serialization_alias="missingCount")
    missing: list[DirectoryResponse]
    live_urls: list[CitationLiveUrl] = Field(serialization_alias="liveUrls")
    by_submit_status: dict[str, int] = Field(serialization_alias="bySubmitStatus")
    by_nap_status: dict[str, int] = Field(serialization_alias="byNapStatus")


# --- API status boards (Wave 4) --------------------------------------------------


class Web2PlatformStatusResponse(BaseModel):
    """One Web 2.0 platform's connection state for the status board."""

    platform: str
    connected: bool
    draft_only: bool = Field(serialization_alias="draftOnly")
    configured_count: int = Field(serialization_alias="configuredCount")
    required_fields: list[str] = Field(serialization_alias="requiredFields")
    vault_provider: str = Field(serialization_alias="vaultProvider")
    reason: str
    external_note: str = Field(serialization_alias="externalNote")


class Web2StatusResponse(BaseModel):
    """The Web 2.0 API status board: every platform CONNECTED vs MISSING, with reasons."""

    connected_count: int = Field(serialization_alias="connectedCount")
    live_count: int = Field(serialization_alias="liveCount")
    total_count: int = Field(serialization_alias="totalCount")
    platforms: list[Web2PlatformStatusResponse]


class EngineStatusResponse(BaseModel):
    """One citation submission engine's configuration state for the status board."""

    key: str
    label: str
    connected: bool
    reason: str
    required_config: list[str] = Field(serialization_alias="requiredConfig")
    external_note: str = Field(serialization_alias="externalNote")


class EngineStatusBoardResponse(BaseModel):
    """The citation-engine status board: each engine CONNECTED vs MISSING, with reasons."""

    connected_count: int = Field(serialization_alias="connectedCount")
    total_count: int = Field(serialization_alias="totalCount")
    engines: list[EngineStatusResponse]
