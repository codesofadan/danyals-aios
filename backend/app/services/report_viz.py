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

Every other granted key renders a representative sample viz (``placeholder=True``)
mirroring the frontend ``REPORT_VIZ`` shape, with a caption noting it is sample data
until its live provider feed is wired. An empty-data client gets HONEST zero series
(never an exception); a DB hiccup degrades real series to empty rather than raising,
so ``/portal/reports`` is always renderable for a granted client.
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
    GaugeDatumResponse,
    PortalReportResponse,
    ReportVizResponse,
    StatDatumResponse,
)

logger = get_logger("app.report_viz")

# Canonical order + membership (mirrors clientReports in lib/data.ts).
_REPORT_ORDER: tuple[str, ...] = (
    "audit_scores", "rank_tracker", "traffic", "core_web_vitals", "backlinks",
    "competitor", "local_seo", "content_status", "keyword_map", "milestones",
    "progress_dashboard", "monthly_report", "roi_summary",
)

_SAMPLE_NOTE = " · sample data until your live feed is connected"

_HEALTH_LABEL: dict[str, str] = {
    "on_track": "On-track", "at_risk": "At-risk", "completed": "Completed",
}

_MONTHS: list[str] = [
    "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"
]

# Representative sample vizzes, mirroring lib/client.ts REPORT_VIZ, for every key
# whose live provider feed is not yet wired. Values are demo-only; placeholder=True
# + the caption note make that explicit. audit_scores / content_status / milestones
# are NOT here - they are computed from real rows below.
_SAMPLE: dict[str, dict[str, Any]] = {
    "rank_tracker": {
        "kind": "area", "headline": "148", "caption": "Tracked keywords ranking in the top 10",
        "delta": "+37", "up": True, "labels": _MONTHS,
        "points": [63, 71, 79, 84, 91, 98, 104, 112, 121, 130, 139, 148],
    },
    "traffic": {
        "kind": "area", "headline": "318K", "caption": "Organic sessions this month across your site",
        "delta": "+9.4%", "up": True, "labels": _MONTHS,
        "points": [180, 195, 205, 220, 232, 250, 262, 275, 288, 300, 309, 318],
    },
    "core_web_vitals": {
        "kind": "gauge", "headline": "Passing", "caption": "Core Web Vitals field data (last 28 days)",
        "delta": "All green", "up": True,
        "gauges": [
            {"label": "LCP", "value": 2.1, "unit": "s", "max": 4, "good": 2.5},
            {"label": "INP", "value": 142, "unit": "ms", "max": 500, "good": 200},
            {"label": "CLS", "value": 0.06, "unit": "", "max": 0.25, "good": 0.1},
        ],
    },
    "backlinks": {
        "kind": "bars", "headline": "1,284", "caption": "Referring domains — new links won each month",
        "delta": "+64 this mo", "up": True, "labels": _MONTHS,
        "points": [22, 31, 28, 40, 37, 45, 52, 48, 57, 61, 58, 64],
    },
    "competitor": {
        "kind": "bars", "headline": "34%", "caption": "Your share-of-voice vs the tracked competitor set",
        "delta": "+6 pts", "up": True, "labels": ["You", "Rival A", "Rival B", "Rival C", "Rival D"],
        "points": [34, 27, 19, 12, 8],
    },
    "local_seo": {
        "kind": "area", "headline": "88%", "caption": "Map-pack visibility across the local search grid",
        "delta": "+14 pts", "up": True, "labels": _MONTHS,
        "points": [58, 61, 64, 67, 69, 72, 74, 77, 80, 83, 86, 88],
    },
    "keyword_map": {
        "kind": "area", "headline": "612", "caption": "Target keywords mapped & ranking across your pages",
        "delta": "+48", "up": True, "labels": _MONTHS,
        "points": [420, 448, 470, 495, 512, 534, 551, 566, 578, 592, 601, 612],
    },
    "progress_dashboard": {
        "kind": "progress", "headline": "68%", "caption": "Overall engagement completion",
        "progress": 68, "delta": "+8% this mo", "up": True,
    },
    "monthly_report": {
        "kind": "stat", "headline": "Ready", "caption": "Your latest branded monthly SEO report",
        "stats": [
            {"label": "Traffic", "value": "+9.4%", "up": True},
            {"label": "Rankings", "value": "+37", "up": True},
            {"label": "Conversions", "value": "+21%", "up": True},
        ],
    },
    "roi_summary": {
        "kind": "area", "headline": "$48.2K", "caption": "Revenue attributed to organic search this month",
        "delta": "5.8× ROI", "up": True, "labels": _MONTHS,  # noqa: RUF001 - matches frontend glyph
        "points": [18, 21, 24, 27, 29, 33, 36, 38, 41, 44, 46, 48],
    },
}


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
        else:
            out.append(_placeholder_report(key))
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


def _placeholder_report(key: str) -> PortalReportResponse:
    """A representative sample viz for a key whose live feed is not yet wired."""
    spec = dict(_SAMPLE[key])
    gauges = [GaugeDatumResponse(**g) for g in spec.pop("gauges", [])] or None
    stats = [StatDatumResponse(**s) for s in spec.pop("stats", [])] or None
    caption = str(spec.pop("caption", "")) + _SAMPLE_NOTE
    viz = ReportVizResponse(caption=caption, gauges=gauges, stats=stats, **spec)
    return PortalReportResponse(key=key, viz=viz, placeholder=True)
