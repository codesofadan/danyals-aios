"""Cost-control request/response models in the frontend shapes (cost.ts)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.util.timefmt import relative_ago

Provider = Literal["Serper", "DataForSEO", "Anthropic", "PageSpeed", "Places", "Voyage"]
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
    DialFeatureMeta(key="cwv", label="Core Web Vitals", icon="speed", provider="PageSpeed", note="Free tier — always on", default_mode="api"),
    DialFeatureMeta(key="content", label="Content Pipeline", icon="article", provider="Anthropic", note="Claude drafting, ~$0.90/pg", default_mode="api"),
    DialFeatureMeta(key="backlinks", label="Backlink Manager", icon="hub", provider="Serper", note="Paid — review before pull", default_mode="byhand"),
    DialFeatureMeta(key="local_seo", label="Local SEO", icon="storefront", provider="Places", note="GBP + map-pack lookups", default_mode="byhand"),
    DialFeatureMeta(key="keywords", label="Keyword Research", icon="search", provider="Serper", note="Paused this cycle", default_mode="off"),
    # Part 6B — the Client-Context / AI-memory module's two AI spends. Both flow
    # through the SAME gate as every other paid call (P6B-4's Gated* wrappers), so
    # ops can throttle context AI to off/byhand/api on the money-dial and no
    # context spend can bypass the budget caps / daily spend-stop.
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
)

DIAL_KEYS: frozenset[str] = frozenset(f.key for f in DIAL_FEATURES)


class ClientBudgetResponse(BaseModel):
    """A per-client budget in the frontend ``ClientBudget`` shape."""

    id: str
    cn: str
    tier: str
    cap: int
    spent: int
    c: str


class BudgetUpdate(BaseModel):
    cap: int = Field(ge=0)


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
    """The org daily spend-stop (frontend dailyStopDefault + live state)."""

    daily_stop: float = Field(serialization_alias="dailyStop")
    halted: bool
    today_spent: float = Field(serialization_alias="todaySpent")


class SpendStopUpdate(BaseModel):
    daily_stop: float | None = Field(default=None, ge=0)
    halted: bool | None = None


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
