"""Citation-builder module request/response models (7B-4).

No frontend TS type exists YET for ``business_profiles``/``directories`` (the
existing ``Citation`` shape in ``frontend/lib/offpage.ts`` stays untouched - this
module only ADDS the campaign-dispatch + catalog-browse surface a new UI will read;
until that UI lands these are server-authoritative, covered by shape/enum unit tests
rather than a TS contract lock, per the module README's own rule for that case).

Every enum here is verbatim from ``db/migrations/0045_citation_web2_automation.sql``.
"""

from __future__ import annotations

from datetime import datetime
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
    # Richer identity beyond NAP (0060) - what a real directory form also asks for.
    description: str = ""
    email: str = ""
    logo_url: str = Field(default="", serialization_alias="logoUrl")
    facebook_url: str = Field(default="", serialization_alias="facebookUrl")
    instagram_url: str = Field(default="", serialization_alias="instagramUrl")
    linkedin_url: str = Field(default="", serialization_alias="linkedinUrl")
    year_founded: int | None = Field(default=None, serialization_alias="yearFounded")
    payment_types: list[str] = Field(default_factory=list, serialization_alias="paymentTypes")
    tagline: str = ""
    service_area: str = Field(default="", serialization_alias="serviceArea")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> BusinessProfileResponse:
        market = row.get("market")
        hours = row.get("hours")
        year = row.get("year_founded")
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
            description=row.get("description") or "",
            email=row.get("email") or "",
            logo_url=row.get("logo_url") or "",
            facebook_url=row.get("facebook_url") or "",
            instagram_url=row.get("instagram_url") or "",
            linkedin_url=row.get("linkedin_url") or "",
            year_founded=int(year) if year is not None else None,
            payment_types=list(row.get("payment_types") or []),
            tagline=row.get("tagline") or "",
            service_area=row.get("service_area") or "",
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
    # Richer identity beyond NAP (0060). The python field name IS the DB column name,
    # so model_dump(by_alias=False) feeds the repo's dynamic INSERT/UPDATE directly.
    description: str = ""
    email: str = ""
    logo_url: str = Field(default="", alias="logoUrl")
    facebook_url: str = Field(default="", alias="facebookUrl")
    instagram_url: str = Field(default="", alias="instagramUrl")
    linkedin_url: str = Field(default="", alias="linkedinUrl")
    year_founded: int | None = Field(default=None, alias="yearFounded")
    payment_types: list[str] = Field(default_factory=list, alias="paymentTypes")
    tagline: str = ""
    service_area: str = Field(default="", alias="serviceArea")


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
    # Audit-first "build only these" subset: after an audit surfaces the MISSING
    # directories, the operator ticks the ones to build and sends their catalog ids
    # here. When present, the campaign restricts to exactly these (still skipping any
    # already in flight); when omitted, it falls back to the full strategy selection.
    directory_ids: list[str] | None = Field(default=None, alias="directoryIds")


class CitationCampaignResponse(BaseModel):
    """The outcome of queuing a campaign: how many rows were queued/skipped, and the
    R5 cost estimate for the WHOLE batch. A lead sees this total regardless of dial
    mode; the ``citations`` dial actually defaults to ``api`` (a recorded client
    decision — see app/schemas/cost.py:71's note), and each row still cost-gates
    individually inside the worker."""

    # The campaign's durable id (0120) — what the board polls. Empty only when the
    # identity row could not be written (the batch still queued; degrade, don't refuse).
    campaign_id: str = Field(default="", serialization_alias="campaignId")
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


# --- campaign identity (0120) -----------------------------------------------------


