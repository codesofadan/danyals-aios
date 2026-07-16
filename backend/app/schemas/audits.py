"""Audit job request/response models in the frontend shapes (``lib/audit.ts``).

``AuditResponse`` mirrors ``AuditRow`` exactly: ``id, client, url, types[],
tier`` (Free/Paid), ``status`` (queued/running/done/failed), a 0-100 composite
``score`` (null while pending), a humanized ``runtime`` + ``when``, and the
``pdf``/``json`` availability booleans.

The per-audit ``tier`` is stored lowercase (``free``/``paid`` - it maps directly
to the engine ``--mode``) and surfaced capitalized to match the frontend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.util.timefmt import format_runtime, format_when

AuditTier = Literal["Free", "Paid"]
AuditStatus = Literal["queued", "running", "done", "failed"]
AuditTypeKey = Literal["technical", "actionable", "local", "geo", "backlink"]

# Types that rely on a paid data source (``audit.ts`` ``paid: true``) - gated
# off on the Free tier so a Free run makes zero paid-provider spend.
PAID_AUDIT_TYPES: frozenset[str] = frozenset({"local", "geo", "backlink"})
_ALL_TYPES: frozenset[str] = frozenset(
    {"technical", "actionable", "local", "geo", "backlink"}
)
_DEFAULT_TYPES: tuple[AuditTypeKey, ...] = ("technical", "actionable")


def tier_to_db(tier: AuditTier) -> str:
    """Map the API tier (``Free``/``Paid``) to the stored/engine value."""
    return "paid" if tier == "Paid" else "free"


def tier_from_db(value: str | None) -> AuditTier:
    """Map the stored tier (``free``/``paid``) back to the frontend shape."""
    return "Paid" if value == "paid" else "Free"


class AuditCreate(BaseModel):
    """POST /audits body: the client, the target URL, the tier, and the types.

    ``url`` is only shape-validated here; the endpoint runs the SSRF guard
    (``validate_public_host`` off the event loop) before enqueuing.
    """

    client_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    tier: AuditTier = "Free"
    types: list[AuditTypeKey] = Field(default_factory=lambda: list(_DEFAULT_TYPES))

    @field_validator("types")
    @classmethod
    def _dedupe_nonempty(cls, value: list[AuditTypeKey]) -> list[AuditTypeKey]:
        seen: list[AuditTypeKey] = []
        for t in value:
            if t not in seen:
                seen.append(t)
        if not seen:
            raise ValueError("at least one audit type is required")
        return seen

    def paid_types(self) -> list[str]:
        """The requested types that need a paid data source."""
        return [t for t in self.types if t in PAID_AUDIT_TYPES]


class AuditResponse(BaseModel):
    """One audit row in the frontend ``AuditRow`` shape."""

    id: str
    client: str
    url: str
    types: list[AuditTypeKey]
    tier: AuditTier
    status: AuditStatus
    score: int | None = None  # 0-100 composite; null while pending
    runtime: str  # "6m 12s" or "—" while pending
    when: str  # display timestamp, e.g. "Today · 09:14"
    pdf: bool
    json_: bool = Field(serialization_alias="json")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AuditResponse:
        score = row.get("score")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            url=row.get("url", ""),
            types=[t for t in (row.get("types") or []) if t in _ALL_TYPES],
            tier=tier_from_db(row.get("tier")),
            status=row.get("status", "queued"),
            score=int(score) if score is not None else None,
            runtime=format_runtime(row.get("runtime_seconds")),
            when=format_when(row.get("created_at")),
            pdf=bool(row.get("pdf_path")),
            json_=bool(row.get("json_path")),
        )


class PortalAuditCreate(BaseModel):
    """POST /portal/audits body: the target URL, the tier, and the types.

    Deliberately has NO ``client_id`` field (contrast ``AuditCreate``): a portal
    client's tenant is pinned server-side from its authenticated ``users`` row, so
    a request body can never influence which client an audit is attributed to.
    """

    url: str = Field(min_length=1)
    tier: AuditTier = "Free"
    types: list[AuditTypeKey] = Field(default_factory=lambda: list(_DEFAULT_TYPES))

    @field_validator("types")
    @classmethod
    def _dedupe_nonempty(cls, value: list[AuditTypeKey]) -> list[AuditTypeKey]:
        seen: list[AuditTypeKey] = []
        for t in value:
            if t not in seen:
                seen.append(t)
        if not seen:
            raise ValueError("at least one audit type is required")
        return seen

    def paid_types(self) -> list[str]:
        """The requested types that need a paid data source."""
        return [t for t in self.types if t in PAID_AUDIT_TYPES]


class PortalAuditResponse(BaseModel):
    """One audit as a portal client sees it - a SAFE column subset.

    Sourced from the ``portal_audits`` security-barrier view (list/get) or the
    freshly-inserted row (create). It NEVER carries the sensitive columns
    (cost/error/run_uuid/artifact_dir/paths); PDF/JSON presence is booleans only.
    """

    id: str
    url: str
    types: list[AuditTypeKey]
    tier: AuditTier
    status: AuditStatus
    score: int | None = None  # 0-100 composite; null while pending
    scores: dict[str, Any] = Field(default_factory=dict)  # per-category detail
    runtime: str
    when: str
    pdf: bool
    json_: bool = Field(serialization_alias="json")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalAuditResponse:
        score = row.get("score")
        # The view exposes has_pdf/has_json booleans; a raw insert row exposes the
        # *_path columns instead. Accept either so one model serves both sources.
        pdf = bool(row.get("has_pdf")) or bool(row.get("pdf_path"))
        json_present = bool(row.get("has_json")) or bool(row.get("json_path"))
        raw_scores = row.get("scores")
        return cls(
            id=str(row["id"]),
            url=row.get("url", ""),
            types=[t for t in (row.get("types") or []) if t in _ALL_TYPES],
            tier=tier_from_db(row.get("tier")),
            status=row.get("status", "queued"),
            score=int(score) if score is not None else None,
            scores=raw_scores if isinstance(raw_scores, dict) else {},
            runtime=format_runtime(row.get("runtime_seconds")),
            when=format_when(row.get("created_at")),
            pdf=pdf,
            json_=json_present,
        )


class AuditStatsResponse(BaseModel):
    """Audit KPI headline in the frontend ``auditStats`` shape."""

    this_month: int = Field(serialization_alias="thisMonth")
    avg_score: int = Field(serialization_alias="avgScore")
    running_now: int = Field(serialization_alias="runningNow")
    turnaround_min: int = Field(serialization_alias="turnaroundMin")


def compute_audit_stats(rows: list[dict[str, Any]]) -> AuditStatsResponse:
    """Derive the ``auditStats`` KPIs from the audit rows (pure, unit-testable).

    thisMonth = runs created this calendar month; avgScore = mean composite of
    completed runs; runningNow = in-flight runs; turnaroundMin = mean completed
    runtime in whole minutes.
    """
    month_prefix = datetime.now(UTC).strftime("%Y-%m")
    this_month = 0
    running = 0
    scores: list[int] = []
    runtimes: list[int] = []
    for r in rows:
        if str(r.get("created_at", ""))[:7] == month_prefix:
            this_month += 1
        status = r.get("status")
        if status == "running":
            running += 1
        elif status == "done":
            if r.get("score") is not None:
                scores.append(int(r["score"]))
            if r.get("runtime_seconds"):
                runtimes.append(int(r["runtime_seconds"]))
    avg_score = round(sum(scores) / len(scores)) if scores else 0
    turnaround = round(sum(runtimes) / len(runtimes) / 60) if runtimes else 0
    return AuditStatsResponse(
        this_month=this_month,
        avg_score=avg_score,
        running_now=running,
        turnaround_min=turnaround,
    )
