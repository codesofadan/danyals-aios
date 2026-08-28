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
# Crawl BREADTH, a separate axis from ``tier`` (which authorises spend) and from
# ``types`` (which scopes dimensions). Recovery plan §3.2 names four tiers; the
# fourth - type-scoped - is the ``types`` picker and is orthogonal to these three.
# ``free`` is the condensed lead magnet, ``standard`` the routine macro health
# read, ``deep`` the full consulting run. Stored lowercase, exactly as written.
AuditDepth = Literal["free", "standard", "deep"]
# Depth is null on rows written before migration 0084. That is a real state
# ("breadth unknown - it came from a process-wide setting"), never a default.
_ALL_DEPTHS: frozenset[str] = frozenset({"free", "standard", "deep"})
# The audit-type picker (frontend ``lib/audit.ts`` ``AuditTypeKey``). On-Page +
# Technical are the FREE deterministic dimensions; Off-Page / Local SEO / AI (GEO)
# / Strategy each rely on a paid provider or the AI agents.
AuditTypeKey = Literal["onpage", "offpage", "technical", "local", "geo", "strategy"]

# Types that rely on a paid data source or the AI agents (``audit.ts`` ``paid:
# true``) - gated off on the Free tier so a Free run makes zero paid-provider spend.
PAID_AUDIT_TYPES: frozenset[str] = frozenset({"offpage", "local", "geo", "strategy"})
_ALL_TYPES: frozenset[str] = frozenset(
    {"onpage", "offpage", "technical", "local", "geo", "strategy"}
)


def tier_to_db(tier: AuditTier) -> str:
    """Map the API tier (``Free``/``Paid``) to the stored/engine value."""
    return "paid" if tier == "Paid" else "free"


def tier_from_db(value: str | None) -> AuditTier:
    """Map the stored tier (``free``/``paid``) back to the frontend shape."""
    return "Paid" if value == "paid" else "Free"


def depth_from_db(value: str | None) -> AuditDepth | None:
    """Map the stored depth back, preserving NULL rather than inventing a default.

    A null here means the row predates the depth axis (migration 0084 backfills
    nothing, deliberately). Coercing it to ``"free"`` would claim a 15-page crawl
    for runs that may have covered 100.
    """
    return value if value in _ALL_DEPTHS else None  # type: ignore[return-value]


def default_depth_for_tier(tier: AuditTier) -> AuditDepth:
    """The depth a request means when it names a tier but not a depth.

    A ``Free`` tier run can only ever be ``free`` depth - the engine hard-clears
    every paid provider on ``--mode free``, so a wider crawl would be a bigger
    free crawl, not a better audit. A ``Paid`` request that names no depth gets
    ``standard``: the routine check-in, and the one depth that does not interrupt
    the operator for a confirmation.
    """
    return "free" if tier == "Free" else "standard"


class AuditCreate(BaseModel):
    """POST /audits body: the client, the target URL, the tier, and the types.

    ``types`` is the audit-type picker. It is OPTIONAL: an empty list (the
    default) runs a FULL audit (every type); a non-empty subset scopes the run to
    only those dimensions. Each value is validated against ``AuditTypeKey``.

    ``url`` is only shape-validated here; the endpoint runs the SSRF guard
    (``validate_public_host`` off the event loop) before enqueuing.
    """

    client_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    tier: AuditTier = "Free"
    # NO `types`. The audit-type picker was removed: every audit covers every
    # dimension, and DEPTH decides how much paid corroboration it buys. The picker
    # could not deliver what its labels promised - the engine has no per-dimension
    # flag, so the deterministic crawl always ran in full and a run scoped to
    # "on-page + technical" still returned GEO and strategy findings. An older
    # client that still sends `types` has it ignored (pydantic drops unknown
    # fields), which is the correct reading of that request: the full audit.
    # Does this run appear in the client's own portal? Default FALSE: an audit is
    # internal until someone decides to share it. Before 0096 there was no such
    # decision - every client-linked audit was visible the moment it was created.
    visible_to_client: bool = False
    # Crawl breadth. Omitted -> `default_depth_for_tier` (Free->free, Paid->standard),
    # which is exactly what every request meant before this field existed, so an
    # older client keeps its behaviour unchanged.
    depth: AuditDepth | None = None
    # The page budget the quote was issued for, echoed back. This is how a deep run
    # reproduces the number it was quoted WITHOUT the server re-probing the site:
    # re-probing on submit would make a confirmation depend on a value that can
    # move between quote and submit, producing spurious 409s for no gain. The
    # server still bounds it - see `routers/audits.py`, which refuses anything
    # above the depth's ceiling - so echoing it back can only ever ask for a run
    # the caller was already entitled to.
    max_pages: int | None = Field(default=None, gt=0)
    # The estimate the operator was shown and accepted, in USD. REQUIRED for a
    # depth in `CONFIRM_REQUIRED_DEPTHS` (deep) and ignored otherwise. It is the
    # number itself rather than a bare "yes" so the server can verify the operator
    # confirmed the CURRENT price: a stale figure is refused, not silently honoured.
    confirmed_estimate: float | None = Field(default=None, ge=0)

    def resolved_depth(self) -> AuditDepth:
        """The depth this request runs at, after defaults.

        A ``Free`` tier request is pinned to ``free`` depth even if it asked for
        more: ``--mode free`` hard-clears every paid provider at the engine, so a
        wider free crawl buys more pages of the same two deterministic dimensions
        while multiplying the cost of an UNMETERED path. The endpoint refuses that
        combination rather than quietly downgrading it - see ``routers/audits.py``.
        """
        return self.depth or default_depth_for_tier(self.tier)