class CampaignSummaryResponse(BaseModel):
    """One row of the campaign list: enough to find the current campaign and read
    its headline without fetching the rollup."""

    id: str
    client: str
    created_at: str = Field(serialization_alias="createdAt")
    requested: int
    queued: int
    live_count: int = Field(serialization_alias="liveCount")
    estimated_cost: float = Field(serialization_alias="estimatedCost")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CampaignSummaryResponse:
        created = row.get("created_at")
        return cls(
            id=str(row["id"]),
            client=str(row.get("client_name") or ""),
            created_at=created.isoformat() if isinstance(created, datetime) else str(created or ""),
            requested=int(row.get("requested") or 0),
            queued=int(row.get("queued") or 0),
            live_count=int(row.get("live_count") or 0),
            estimated_cost=float(row.get("estimated_cost") or 0.0),
        )


class CampaignRowResponse(BaseModel):
    """One directory's row on the campaign board."""

    id: str
    directory: str
    submit_status: str = Field(serialization_alias="submitStatus")
    blocked_reason: str = Field(default="", serialization_alias="blockedReason")
    live_url: str = Field(default="", serialization_alias="liveUrl")
    detail: str = ""


class CampaignRollupResponse(BaseModel):
    """The campaign board: identity + per-status/per-reason rollups + every row.

    Computed LIVE from the citations table (the rows are the truth; the campaign row
    is identity + the persisted skip ledger). ``stuck`` counts in-flight rows whose
    ``updated_at`` sat unmoved past the staleness threshold — the "no worker is
    consuming this" signal that turned 2026-09-01 into an evening of guessing."""

    id: str
    client: str
    created_at: str = Field(serialization_alias="createdAt")
    requested: int
    queued: int
    estimated_cost: float = Field(serialization_alias="estimatedCost")
    by_status: dict[str, int] = Field(serialization_alias="byStatus")
    by_blocked_reason: dict[str, int] = Field(serialization_alias="byBlockedReason")
    stuck: int
    live_urls: list[CitationLiveUrl] = Field(serialization_alias="liveUrls")
    skipped: list[CitationSkip] = Field(default_factory=list)
    rows: list[CampaignRowResponse]


# --- gap analysis ----------------------------------------------------------------


class CitationLiveUrl(BaseModel):
    """One LIVE listing: the directory and the public URL of the listing itself.

    `url` is `citations.live_url` and nothing else. It is never `proof_url` (a
    screenshot key) and never appears for a row that is merely `submitted` - only a row
    the liveness probe has fetched and found the business on can reach this list."""

    directory: str
    url: str
    status: str


class CitationSkip(BaseModel):
    """One catalog directory NOT built for this client, and why.

    Required output, not a nicety: without it a shorter-than-promised list looks
    identical to a system that quietly failed. A client comparing "100 promised" against
    "45 delivered" reads the other 55 here, by name."""

    directory: str
    reason: str
    detail: str = ""
    # The exact terms clause, when the reason is `prohibited_by_terms`. "We did not
    # submit to Yelp, and here is the sentence that says we must not" is a far better
    # answer than a silently shorter list.
    clause: str = ""


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
    # In-flight rows dedupe from `missing` but are NOT covered - nothing was delivered
    # yet. Stale ones are listed in `stuck` by directory name: the "no worker is
    # consuming this" signal (2026-09-01: 45 queued rows once read as covered/built).
    in_flight_count: int = Field(default=0, serialization_alias="inFlightCount")
    stuck: list[dict[str, str]] = Field(default_factory=list)
    missing_count: int = Field(serialization_alias="missingCount")
    missing: list[DirectoryResponse]
    live_urls: list[CitationLiveUrl] = Field(serialization_alias="liveUrls")
    skipped: list[CitationSkip] = Field(default_factory=list)
    by_submit_status: dict[str, int] = Field(serialization_alias="bySubmitStatus")
    by_nap_status: dict[str, int] = Field(serialization_alias="byNapStatus")


# --- audit plan (generic -> country -> niche) ------------------------------------


