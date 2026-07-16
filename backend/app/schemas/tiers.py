"""Service-tier models mirroring frontend tiers.ts.

Two SEPARATE concepts:
* subscription tier (Starter/Growth/Scale) - billing; lives on clients.tier and
  is edited via the clients endpoints.
* delivery tier (free/semi/fully) - a preset over the cost dial; lives on
  clients.delivery_tier and is edited here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.util.text import initials

TierKey = Literal["free", "semi", "fully"]
Mode = Literal["off", "byhand", "api"]


class TierResponse(BaseModel):
    """A delivery tier preset (frontend ``Tier``)."""

    key: TierKey
    name: str
    price: int
    tagline: str
    blurb: str
    c: str
    popular: bool = False
    unlocks: list[str]


class FeatureAreaResponse(BaseModel):
    """A gated feature area x tier matrix row (frontend ``FeatureArea``)."""

    id: str
    name: str
    icon: str
    desc: str
    modes: dict[TierKey, Mode]


class TierClientResponse(BaseModel):
    """A per-client delivery-tier assignment (frontend ``TierClient``)."""

    id: str
    cn: str
    industry: str
    init: str
    c: str
    tier: TierKey

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TierClientResponse:
        name = row.get("name", "")
        return cls(
            id=str(row["id"]),
            cn=name,
            industry=row.get("industry", ""),
            init=initials(name),
            c=row.get("contact_color", "#7B69EE"),
            tier=row.get("delivery_tier", "free"),
        )


class DeliveryTierUpdate(BaseModel):
    tier: TierKey


# --- Reference data (verbatim from tiers.ts) ---------------------------------

TIERS: tuple[TierResponse, ...] = (
    TierResponse(
        key="free", name="Free", price=0, tagline="For trials & leads",
        blurb="No automation, no paid data — free Google + Serper only.", c="#22C08A",
        unlocks=[
            "Google Search Console + Analytics traffic",
            "Client spreadsheet uploads",
            "Serper.dev free rank checks (2,500/mo)",
            "1 free sample / public audit",
            "Basic login portal",
            "On-request basic reports",
        ],
    ),
    TierResponse(
        key="semi", name="Semi-Automated", price=20, tagline="Cost-optimized",
        blurb="AI drafts, humans finish — one shared paid seat, on-request data.",
        c="#4D8DF0", popular=True,
        unlocks=[
            "AI-drafted content — human edits & posts",
            "Manual backlink uploads (Ahrefs / SEMrush seat)",
            "Cloud crawl audits on request",
            "Weekly rank checks",
            "AI schema markup",
            "Competitor SWOT from uploads",
            "AI-drafted branded reports",
            "Task / workflow board",
            "Full read-only portal",
        ],
    ),
    TierResponse(
        key="fully", name="Fully-Automated", price=54, tagline="All-API",
        blurb="DataForSEO nightly pipeline — auto everything, human approves.", c="#7B69EE",
        unlocks=[
            "DataForSEO nightly rankings & keywords",
            "Weekly backlinks & full-site audits",
            "Auto crawl / indexing / redirect checks",
            "Auto content drafted + published on approval",
            "Auto GBP posts + review replies",
            "Scheduled reports",
            "Rank-drop & lost-link alerts",
            "Full portal + live updates",
        ],
    ),
)

FEATURE_AREAS: tuple[FeatureAreaResponse, ...] = (
    FeatureAreaResponse(id="A", name="Data & rankings", icon="trending_up", desc="Rank tracking, keyword & traffic data", modes={"free": "byhand", "semi": "byhand", "fully": "api"}),
    FeatureAreaResponse(id="B", name="Audits & site health", icon="fact_check", desc="Crawls, technical audits, indexing", modes={"free": "byhand", "semi": "byhand", "fully": "api"}),
    FeatureAreaResponse(id="C", name="Backlinks & off-page", icon="hub", desc="Backlink profile & lost-link monitoring", modes={"free": "off", "semi": "byhand", "fully": "api"}),
    FeatureAreaResponse(id="D", name="Content & publishing", icon="article", desc="Drafting, editing & CMS publishing", modes={"free": "off", "semi": "byhand", "fully": "api"}),
    FeatureAreaResponse(id="E", name="Local SEO & GBP", icon="storefront", desc="Map-pack, schema, GBP posts & reviews", modes={"free": "off", "semi": "byhand", "fully": "api"}),
    FeatureAreaResponse(id="F", name="Competitors & strategy", icon="insights", desc="SWOT, gap analysis & competitor intel", modes={"free": "off", "semi": "byhand", "fully": "api"}),
    FeatureAreaResponse(id="G", name="Reports, alerts & workflow", icon="summarize", desc="Reporting, task board & live alerts", modes={"free": "byhand", "semi": "byhand", "fully": "api"}),
)


def delivery_tier_modes(tier: TierKey) -> dict[str, Mode]:
    """The per-feature-area dial modes a delivery tier presets (area_id -> mode)."""
    return {area.id: area.modes[tier] for area in FEATURE_AREAS}
