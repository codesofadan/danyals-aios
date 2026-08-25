"""Client-portal report visualizations: build the per-key ``ReportViz`` payloads a
client's granted reports render.

:func:`build_report_viz` takes the caller's ``client_id`` + its GRANTED report keys
and returns one :class:`PortalReportResponse` per granted key, in the canonical
frontend order (``clientReports`` in ``lib/data.ts``). Three surfaces are REAL,
computed on one privileged connection from the tenant's own rows:

* ``audit_scores``   - the site-health score trended monthly (``audits.score``),
* ``content_status`` - pieces published per month (``content_jobs`` done-by-month),
* ``milestones``     - the engagement's stage progress + health (``client_projects``
  + ``project_stages``).

THOSE THREE ARE THE WHOLE CATALOGUE. Until 2026-08-25 there were thirteen: the other
ten returned hard-coded demo numbers - rankings climbing 63 -> 148, "318K" sessions,
"LCP 2.1s", a backlink profile, a competitor benchmark - flagged ``placeholder=True``
and captioned "sample data until your live feed is connected". Honestly labelled, and
still fabricated performance figures about their own site shown to a paying client, on
the portal page most likely to be screenshotted into a report.

They were removed rather than re-captioned. A client portal that shows three true
things is worth more than one that shows thirteen of which ten are invented, and the
label was doing all the work of making that acceptable.

``placeholder`` stays on the response (the field is contract-locked against the
frontend type) and is now always ``False``. A key regains an entry here when a real
provider feed lands behind it - not before.

An empty-data client gets HONEST zero series (never an exception); a DB hiccup degrades
real series to empty rather than raising, so ``/portal/reports`` is always renderable
for a granted client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Cursor
from psycopg.rows import DictRow

from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.schemas.milestones import STAGE_LABEL, STAGE_ORDER
from app.schemas.portal_reports import (
    PortalReportResponse,
    ReportVizResponse,
    StatDatumResponse,
)

logger = get_logger("app.report_viz")

# Canonical order + membership (mirrors clientReports in lib/data.ts). Every key here
# is computed from the tenant's own rows; there is no sample path any more.
_REPORT_ORDER: tuple[str, ...] = ("audit_scores", "content_status", "milestones")

_HEALTH_LABEL: dict[str, str] = {
    "on_track": "On-track", "at_risk": "At-risk", "completed": "Completed",
}

_MONTHS: list[str] = [
    "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"
]



def build_report_viz(client_id: str, granted_keys: list[str]) -> list[PortalReportResponse]:
    """Build the ordered viz list for a client's GRANTED report keys.

    ONE privileged connection is opened; the real series are computed only for the
    granted real keys. Never raises: a DB failure degrades the real series to empty
    (honest zeros), and every other granted key renders a placeholder sample viz."""
    granted = set(granted_keys)
    audit_series: list[tuple[str, float]] = []
    content_series: list[tuple[str, float]] = []
    milestones: dict[str, Any] | None = None

    try:
        with privileged_connection() as cur:
            if "audit_scores" in granted:
                audit_series = _fetch_audit_scores(cur, client_id)
            if "content_status" in granted:
                content_series = _fetch_content_counts(cur, client_id)
            if "milestones" in granted:
                milestones = _fetch_milestones(cur, client_id)
    except Exception:
        # A missing/unreachable DB should not 500 a granted client's dashboard: the
        # real series stay empty (honest) and placeholders still render.
        logger.warning("report_viz_fetch_failed", client_id=client_id)

    out: list[PortalReportResponse] = []
    for key in _REPORT_ORDER:
        if key not in granted:
            continue
        if key == "audit_scores":
            out.append(_audit_scores_report(audit_series))
        elif key == "content_status":
            out.append(_content_status_report(content_series))
        elif key == "milestones":
            out.append(_milestones_report(milestones))
    return out


# --------------------------------------------------------------------------- #
# Real series (privileged reads over the tenant's own rows)
# --------------------------------------------------------------------------- #
def _month_window(n: int = 12) -> list[tuple[int, int]]:
    """The last ``n`` (year, month) pairs, oldest -> newest, ending this month."""
    now = datetime.now(UTC)
    seq: list[tuple[int, int]] = []
    for i in range(n - 1, -1, -1):
        year, month = now.year, now.month - i
        while month <= 0:
            month += 12
            year -= 1
        seq.append((year, month))
    return seq


def _bucketize(window: list[tuple[int, int]], data: dict[tuple[int, int], float]) -> list[tuple[str, float]]:
    """Map month aggregates onto the fixed window (0 where absent); labelled 'Jul'."""
    return [
        (datetime(year, month, 1).strftime("%b"), float(data.get((year, month), 0.0)))
        for (year, month) in window
    ]


def _fetch_audit_scores(cur: Cursor[DictRow], client_id: str) -> list[tuple[str, float]]:
    cur.execute(
        "select date_trunc('month', coalesce(finished_at, created_at)) as mon, "
        "avg(score)::float as val "
        "from public.audits "
        "where client_id = %s and score is not null "
        "group by mon",
        (client_id,),
    )
    data = {(r["mon"].year, r["mon"].month): round(float(r["val"]), 1) for r in cur.fetchall()}
    return _bucketize(_month_window(), data)


def _fetch_content_counts(cur: Cursor[DictRow], client_id: str) -> list[tuple[str, float]]:
    cur.execute(
        "select date_trunc('month', updated_at) as mon, count(*)::float as cnt "
        "from public.content_jobs "
        "where client_id = %s and status = 'done' "
        "group by mon",
        (client_id,),
    )
    data = {(r["mon"].year, r["mon"].month): float(r["cnt"]) for r in cur.fetchall()}
    return _bucketize(_month_window(), data)


def _fetch_milestones(cur: Cursor[DictRow], client_id: str) -> dict[str, Any] | None:
    cur.execute(
        "select id, health from public.client_projects "
        "where client_id = %s order by created_at desc limit 1",
        (client_id,),
    )
    project = cur.fetchone()
    if project is None:
        return None
    cur.execute(
        "select stage_key, status from public.project_stages where project_id = %s",
        (project["id"],),
    )
    stages = cur.fetchall()
    return {"health": project.get("health"), "stages": stages}


# --------------------------------------------------------------------------- #
# Report constructors
# --------------------------------------------------------------------------- #
def _audit_scores_report(series: list[tuple[str, float]]) -> PortalReportResponse:
    labels = [label for label, _ in series]
    points = [value for _, value in series]
    has_data = any(points)
    if not has_data:
        viz = ReportVizResponse(
            kind="area", headline="—", unit="/100",
            caption="No audit runs yet — your site-health trend appears here once an audit completes.",
            labels=labels, points=points,
        )
        return PortalReportResponse(key="audit_scores", viz=viz, placeholder=False)
    latest = next((p for p in reversed(points) if p), points[-1])
    first = next((p for p in points if p), 0.0)
    delta = round(latest - first, 1)
    viz = ReportVizResponse(
        kind="area", headline=str(round(latest)), unit="/100",
        caption="Overall site-health score, trended monthly",
        delta=f"{'+' if delta >= 0 else ''}{delta:g} pts", up=delta >= 0,
        labels=labels, points=points,
    )
    return PortalReportResponse(key="audit_scores", viz=viz, placeholder=False)


def _content_status_report(series: list[tuple[str, float]]) -> PortalReportResponse:
    labels = [label for label, _ in series]
    points = [value for _, value in series]
    total = int(sum(points))
    if total == 0:
        viz = ReportVizResponse(
            kind="bars", headline="0",
            caption="No content published yet — your monthly pipeline output appears here.",
            labels=labels, points=points,
        )
        return PortalReportResponse(key="content_status", viz=viz, placeholder=False)
    recent = int(points[-1])
    viz = ReportVizResponse(
        kind="bars", headline=str(total),
        caption="Pieces published — pipeline output per month",
        delta=f"+{recent} this mo" if recent else "steady", up=True,
        labels=labels, points=points,
    )
    return PortalReportResponse(key="content_status", viz=viz, placeholder=False)


def _milestones_report(data: dict[str, Any] | None) -> PortalReportResponse:
    if not data or not data.get("stages"):
        viz = ReportVizResponse(
            kind="stat", headline="—",
            caption="No active engagement yet — your delivery milestones appear here once onboarding starts.",
            stats=[StatDatumResponse(label="Stages complete", value="0 / 5")],
        )
        return PortalReportResponse(key="milestones", viz=viz, placeholder=False)

    stages: list[dict[str, Any]] = list(data["stages"])
    total = len(stages)
    complete = sum(1 for s in stages if str(s.get("status")) == "completed")
    current = _current_stage_label(stages)
    health = str(data.get("health") or "on_track")
    health_label = _HEALTH_LABEL.get(health, "On-track")
    viz = ReportVizResponse(
        kind="stat", headline=health_label,
        caption="Where your engagement stands right now",
        stats=[
            StatDatumResponse(label="Stages complete", value=f"{complete} / {total}"),
            StatDatumResponse(label="Current stage", value=current),
            StatDatumResponse(label="Health", value=health_label, up=health == "on_track"),
        ],
    )
    return PortalReportResponse(key="milestones", viz=viz, placeholder=False)


def _current_stage_label(stages: list[dict[str, Any]]) -> str:
    """The stage the project is sitting on (mirrors milestones.ts currentStage)."""
    by_key = {str(s.get("stage_key")): str(s.get("status")) for s in stages}
    ordered = [k for k in STAGE_ORDER if k in by_key]
    for key in ordered:
        if by_key[key] in ("in_progress", "blocked"):
            return STAGE_LABEL.get(key, key)
    for key in ordered:
        if by_key[key] == "upcoming":
            return STAGE_LABEL.get(key, key)
    return STAGE_LABEL.get(ordered[-1], ordered[-1]) if ordered else "—"