class AuditPlanItem(BaseModel):
    """One directory in the audit plan: which directory, its market/tier/url, and
    whether the client already has it BUILT (a covering citation exists) or it is a
    MISSING build target. ``status`` mirrors the gap-analysis covering rule."""

    directory_name: str = Field(serialization_alias="directoryName")
    market: BusinessMarket
    tier: DirectoryTier
    url: str
    # `in_flight` = an attempt is pending (deduped, not built). `stuck` = that attempt
    # has sat unmoved past the staleness threshold. Neither may render as "built".
    status: Literal["built", "missing", "in_flight", "stuck"]

    @classmethod
    def from_directory(
        cls, row: dict[str, Any], *, status: Literal["built", "missing", "in_flight", "stuck"]
    ) -> AuditPlanItem:
        market, tier = row.get("market"), row.get("tier")
        return cls(
            directory_name=str(row.get("name") or ""),
            market=market if market in _MARKETS else "US",
            tier=tier if tier in _TIERS else "bot_fillable",
            url=str(row.get("url") or ""),
            status=status,
        )


class AuditPlanResponse(BaseModel):
    """The geo/niche/generic citation audit, PRIORITIZED Generic -> Country -> Niche.

    * ``generic`` - the GLOBAL core/aggregators/APIs every market builds first.
    * ``country`` - the client's own-market (US/UK/CA/AU) general directories.
    * ``niche``   - vertical-specific directories that serve the client's industry.

    Each bucket is in build order and each item carries a built|missing status derived
    from the existing citation records (all ``missing`` when none exist yet)."""

    client: str
    resolved_vertical: str | None = Field(default=None, serialization_alias="resolvedVertical")
    market: BusinessMarket
    generic: list[AuditPlanItem]
    country: list[AuditPlanItem]
    niche: list[AuditPlanItem]


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
    """The citation-engine status board: the whitelist headline first, then each real
    engine CONNECTED vs MISSING with reasons. "3/5 connected" once coexisted with zero
    machine-submittable directories because the binding constraint was not on the
    board at all."""

    machine_submittable_directories: int = Field(
        default=0, serialization_alias="machineSubmittableDirectories"
    )
    whitelist_note: str = Field(default="", serialization_alias="whitelistNote")
    connected_count: int = Field(serialization_alias="connectedCount")
    total_count: int = Field(serialization_alias="totalCount")
    engines: list[EngineStatusResponse]


# --- the human work queue (0110) ---------------------------------------------------


class QueueFieldValue(BaseModel):
    """One pre-computed field the operator pastes — or the extension types — into the
    directory's form.

    Pre-computing every value server-side is the entire point of the queue: the two
    levers on cost per live citation are the aggregator price and MINUTES PER ITEM, and
    the minutes are spent hunting for values, not typing them.

    `selector` is where that value goes on the live form, taken from the directory's
    ACTIVE spec. It was missing, and the omission made the extension inert: the service
    worker had nothing to send, so it shipped `selector: ""`, `document.querySelector("")`
    matched nothing, and every field came back `selector_not_found`. The read-back logic
    that catches a React revert was unreachable because nothing was ever filled.

    EMPTY IS THE HONEST DEFAULT and it is common: a directory with no earned spec has no
    selectors, and the panel then falls back to copy-buttons for a human to paste. A
    fabricated selector would be worse than none - it would type a client's phone number
    into whatever field happened to match."""

    key: str
    label: str
    value: str
    selector: str = ""


class QueueItemResponse(BaseModel):
    """One claimed queue item: what to do, where to do it, and with what values."""

    citation_id: str = Field(serialization_alias="citationId")
    client: str
    directory: str
    directory_url: str = Field(serialization_alias="directoryUrl")
    # The verified deep link to the add-listing form. Empty when the catalogue has never
    # had one probed - the operator then starts from the directory's home page, and the
    # UI says so rather than presenting an empty link as if it were a destination.
    add_url: str = Field(serialization_alias="addUrl")
    fields: list[QueueFieldValue]
    # Why this is a human's job rather than the bot's. Shown to the operator because
    # knowing the obstacle before opening the tab is worth ~a minute an item.
    queued_because: str = Field(serialization_alias="queuedBecause")
    claim_expires_at: str | None = Field(default=None, serialization_alias="claimExpiresAt")
    human_attempts: int = Field(serialization_alias="humanAttempts")
    worked_seconds: int = Field(serialization_alias="workedSeconds")
    # Set only when the directory's terms forbid automated submission. The queue should
    # never contain one of these, so if it is ever non-empty the UI must refuse to help.
    prohibited_warning: str = Field(default="", serialization_alias="prohibitedWarning")


