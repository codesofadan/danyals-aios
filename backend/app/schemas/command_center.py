"""Command Center (admin-home) aggregate response - the 7C-4 payload.

ONE composite the admin dashboard reads: the KPI stat tiles, the four chart series
(``audits`` / ``traffic`` / ``team`` / ``clients``), the Policy-Radar digest (top
OPEN recommendations awaiting confirmation) and the platform spend snapshot. Shapes
mirror the admin-home surfaces in ``frontend/lib/data.ts`` + the overview components
(``StatTiles`` / ``AuditVolumeChart`` / ``TrafficChart`` / ``TeamTracking`` /
``ClientProgress`` / ``CommandDigest`` / ``SpendSnapshot``).

CONTRACT-LOCK NOTE: this is a COMPOSITE, not a single ``lib/*.ts`` type, so it is
deliberately OUTSIDE ``test_contract_lock`` (there is no one TS type to mirror). The
leaf shapes DO track their TS counterparts (``AuditPoint`` / ``TrafficPoint`` /
``TeamMember`` / ``Client``) and ``digest`` reuses the already-locked
``RecommendationResponse``.

N8 PLACEHOLDER HONESTY: audits are URL-only, so the platform has NO organic-traffic
signal. The ``traffic`` series is therefore an explicit AUDIT-DERIVED ESTIMATE and
is flagged ``placeholder: true`` so the UI can badge it as not-yet-live; every other
series is derived from real rows.

The builders are PURE (rows -> models), so the whole aggregate is unit-testable with
no DB; the router just fans out the RLS-scoped repo reads and calls them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.policy import RecommendationResponse
from app.util.text import initials

# --- leaf shapes -------------------------------------------------------------- #


class StatTile(BaseModel):
    """One KPI tile (frontend ``StatTiles`` ``Tile`` shape). ``value`` is live;
    ``delta``/``note`` are the honest secondary figures, not fabricated trends."""

    icon: str
    label: str
    value: int
    unit: str = ""
    delta: str
    delta_dir: Literal["up", "down"] = Field(serialization_alias="deltaDir")
    note: str
    hero: bool = False


class AuditPoint(BaseModel):
    """One weekly audit-volume point (frontend ``AuditPoint``: ``{w, v}``)."""

    w: str
    v: int


class TrafficPoint(BaseModel):
    """One monthly traffic point (frontend ``TrafficPoint``: ``{m, v}``)."""

    m: str
    v: int


class TrafficSeries(BaseModel):
    """The traffic chart series WRAPPED with the placeholder flag (N8). ``points``
    is the frontend ``TrafficPoint[]``; ``placeholder`` is always ``True`` here -
    it is an audit-derived ESTIMATE, since audits are URL-only (no live analytics)."""

    placeholder: bool = True
    points: list[TrafficPoint]


class TeamPoint(BaseModel):
    """One team-member bar (frontend ``TeamMember``: ``{nm, init, c, jobs}``)."""

    nm: str
    init: str
    c: str
    jobs: int


class ClientPoint(BaseModel):
    """One client-progress row (frontend ``Client``: ``{cn, cd, p}``)."""

    cn: str
    cd: str
    p: int


class SpendFlag(BaseModel):
    """One near/over-cap client in the spend snapshot (frontend ``ov-flag`` row)."""

    cn: str
    spent: int
    cap: int
    pct: int
    c: str


class SpendSnapshot(BaseModel):
    """Platform month-to-date spend rollup (frontend ``SpendSnapshot`` surface)."""

    total_spent: int = Field(serialization_alias="totalSpent")
    total_cap: int = Field(serialization_alias="totalCap")
    pct: int
    flagged: list[SpendFlag]
    daily_stop: float = Field(serialization_alias="dailyStop")
    halted: bool


class GscSummary(BaseModel):
    """Agency-wide Search Console rollup (7C). ``placeholder=true`` until at least
    one property is connected - mirrors the ``traffic`` series's honesty flag, but
    for the opposite reason: this one is REAL once connected, never an estimate."""

    placeholder: bool
    connected: int
    total: int
    clicks_28d: int = Field(serialization_alias="clicks28d")
    impressions_28d: int = Field(serialization_alias="impressions28d")


class Ga4Summary(BaseModel):
    """Agency-wide GA4 rollup (7C). Mirrors :class:`GscSummary` exactly."""

    placeholder: bool
    connected: int
    total: int
    sessions_28d: int = Field(serialization_alias="sessions28d")
    users_28d: int = Field(serialization_alias="users28d")


class CommandCenterResponse(BaseModel):
    """The whole admin-home payload (a COMPOSITE - see the module contract note)."""

    stat_tiles: list[StatTile] = Field(serialization_alias="statTiles")
    audits: list[AuditPoint]
    traffic: TrafficSeries
    team: list[TeamPoint]
    clients: list[ClientPoint]
    digest: list[RecommendationResponse]
    spend: SpendSnapshot
    gsc: GscSummary
    ga4: Ga4Summary


# --- pure helpers ------------------------------------------------------------- #

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# The open (awaiting-confirmation) recommendation states - mirrors policy.ts REC_OPEN.
_REC_OPEN: frozenset[str] = frozenset({"new", "acknowledged"})
_AUDIT_WEEKS = 12
_TRAFFIC_MONTHS = 6
_DIGEST_LIMIT = 4
_TEAM_LIMIT = 5
_CLIENT_LIMIT = 6
# A budget at/above this % of its cap is surfaced as near/over-cap (mirrors cost.ts).
_FLAG_THRESHOLD = 80


def _to_dt(value: Any) -> datetime | None:
    """Best-effort parse of a created_at value (datetime or ISO string) -> aware UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _month_key(dt: datetime) -> tuple[int, int]:
    return (dt.year, dt.month)


