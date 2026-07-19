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

_MARKETS: frozenset[str] = frozenset({"US", "UK", "CA", "AU", "GLOBAL"})
_TIERS: frozenset[str] = frozenset(
    {"aggregator", "api", "bot_fillable", "captcha_assisted", "manual_only"}
)
# The tiers a campaign may actually DISPATCH work to - manual_only never queues (no
# worker will ever claim a manual_only row; see service.automatable_directories).
AUTOMATABLE_TIERS: frozenset[str] = frozenset({"aggregator", "api", "bot_fillable", "captcha_assisted"})


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


class DirectoryResponse(BaseModel):
    """One catalog row (``public.directories``) - reference data, not tenant data."""

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

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DirectoryResponse:
        market, tier, link_rel = row.get("market"), row.get("tier"), row.get("link_rel")
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
        )


class CitationCampaignRequest(BaseModel):
    """POST /citation-builder/campaigns body: queue a submission run.

    ``markets``/``tiers`` narrow which catalog rows to queue (default: every
    automatable row in the business profile's own market + GLOBAL). ``manual_only``
    directories are ALWAYS excluded regardless of ``tiers`` - there is no worker path
    for them; passing it is not an error, it is simply a no-op filter.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1, alias="clientId")
    business_profile_id: str = Field(min_length=1, alias="businessProfileId")
    markets: list[BusinessMarket] | None = None
    tiers: list[DirectoryTier] | None = None


class CitationCampaignResponse(BaseModel):
    """The outcome of queuing a campaign: how many rows were queued/skipped, and the
    R5 cost estimate for the WHOLE batch (a lead reviews this before it runs - the
    ``citations`` dial defaults to ``byhand`` for exactly this reason)."""

    queued: int
    already_queued: int = Field(serialization_alias="alreadyQueued")
    skipped_manual_only: int = Field(serialization_alias="skippedManualOnly")
    estimated_cost: float = Field(serialization_alias="estimatedCost")
    citation_ids: list[str] = Field(serialization_alias="citationIds")
