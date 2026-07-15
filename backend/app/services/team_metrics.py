"""Real team-performance metrics (Part 7 / 7F-3).

The Team screen renders three per-member percentages - **onTime**, **utilization**
and **quality** - plus the live **activeTasks** / **completed** counts. This module
computes all five from the two ledgers that already carry the truth: the ``tasks``
board (0011) and the append-only ``activity_log`` (0005). It replaces the hard-coded
defaults that ``GET /me`` and the admin roster returned before.

Everything reads through the RLS-scoped ``rls_connection`` seam, so a caller only
aggregates rows RLS lets them see (staff see the whole board + feed; a portal
client never reaches these routes). The DB read (:func:`fetch_member_counts`) is
kept separate from the pure arithmetic (:func:`compute_metrics`) so the formulas
are unit-testable on fixed counts with no database.

The formulas (each documented at its computation site):

* **onTime %** - of a member's *completed* tasks that carried a ``due_date``, the
  share delivered on or before it. Delivery time is the task's ``updated_at`` (for
  a terminal ``done`` row that is the completion stamp). Completed tasks with no
  due date carry no on-time signal and are excluded from the denominator; a member
  with completed-but-undated work scores 100 (nothing was late), and a member with
  no tasks at all scores 0 (no record yet).

* **utilization %** - current in-flight load against a target capacity. ``active``
  = tasks not yet ``done``; utilization = ``active / CAPACITY`` capped at 100. A
  simple, deterministic load heuristic (not a timesheet).

* **quality %** - the review-gate pass rate: approvals over resolved review
  attempts. A content task passes the gate by reaching ``done`` (approved) and is
  bounced back to ``in_progress`` when rejected. Each trip to the gate is the
  member's own "submitted for review" activity event (actor = the assignee), so
  ``submissions`` counts gate attempts; subtracting the tasks still *pending* in
  ``review`` leaves the *resolved* attempts, and the member's ``done`` content
  tasks are the approvals among them. quality = ``content_done / (submissions -
  content_review)`` capped to 0..100; 100 when nothing has been resolved yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

# Tasks-in-flight that read as 100% utilization. A deliberately simple constant:
# utilization is a load signal (how full a member's plate is), not a timesheet.
CAPACITY = 8


@dataclass(frozen=True)
class MemberCounts:
    """Raw per-member aggregates pulled from the two ledgers (all default 0)."""

    active: int = 0  # tasks not yet done (in flight)
    completed: int = 0  # tasks done
    done_with_due: int = 0  # done tasks that carried a due_date
    on_time_done: int = 0  # ...of those, delivered on/before the due_date
    content_done: int = 0  # content_sprint tasks approved (reached done)
    content_review: int = 0  # content_sprint tasks currently pending in review
    submissions: int = 0  # "submitted for review" events by this member (gate trips)


@dataclass(frozen=True)
class MemberMetrics:
    """The five numbers overlaid onto a ``TeamMemberRecord``."""

    active_tasks: int = 0
    completed: int = 0
    on_time: int = 0
    utilization: int = 0
    quality: int = 0


def compute_metrics(c: MemberCounts) -> MemberMetrics:
    """Derive the five member metrics from raw counts. Pure (no I/O), deterministic.

    A member with no tasks at all reports all-zero (a fresh/invited member has no
    record yet - matching the roster's zero convention and avoiding a misleading
    "100% quality on 0 work"). Otherwise each percentage defaults to a neutral 100
    when its own denominator is empty.
    """
    if c.active == 0 and c.completed == 0:
        return MemberMetrics()

    # onTime: on-time deliveries / dated deliveries (100 when none were dated).
    on_time = round(100 * c.on_time_done / c.done_with_due) if c.done_with_due else 100

    # utilization: in-flight load vs target capacity, capped at 100.
    utilization = min(100, round(100 * c.active / CAPACITY)) if CAPACITY else 0

    # quality: approvals / resolved review attempts (100 when none resolved yet).
    resolved = c.submissions - c.content_review
    quality = max(0, min(100, round(100 * c.content_done / resolved))) if resolved > 0 else 100

    return MemberMetrics(
        active_tasks=c.active,
        completed=c.completed,
        on_time=on_time,
        utilization=utilization,
        quality=quality,
    )


# Per-member task aggregates. ``filter (where ...)`` computes every count in one
# pass. The ``ids`` guard is a single bound param used twice: NULL => all members,
# otherwise only the listed ids (efficient for GET /me and a roster page).
_TASK_AGG_SQL = """
select
    assignee_id::text as member_id,
    count(*) filter (where status <> 'done')::int as active,
    count(*) filter (where status = 'done')::int as completed,
    count(*) filter (where status = 'done' and due_date is not null)::int as done_with_due,
    count(*) filter (
        where status = 'done' and due_date is not null and updated_at::date <= due_date
    )::int as on_time_done,
    count(*) filter (where type = 'content_sprint' and status = 'done')::int as content_done,
    count(*) filter (where type = 'content_sprint' and status = 'review')::int as content_review