class AuditVisibilityUpdate(BaseModel):
    """The one field ``PATCH /audits/{id}/visibility`` may change.

    Deliberately a single-field model rather than a partial ``AuditCreate``:
    sharing a document with a client is the only mutation this route exists for,
    and a wider body would let an operator edit a completed run's url, tier or
    quoted cost through a route reviewed as a sharing control.
    """

    visible_to_client: bool


class AuditResponse(BaseModel):
    """One audit row in the frontend ``AuditRow`` shape."""

    id: str
    client: str
    url: str
    types: list[AuditTypeKey]
    tier: AuditTier
    status: AuditStatus
    # null on rows written before migration 0084 - "breadth unknown", not "free".
    depth: AuditDepth | None = None
    # The pages the engine was asked for. Snapshotted per row, so re-reading an old
    # audit reports the breadth IT ran at rather than today's setting.
    max_pages: int | None = Field(default=None, serialization_alias="maxPages")
    # What the pre-flight gate was told this would cost, next to what it did cost.
    estimated_cost: float | None = Field(default=None, serialization_alias="estimatedCost")
    # The COMMITTED cost, runtime-derived from the engine's own observables.
    #
    # It was already recorded on the row and already visible in Cost Controls, one
    # screen away from the table where audits are actually reviewed. Being
    # reachable is not the same as being present at the decision: an operator
    # scanning the audit list could see what a run was QUOTED and never what it
    # SPENT, which is exactly the comparison that says whether the cost model is
    # any good. Staff-safe by construction - every caller of `GET /audits`
    # (`ViewReports`) can already read `GET /cost/log`, which carries these same
    # figures; the PORTAL response deliberately still omits it.
    cost: float | None = None
    score: int | None = None  # 0-100 composite; null while pending
    runtime: str  # "6m 12s" or "—" while pending
    when: str  # display timestamp, e.g. "Today · 09:14"
    pdf: bool
    json_: bool = Field(serialization_alias="json")
    # Is this audit shared into the client's portal?
    #
    # It was settable at creation and readable NOWHERE, so an operator could
    # share an audit and then had no way to see that they had, and no way to
    # undo it. Migration 0096 also backfilled `true` for every pre-existing
    # client-linked audit, which was correct at the time - it preserved the
    # behaviour of the view it replaced - but it means the exposed set is
    # historical rather than chosen. Surfacing the flag is what makes it
    # reviewable; `PATCH /audits/{id}/visibility` is what makes it reversible.
    visible_to_client: bool = Field(default=False, serialization_alias="visibleToClient")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AuditResponse:
        score = row.get("score")
        max_pages = row.get("max_pages")
        estimated = row.get("estimated_cost")
        # `cost` is `not null default 0`, so a queued row reads as $0.00 - which is
        # true and misleading: nothing has been spent YET. It is surfaced only once
        # the engine actually started, which is exactly the condition the worker
        # commits a cost under (`if result.run_uuid is not None`). Before that it is
        # null: "not yet spent", not "free".
        committed = row.get("cost") if row.get("run_uuid") else None
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            url=row.get("url", ""),
            types=[t for t in (row.get("types") or []) if t in _ALL_TYPES],
            tier=tier_from_db(row.get("tier")),
            depth=depth_from_db(row.get("depth")),
            max_pages=int(max_pages) if max_pages is not None else None,
            estimated_cost=float(estimated) if estimated is not None else None,
            cost=float(committed) if committed is not None else None,
            status=row.get("status", "queued"),
            score=int(score) if score is not None else None,
            runtime=format_runtime(row.get("runtime_seconds")),
            when=format_when(row.get("created_at")),
            pdf=bool(row.get("pdf_path")),
            json_=bool(row.get("json_path")),
            visible_to_client=bool(row.get("visible_to_client")),
        )


