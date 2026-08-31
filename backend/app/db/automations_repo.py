"""Data access for ``public.automations`` (0118).

Two seams, for the same reason every other module here has two. Staff READ through
``rls_connection``, where the table's select policy is the enforcement. The dispatcher
and the mutating routes run on ``privileged_connection``: the table deliberately has
no write policy for ``authenticated``, so writes are server actions behind a lead-only
route, exactly as ``job_runs`` does it.

The claim is the load-bearing part. ``claim_due`` selects due rows FOR UPDATE SKIP
LOCKED and advances ``next_due_at`` in the same transaction, so two dispatcher ticks
overlapping - a slow tick, a redelivered one, two workers - cannot both fire the same
automation. That is one of three independent guards; see ``dispatch_automations`` for
the other two.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection
from app.jobs.automation_schedule import next_due

_ROW = (
    "id, name, kind, params, schedule_kind, interval_seconds, cron_expr, enabled, "
    "notify_on_failure, notify_channels, next_due_at, last_fired_at, last_run_id, "
    "last_notified_run_id, created_by, created_at, updated_at"
)

#: One tick claims at most this many. Keeps the transaction - and the row locks it
#: holds - short, and a backlog drains over the following ticks rather than in one
#: burst that could enqueue hundreds of paid jobs at once.
CLAIM_BATCH = 25


class AutomationsRepo:
    """Staff reads, RLS-scoped."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_all(self) -> list[dict[str, Any]]:
        """Every automation, with the outcome of its most recent run.

        Joined rather than fetched per row: the manager shows a status per line, and
        one query per automation is how a fifteen-row screen becomes sixteen requests.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                f"select a.{', a.'.join(_ROW.split(', '))}, "
                "       r.status as last_status, r.finished_at as last_finished_at, "
                "       r.reason as last_reason, r.error_message as last_error "
                "from public.automations a "
                "left join public.job_runs r on r.id = a.last_run_id "
                "order by a.enabled desc, a.name"
            )
            return cur.fetchall()

    def get(self, automation_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                f"select {_ROW} from public.automations where id = %s", (automation_id,)
            )
            return cur.fetchone()


class AutomationsStore:
    """Privileged writes + the dispatcher's claim."""

    def create(
        self,
        *,
        name: str,
        kind: str,
        params: dict[str, Any],
        schedule_kind: str,
        interval_seconds: int | None,
        cron_expr: str | None,
        enabled: bool,
        notify_on_failure: bool,
        notify_channels: dict[str, Any],
        created_by: str | None,
    ) -> dict[str, Any]:
        due = (
            next_due(
                schedule_kind=schedule_kind,
                interval_seconds=interval_seconds,
                cron_expr=cron_expr,
            )
            if enabled
            else None
        )
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.automations "
                "(name, kind, params, schedule_kind, interval_seconds, cron_expr, "
                " enabled, notify_on_failure, notify_channels, next_due_at, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                f"returning {_ROW}",
                (
                    name, kind, Jsonb(params), schedule_kind, interval_seconds, cron_expr,
                    enabled, notify_on_failure, Jsonb(notify_channels), due, created_by,
                ),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover - insert ... returning always yields a row
            raise RuntimeError("automation insert returned no row")
        return row

    def update(self, automation_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a partial edit and recompute when it is next due.

        `next_due_at` is DERIVED here rather than accepted from a caller: it is the one
        column the dispatcher reads, and letting a route set it directly would make
        "when does this actually run" a different question from "what does its schedule
        say".
        """
        if not fields:
            return self._get(automation_id)
        sets: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            sets.append(f"{key} = %s")
            params.append(Jsonb(value) if key in {"params", "notify_channels"} else value)
        params.append(automation_id)
        with privileged_connection() as cur:
            cur.execute(
                f"update public.automations set {', '.join(sets)} where id = %s "
                f"returning {_ROW}",
                params,
            )
            row = cur.fetchone()
            if row is None:
                return None
            due = (
                next_due(
                    schedule_kind=str(row["schedule_kind"]),
                    interval_seconds=row["interval_seconds"],
                    cron_expr=row["cron_expr"],
                )
                if row["enabled"]
                else None
            )
            cur.execute(
                f"update public.automations set next_due_at = %s where id = %s returning {_ROW}",
                (due, automation_id),
            )
            return cur.fetchone()

    def delete(self, automation_id: str) -> bool:
        with privileged_connection() as cur:
            cur.execute("delete from public.automations where id = %s", (automation_id,))
            return cur.rowcount > 0

    def _get(self, automation_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(f"select {_ROW} from public.automations where id = %s", (automation_id,))
            return cur.fetchone()

    # --- the dispatcher -------------------------------------------------------
    def claim_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Take the automations that are due, and advance them past now.

        SKIP LOCKED plus advancing `next_due_at` inside the same transaction is what
        makes an overlapping tick harmless: the second tick sees no due rows rather
        than firing the same automation twice.

        The new due time is computed from NOW, not from the old due time. An
        automation that was overdue - the dispatcher was down, the box was off -
        resumes its cadence from here instead of firing repeatedly to "catch up" on
        every window it missed, which for a paid capability is a bill rather than a
        recovery.
        """
        at = now or datetime.now(UTC)
        with privileged_connection() as cur:
            cur.execute(
                f"select {_ROW} from public.automations "
                "where enabled and next_due_at is not null and next_due_at <= %s "
                "order by next_due_at "
                "limit %s for update skip locked",
                (at, CLAIM_BATCH),
            )
            rows = cur.fetchall()
            for row in rows:
                cur.execute(
                    "update public.automations set next_due_at = %s, last_fired_at = %s "
                    "where id = %s",
                    (
                        next_due(
                            schedule_kind=str(row["schedule_kind"]),
                            interval_seconds=row["interval_seconds"],
                            cron_expr=row["cron_expr"],
                            after=at,
                        ),
                        at,
                        row["id"],
                    ),
                )
            return rows

    def record_run(self, automation_id: str, run_id: str | None) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.automations set last_run_id = %s where id = %s",
                (run_id, automation_id),
            )

    def pending_failure_notices(self) -> list[dict[str, Any]]:
        """Automations whose latest run finished badly and has not been reported.

        `last_notified_run_id` is what makes this at-most-once: a failing automation
        tells someone the first time, not every minute until it is fixed.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select a.id, a.name, a.kind, a.notify_on_failure, a.last_run_id, "
                "       r.status, r.reason, r.error_message "
                "from public.automations a "
                "join public.job_runs r on r.id = a.last_run_id "
                "where a.notify_on_failure "
                "  and a.last_run_id is distinct from a.last_notified_run_id "
                "  and r.status in ('failed', 'blocked', 'degraded')"
            )
            return cur.fetchall()

    def mark_notified(self, automation_id: str, run_id: str) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.automations set last_notified_run_id = %s where id = %s",
                (run_id, automation_id),
            )


def get_automations_repo(user: CurrentUserDep) -> AutomationsRepo:
    return AutomationsRepo(user.id)


AutomationsRepoDep = Annotated[AutomationsRepo, Depends(get_automations_repo)]

_store = AutomationsStore()


def automations_store() -> AutomationsStore:
    return _store


__all__ = [
    "CLAIM_BATCH",
    "AutomationsRepo",
    "AutomationsRepoDep",
    "AutomationsStore",
    "automations_store",
    "get_automations_repo",
]