from public.tasks
where assignee_id is not null
  and (%(ids)s::text[] is null or assignee_id::text = any(%(ids)s::text[]))
group by assignee_id
"""

# Per-member review-gate submissions: each "submitted for review" event is one
# trip to the content gate, recorded with the ASSIGNEE as actor (see tasks.py
# advance -> _advance_action). kind='content' pins it to the review pipeline.
_ACTIVITY_AGG_SQL = """
select actor_id::text as member_id, count(*)::int as submissions
from public.activity_log
where kind = 'content' and action = 'submitted for review' and actor_id is not null
  and (%(ids)s::text[] is null or actor_id::text = any(%(ids)s::text[]))
group by actor_id
"""


def fetch_member_counts(
    caller_id: str, member_ids: Sequence[str] | None = None
) -> dict[str, MemberCounts]:
    """Aggregate the raw per-member counts via the RLS-scoped ``rls_connection``.

    ``member_ids`` restricts the aggregation (``GET /me`` passes one id; the roster
    passes the page's ids); ``None`` aggregates every member the caller may see.
    Blocking (psycopg is sync); callers offload with ``asyncio.to_thread``.
    Members with no tasks/activity are simply absent from the map (the caller
    treats an absent member as all-zero via ``compute_metrics(MemberCounts())``).
    """
    params = {"ids": list(member_ids) if member_ids is not None else None}
    merged: dict[str, dict[str, int]] = {}
    with rls_connection(caller_id) as cur:
        cur.execute(_TASK_AGG_SQL, params)
        for row in cur.fetchall():
            mid = row["member_id"]
            merged[mid] = {k: v for k, v in row.items() if k != "member_id"}
        cur.execute(_ACTIVITY_AGG_SQL, params)
        for row in cur.fetchall():
            merged.setdefault(row["member_id"], {})["submissions"] = row["submissions"]
    return {mid: MemberCounts(**fields) for mid, fields in merged.items()}


class TeamMetricsRepo:
    """RLS-scoped metrics reader bound to the verified caller id."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def member_metrics(
        self, member_ids: Sequence[str] | None = None
    ) -> dict[str, MemberMetrics]:
        """Map member id -> computed metrics (absent members = all-zero)."""
        counts = fetch_member_counts(self._user_id, member_ids)
        return {mid: compute_metrics(c) for mid, c in counts.items()}


def get_team_metrics(user: CurrentUserDep) -> TeamMetricsRepo:
    """Dependency: a metrics reader scoped to the caller (RLS identity = caller)."""
    return TeamMetricsRepo(user.id)


TeamMetricsDep = Annotated[TeamMetricsRepo, Depends(get_team_metrics)]

# A member absent from the aggregation carries no record -> all-zero metrics.
ZERO_METRICS = compute_metrics(MemberCounts())