class PortalAuditCreate(BaseModel):
    """POST /portal/audits body: the target URL, the tier, and the types.

    Deliberately has NO ``client_id`` field (contrast ``AuditCreate``): a portal
    client's tenant is pinned server-side from its authenticated ``users`` row, so
    a request body can never influence which client an audit is attributed to.
    """

    url: str = Field(min_length=1)
    tier: AuditTier = "Free"


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
    """Audit KPI headline in the frontend ``auditStats`` shape.

    ``lifetime`` and ``avgCostUsd`` were added for the operator dashboard, which
    reads "how many have we ever run" and "what does one cost us" rather than the
    composite score. The four original fields are KEPT even though the dashboard
    no longer renders two of them: ``.claude/skills/aios-audit`` documents this
    response as ``{thisMonth, avgScore, runningNow, turnaroundMin}`` and reads it,
    so removing them would break the skill for a cosmetic change.
    """

    this_month: int = Field(serialization_alias="thisMonth")
    avg_score: int = Field(serialization_alias="avgScore")
    running_now: int = Field(serialization_alias="runningNow")
    turnaround_min: int = Field(serialization_alias="turnaroundMin")
    lifetime: int = Field(default=0, serialization_alias="lifetime")
    # Mean COMMITTED cost of completed runs. Rounded to cents at the edge; a
    # sub-cent mean is real (a free-tier-heavy month) and must not round to 0.
    avg_cost_usd: float = Field(default=0.0, serialization_alias="avgCostUsd")


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
    costs: list[float] = []
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
            # Only COMPLETED runs have a committed cost. A queued row's `cost`
            # column defaults to 0, and averaging that in would report work that
            # has not happened as work that was free.
            if r.get("cost") is not None:
                costs.append(float(r["cost"]))
    avg_score = round(sum(scores) / len(scores)) if scores else 0
    turnaround = round(sum(runtimes) / len(runtimes) / 60) if runtimes else 0
    avg_cost = round(sum(costs) / len(costs), 4) if costs else 0.0
    return AuditStatsResponse(
        this_month=this_month,
        avg_score=avg_score,
        running_now=running,
        turnaround_min=turnaround,
        lifetime=len(rows),
        avg_cost_usd=avg_cost,
    )


class AuditEstimateRequest(BaseModel):
    """POST /audits/estimate body: what a run WOULD cost, before committing to it.

    Mirrors the shape of ``AuditCreate`` minus the target URL, because the price
    is a function of breadth and dimensions, not of which site is crawled. No
    ``client_id`` either: this endpoint reads nothing tenant-scoped and spends
    nothing, so it needs no tenant.
    """

    tier: AuditTier = "Free"
    depth: AuditDepth | None = None
    types: list[AuditTypeKey] = Field(default_factory=list)
    # Optional, and only consulted for a depth that scales to site size (deep).
    # Given one, the quote measures the site's own sitemap and prices the run it
    # would ACTUALLY make rather than the depth's ceiling. Omitted -> the ceiling,
    # which errs high; the quote says which of the two it did.
    url: str | None = None

    @field_validator("types")
    @classmethod
    def _dedupe(cls, value: list[AuditTypeKey]) -> list[AuditTypeKey]:
        seen: list[AuditTypeKey] = []
        for t in value:
            if t not in seen:
                seen.append(t)
        return seen

    def resolved_depth(self) -> AuditDepth:
        """The depth this quote is for, after defaults."""
        return self.depth or default_depth_for_tier(self.tier)


class AuditEstimateResponse(BaseModel):
    """A quote for one audit run: the number, and everything it was derived from.

    The derivation is returned alongside the figure ON PURPOSE. An operator asked
    to approve a spend is being asked to approve a judgement, and "$1.15" alone
    is not reviewable - ``pages`` and ``agents`` are the two variables that move
    it, so they are shown. ``estimatedCost`` is the value the caller echoes back
    as ``confirmedEstimate`` when it creates the run.
    """

    tier: AuditTier
    depth: AuditDepth
    pages: int  # the --max-pages ceiling this depth hands the engine
    agents: bool  # whether the 21-agent AI fan-out fires for these types
    estimated_cost: float = Field(serialization_alias="estimatedCost")
    # True when creating this run requires echoing the figure back. Lets the UI
    # decide whether to show a confirmation step without duplicating the policy.
    confirmation_required: bool = Field(serialization_alias="confirmationRequired")
    # What the site's own sitemap reported, or null for "could not tell". Null is
    # NOT zero: `pages` above then falls back to the depth's ceiling, and the
    # operator can see that is what happened instead of guessing why the number
    # looks round.
    measured_pages: int | None = Field(default=None, serialization_alias="measuredPages")
    # Where the measurement came from (robots_sitemap | sitemap | sitemap_index |
    # unknown), so a surprising quote can be traced to its evidence.
    size_source: str = Field(default="unknown", serialization_alias="sizeSource")
    # True when a probe bound stopped the count short, making `measuredPages` a
    # FLOOR on the real total rather than the total.
    size_truncated: bool = Field(default=False, serialization_alias="sizeTruncated")