class QueueBoardResponse(BaseModel):
    """The queue at a glance, plus the number the cost model actually rests on."""

    waiting: int
    in_progress: int = Field(serialization_alias="inProgress")
    # MEDIAN seconds per finished item. `None` until something has been finished - an
    # unmeasured number must read as unmeasured, never as zero, because zero would make
    # the loaded-cost model look free.
    median_seconds: int | None = Field(default=None, serialization_alias="medianSeconds")
    mine: list[QueueItemResponse] = Field(default_factory=list)


class QueueClaimRequest(BaseModel):
    """Optionally narrow the claim to one client (an operator working one account)."""

    client_id: str | None = Field(default=None, alias="clientId")
    model_config = ConfigDict(populate_by_name=True)


class QueueHeartbeatRequest(BaseModel):
    """Extend the lease and bank the seconds worked since the last heartbeat."""

    worked_seconds: int = Field(default=0, ge=0, le=3600, alias="workedSeconds")
    model_config = ConfigDict(populate_by_name=True)


class QueueCompleteRequest(BaseModel):
    """Close an item WITH the public URL of the listing that was created.

    `live_url` is required and is checked before it is stored. An operator cannot mark
    an item done by asserting it - the same liveness probe the re-check uses has to
    fetch that URL and find the business on it first."""

    live_url: str = Field(min_length=1, alias="liveUrl")
    worked_seconds: int = Field(default=0, ge=0, le=86400, alias="workedSeconds")
    note: str = ""
    model_config = ConfigDict(populate_by_name=True)


class QueueBlockedRequest(BaseModel):
    """Close an item as NOT done, with a reason. A first-class outcome, not a failure:
    a queue whose only exit is success trains people to fake success."""

    reason: Literal[
        "captcha_wall",
        "account_required",
        "paid_only",
        "form_changed",
        "duplicate_listing",
        "directory_dead",
        "phone_verification",
        "postcard_verification",
        "other",
    ]
    detail: str = ""
    worked_seconds: int = Field(default=0, ge=0, le=86400, alias="workedSeconds")
    model_config = ConfigDict(populate_by_name=True)


class QueueCompleteResponse(BaseModel):
    """The outcome of a completion attempt, including a REFUSAL.

    A refusal is a normal, expected response and not an error: the operator submitted a
    URL, we fetched it, and the business was not on the page. Telling them that
    immediately - while they still have the tab open - is worth far more than accepting
    it and discovering the truth at the next re-check."""

    accepted: bool
    submit_status: str = Field(serialization_alias="submitStatus")
    live_url: str = Field(serialization_alias="liveUrl")
    # Present when accepted is false: what we fetched and why it did not convince us.
    reason: str = ""
    matched_fields: list[str] = Field(default_factory=list, serialization_alias="matchedFields")


# --- the earned spec whitelist (0111) ----------------------------------------------


class SpecFieldRequest(BaseModel):
    """One form field: where it is, and which canonical value goes in it."""

    selector: str = Field(min_length=1)
    value_key: str = Field(min_length=1, alias="valueKey")
    model_config = ConfigDict(populate_by_name=True)


class SpecCreateRequest(BaseModel):
    """A NEW spec revision. Always created INACTIVE - it has earned nothing yet.

    There is no update endpoint by design: `spec` is immutable once written, so a
    revision is a new row. That is what makes a verification meaningful - it signs the
    selectors it actually checked and cannot be carried onto different ones."""

    directory_id: str = Field(min_length=1, alias="directoryId")
    url: str = Field(min_length=1)
    fields: list[SpecFieldRequest]
    submit_selector: str = Field(min_length=1, alias="submitSelector")
    success_indicator: str = Field(default="", alias="successIndicator")
    model_config = ConfigDict(populate_by_name=True)