# --- builders ----------------------------------------------------------------- #


def build_audit_series(audits: list[dict[str, Any]], *, now: datetime | None = None) -> list[AuditPoint]:
    """Weekly audit volume for the last ``_AUDIT_WEEKS`` ISO weeks (oldest -> newest,
    labelled W1..W12). Counts every audit whose ``created_at`` falls in the week."""
    ref = now or datetime.now(UTC)
    counts = [0] * _AUDIT_WEEKS
    for row in audits:
        dt = _to_dt(row.get("created_at"))
        if dt is None:
            continue
        weeks_ago = (ref - dt).days // 7
        if 0 <= weeks_ago < _AUDIT_WEEKS:
            counts[_AUDIT_WEEKS - 1 - weeks_ago] += 1
    return [AuditPoint(w=f"W{i + 1}", v=v) for i, v in enumerate(counts)]


def build_traffic_series(
    audits: list[dict[str, Any]], *, now: datetime | None = None
) -> TrafficSeries:
    """PLACEHOLDER (N8): an audit-derived monthly estimate, flagged
    ``placeholder=True``. ``v`` is the audit count that month (a stand-in until a
    live analytics source lands), labelled by month abbreviation (oldest -> newest)."""
    ref = now or datetime.now(UTC)
    # Build the last _TRAFFIC_MONTHS month buckets ending at the reference month.
    buckets: list[tuple[int, int]] = []
    y, m = ref.year, ref.month
    for _ in range(_TRAFFIC_MONTHS):
        buckets.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    buckets.reverse()
    counts: dict[tuple[int, int], int] = dict.fromkeys(buckets, 0)
    for row in audits:
        dt = _to_dt(row.get("created_at"))
        if dt is None:
            continue
        key = _month_key(dt)
        if key in counts:
            counts[key] += 1
    points = [TrafficPoint(m=_MONTHS[mo - 1], v=counts[(yr, mo)]) for yr, mo in buckets]
    return TrafficSeries(placeholder=True, points=points)


def build_team_series(
    tasks: list[dict[str, Any]], users_by_id: dict[str, dict[str, Any]]
) -> list[TeamPoint]:
    """Per-member job counts from the tasks ledger (jobs = tasks assigned to the
    member), resolved to name/color via ``users_by_id``. Top ``_TEAM_LIMIT`` by
    jobs; a task with no/unknown assignee is skipped."""
    jobs: dict[str, int] = {}
    for t in tasks:
        aid = t.get("assignee_id")
        if aid is None:
            continue
        key = str(aid)
        jobs[key] = jobs.get(key, 0) + 1
    out: list[TeamPoint] = []
    for uid, count in jobs.items():
        user = users_by_id.get(uid)
        if user is None:
            continue
        name = user.get("name", "")
        out.append(
            TeamPoint(
                nm=name,
                init=initials(name),
                c=user.get("avatar_color", "#7B69EE"),
                jobs=count,
            )
        )
    out.sort(key=lambda p: p.jobs, reverse=True)
    return out[:_TEAM_LIMIT]


def _latest_audit_by_client(audits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map client_name -> its most-recent audit row (by created_at)."""
    latest: dict[str, dict[str, Any]] = {}
    for row in audits:
        name = row.get("client_name", "")
        if not name:
            continue
        cur = latest.get(name)
        if cur is None:
            latest[name] = row
            continue
        cur_dt = _to_dt(cur.get("created_at")) or datetime.min.replace(tzinfo=UTC)
        row_dt = _to_dt(row.get("created_at")) or datetime.min.replace(tzinfo=UTC)
        if row_dt >= cur_dt:
            latest[name] = row
    return latest


def build_client_series(
    clients: list[dict[str, Any]], audits: list[dict[str, Any]]
) -> list[ClientPoint]:
    """Client progress rows: ``cn`` = name; ``cd`` = the latest audit's primary type
    (capitalized) or the tier label when no audit exists; ``p`` = the latest audit
    score (0-100) or 0. Top ``_CLIENT_LIMIT`` clients."""
    latest = _latest_audit_by_client(audits)
    out: list[ClientPoint] = []
    for c in clients[:_CLIENT_LIMIT]:
        name = c.get("name", "")
        audit = latest.get(name)
        if audit is not None:
            types = audit.get("types") or []
            cd = str(types[0]).capitalize() if types else "Audit"
            score = audit.get("score")
            p = int(score) if score is not None else 0
        else:
            cd = f"{c.get('tier', 'Starter')} client"
            p = 0
        out.append(ClientPoint(cn=name, cd=cd, p=p))
    return out


def build_spend_snapshot(
    budgets: list[dict[str, Any]], settings: dict[str, Any]
) -> SpendSnapshot:
    """Platform MTD spend rollup from the per-client budgets + the spend-stop
    settings. ``flagged`` = budgets at/above ``_FLAG_THRESHOLD`` % of cap, worst
    first."""
    total_spent = sum(int(b.get("spent", 0) or 0) for b in budgets)
    total_cap = sum(int(b.get("cap", 0) or 0) for b in budgets)
    pct = round(total_spent / total_cap * 100) if total_cap else 0
    flags: list[SpendFlag] = []
    for b in budgets:
        cap = int(b.get("cap", 0) or 0)
        spent = int(b.get("spent", 0) or 0)
        bpct = round(spent / cap * 100) if cap else 0
        if bpct >= _FLAG_THRESHOLD:
            flags.append(
                SpendFlag(cn=b.get("cn", ""), spent=spent, cap=cap, pct=bpct, c=b.get("c", "#7B69EE"))
            )
    flags.sort(key=lambda f: f.pct, reverse=True)
    return SpendSnapshot(
        total_spent=total_spent,
        total_cap=total_cap,
        pct=pct,
        flagged=flags,
        daily_stop=float(settings.get("daily_stop", 75) or 0),
        halted=bool(settings.get("halted", False)),
    )


def build_digest(rec_rows: list[dict[str, Any]]) -> list[RecommendationResponse]:
    """The top ``_DIGEST_LIMIT`` OPEN recommendations (status new/acknowledged) -
    the CommandDigest 'awaiting confirmation' queue."""
    open_recs = [r for r in rec_rows if str(r.get("status", "")) in _REC_OPEN]
    return [RecommendationResponse.from_row(r) for r in open_recs[:_DIGEST_LIMIT]]


def build_gsc_summary(rows: list[dict[str, Any]]) -> GscSummary:
    """Agency-wide Search Console rollup: how many registered properties are
    actually CONNECTED, and their summed trailing-28-day totals. ``placeholder``
    is true until at least one is connected - unlike ``traffic``, this flips to
    real data the moment a client's property is connected, it is never an
    estimate."""
    connected_rows = [r for r in rows if r.get("oauth_connected")]
    return GscSummary(
        placeholder=not connected_rows,
        connected=len(connected_rows),
        total=len(rows),
        clicks_28d=sum(int(r.get("clicks_28d", 0) or 0) for r in connected_rows),
        impressions_28d=sum(int(r.get("impressions_28d", 0) or 0) for r in connected_rows),
    )


def build_ga4_summary(rows: list[dict[str, Any]]) -> Ga4Summary:
    """Agency-wide GA4 rollup. Mirrors :func:`build_gsc_summary` exactly."""
    connected_rows = [r for r in rows if r.get("oauth_connected")]
    return Ga4Summary(
        placeholder=not connected_rows,
        connected=len(connected_rows),
        total=len(rows),
        sessions_28d=sum(int(r.get("sessions_28d", 0) or 0) for r in connected_rows),
        users_28d=sum(int(r.get("users_28d", 0) or 0) for r in connected_rows),
    )


def _count_this_month(rows: list[dict[str, Any]], ref: datetime) -> int:
    key = (ref.year, ref.month)
    return sum(1 for r in rows if (dt := _to_dt(r.get("created_at"))) and _month_key(dt) == key)


def _count_prev_month(rows: list[dict[str, Any]], ref: datetime) -> int:
    py, pm = (ref.year - 1, 12) if ref.month == 1 else (ref.year, ref.month - 1)
    return sum(1 for r in rows if (dt := _to_dt(r.get("created_at"))) and _month_key(dt) == (py, pm))


def _mom_pct(current: int, previous: int) -> int:
    """Month-over-month % change; a jump from a zero baseline reads as +100%."""
    if previous:
        return round((current - previous) / previous * 100)
    return 100 if current else 0


def build_stat_tiles(
    audits: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    budgets: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[StatTile]:
    """The four admin-home KPI tiles, all from LIVE rows (audits / clients / tasks /
    budgets). ``value`` is real; deltas are honest secondary counts (audits carries a
    real month-over-month %), never a fabricated trend."""
    ref = now or datetime.now(UTC)

    audits_this = _count_this_month(audits, ref)
    mom = _mom_pct(audits_this, _count_prev_month(audits, ref))

    active_clients = sum(1 for c in clients if c.get("status") == "active")
    new_clients = _count_this_month(clients, ref)

    open_tasks = sum(1 for t in tasks if t.get("status") != "done")
    in_review = sum(1 for t in tasks if t.get("status") == "review")

    total_spent = sum(int(b.get("spent", 0) or 0) for b in budgets)
    total_cap = sum(int(b.get("cap", 0) or 0) for b in budgets)
    spend_pct = round(total_spent / total_cap * 100) if total_cap else 0

    return [
        StatTile(
            icon="fact_check",
            label="Audits this month",
            value=audits_this,
            delta=f"{abs(mom)}%",
            delta_dir="up" if mom >= 0 else "down",
            note="vs last month",
            hero=True,
        ),
        StatTile(
            icon="diversity_3",
            label="Active clients",
            value=active_clients,
            delta=str(new_clients),
            delta_dir="up",
            note="onboarded this month",
        ),
        StatTile(
            icon="checklist",
            label="Active tasks",
            value=open_tasks,
            delta=str(in_review),
            delta_dir="up",
            note="in review",
        ),
        StatTile(
            icon="payments",
            label="Spend month-to-date",
            value=total_spent,
            unit="$",
            delta=f"{spend_pct}%",
            delta_dir="up",
            note="of total cap",
        ),
    ]


def build_command_center(
    *,
    audits: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    users_by_id: dict[str, dict[str, Any]],
    budgets: list[dict[str, Any]],
    settings: dict[str, Any],
    rec_rows: list[dict[str, Any]],
    gsc_rows: list[dict[str, Any]] | None = None,
    ga4_rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> CommandCenterResponse:
    """Compose the full admin-home payload from the (already RLS-scoped) rows.
    ``gsc_rows``/``ga4_rows`` default to empty (both summaries come back an honest
    placeholder) so existing callers/tests that predate 7C keep working unchanged."""
    return CommandCenterResponse(
        stat_tiles=build_stat_tiles(audits, clients, tasks, budgets, now=now),
        audits=build_audit_series(audits, now=now),
        traffic=build_traffic_series(audits, now=now),
        team=build_team_series(tasks, users_by_id),
        clients=build_client_series(clients, audits),
        digest=build_digest(rec_rows),
        spend=build_spend_snapshot(budgets, settings),
        gsc=build_gsc_summary(gsc_rows or []),
        ga4=build_ga4_summary(ga4_rows or []),
    )