class SpecVerifyRequest(BaseModel):
    """The dated human live-DOM check. `selectors` is what the person actually saw."""

    selectors: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class SpecFirstLiveRequest(BaseModel):
    """The first submission using this exact spec that produced a public listing URL."""

    live_url: str = Field(min_length=1, alias="liveUrl")
    model_config = ConfigDict(populate_by_name=True)


class SpecDeactivateRequest(BaseModel):
    reason: Literal[
        "drift_detected", "stale_unused", "submission_failed",
        "operator_disabled", "terms_changed",
    ]


class DirectorySpecResponse(BaseModel):
    """One spec and exactly how much it has earned."""

    id: str
    directory_id: str = Field(serialization_alias="directoryId")
    directory_name: str = Field(serialization_alias="directoryName")
    url: str
    field_count: int = Field(serialization_alias="fieldCount")
    active: bool
    # The two halves of the contract, reported separately so a half-earned spec reads as
    # half-earned rather than simply "not active".
    verified: bool
    verified_at: str | None = Field(default=None, serialization_alias="verifiedAt")
    has_first_live_url: bool = Field(serialization_alias="hasFirstLiveUrl")
    first_live_url: str = Field(default="", serialization_alias="firstLiveUrl")
    success_count: int = Field(serialization_alias="successCount")
    failure_count: int = Field(serialization_alias="failureCount")
    drifted: bool
    drift_selector: str = Field(default="", serialization_alias="driftSelector")
    deactivated_reason: str = Field(default="", serialization_alias="deactivatedReason")
    # What still has to happen before this spec may run. Empty when it is active.
    blocking: list[str] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DirectorySpecResponse:
        spec = row.get("spec") or {}
        verified = row.get("verified_at") is not None
        has_live = bool(str(row.get("first_live_url") or ""))
        drifted = row.get("drift_detected_at") is not None
        blocking: list[str] = []
        if not row.get("active"):
            if not verified:
                blocking.append("needs a dated human DOM verification")
            if not has_live:
                blocking.append("needs one submission that produced a public listing URL")
            if drifted:
                blocking.append(
                    f"drifted: selector {row.get('drift_selector') or 'unknown'} is gone - "
                    "record a NEW revision, this one cannot be repaired in place"
                )
        # Tolerate a datetime OR an already-serialised string. psycopg hands back a
        # datetime, but the same row can arrive from a JSON round-trip, and a serializer
        # that 500s on the shape of its own input is a bad trade for one line.
        va = row.get("verified_at")
        iso = getattr(va, "isoformat", None)
        verified_at = iso() if callable(iso) else (str(va) if va else None)
        return cls(
            id=str(row["id"]),
            directory_id=str(row["directory_id"]),
            directory_name=str(row.get("directory_name") or ""),
            url=str(spec.get("url") or ""),
            field_count=len(spec.get("fields") or []),
            active=bool(row.get("active")),
            verified=verified,
            verified_at=verified_at,
            has_first_live_url=has_live,
            first_live_url=str(row.get("first_live_url") or ""),
            success_count=int(row.get("success_count") or 0),
            failure_count=int(row.get("failure_count") or 0),
            drifted=drifted,
            drift_selector=str(row.get("drift_selector") or ""),
            deactivated_reason=str(row.get("deactivated_reason") or ""),
            blocking=blocking,
        )


class SpecBoardResponse(BaseModel):
    """The whitelist at a glance. `active` is the ONLY honest coverage number for the
    automated route - and it starts at zero, which is the true state, not a regression."""

    active: int
    verified_not_live: int = Field(serialization_alias="verifiedNotLive")
    unverified: int
    drifted: int
    specs: list[DirectorySpecResponse]
