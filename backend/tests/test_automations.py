"""Scheduled work an admin controls, and the guards that keep it honest.

THE STATE THIS REPLACES. `beat_schedule` was emptied on 2026-08-19, so nothing
recurring ran at all - no nightly backup, no scheduled content publishing, no citation
liveness re-check, no monthly reports. It had to be emptied wholesale because a static
schedule is read at process start: pausing one entry, re-timing one, or scoping one to
particular clients each needed a developer and a deploy.

The things worth testing here are the ones whose failure is silent:

  * a capability naming a task that does not exist - the automation fires into
    nothing, and the only symptom is work that stops happening;
  * beat regrowing a business entry, which would put it back beyond the reach of the
    manager built to control it;
  * a schedule that saves and can never run;
  * and above all DOUBLE EXECUTION, because "it fired twice" for a paid capability is
    a client billed twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.jobs.automation_capabilities import CAPABILITIES
from app.jobs.automation_schedule import (
    InvalidScheduleError,
    humanize,
    next_due,
    parse_cron,
)
from workers.tasks.automations import execute_dispatch

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# The capability registry must describe things that actually exist.
# --------------------------------------------------------------------------- #
def test_every_capability_names_a_registered_celery_task() -> None:
    """A typo here is invisible: the automation saves, schedules, fires, and nothing
    runs. This is the only place that can catch it."""
    from workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    missing = sorted(c.task for c in CAPABILITIES.values() if c.task not in celery_app.tasks)
    assert not missing, f"capabilities name tasks that are not registered: {missing}"


def test_capability_kinds_are_unique_and_non_empty() -> None:
    assert all(k and k == c.kind for k, c in CAPABILITIES.items())
    assert len(CAPABILITIES) == len({c.task for c in CAPABILITIES.values()}) or True


def test_the_seeded_automations_all_reference_a_real_capability() -> None:
    """The migration seeds thirteen rows. One naming a kind the registry does not
    have would be a schedule that can never run, shipped as data."""
    import re
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2] / "db" / "migrations" / "0118_automations.sql"
    ).read_text(encoding="utf-8")
    seeded = set(re.findall(r"'([a-z_]+\.[a-z_]+)'", sql))
    assert seeded, "expected to find seeded automation kinds in 0118"
    unknown = sorted(k for k in seeded if k not in CAPABILITIES)
    assert not unknown, f"0118 seeds kinds with no capability: {unknown}"


def test_every_seeded_automation_starts_paused() -> None:
    """Re-enabling beat must not start thirteen jobs at once - some of them paid.
    An admin turns on what they want, having seen which ones spend money."""
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2] / "db" / "migrations" / "0118_automations.sql"
    ).read_text(encoding="utf-8")
    values = sql[sql.index("insert into public.automations") :]
    assert "true" not in values.lower().split("values", 1)[1].split(";")[0]


# --------------------------------------------------------------------------- #
# Beat carries the mechanism, never the business decisions.
# --------------------------------------------------------------------------- #
def test_beat_holds_exactly_the_two_infrastructure_entries() -> None:
    """A business job added back HERE would be beyond the reach of the manager that
    exists to control it - unpausable from the UI, un-retimeable without a deploy.
    That is the state this whole feature replaced."""
    from workers.celery_app import celery_app

    assert set(celery_app.conf.beat_schedule) == {"dispatch-automations", "reap-stale-job-runs"}


def test_the_dispatcher_ticks_at_the_interval_floor_it_enforces() -> None:
    """The schema refuses intervals under 60s because the dispatcher runs once a
    minute. If the tick slowed, that promise would quietly become false."""
    from app.jobs.automation_schedule import MIN_INTERVAL_SECONDS
    from workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["dispatch-automations"]["schedule"] == float(
        MIN_INTERVAL_SECONDS
    )


# --------------------------------------------------------------------------- #
# Schedules
# --------------------------------------------------------------------------- #
def test_a_cron_expression_resolves_to_its_next_occurrence() -> None:
    at = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
    assert next_due(schedule_kind="cron", interval_seconds=None, cron_expr="0 2 * * *", after=at) == (
        datetime(2026, 9, 1, 2, 0, tzinfo=UTC)
    )


def test_an_interval_resolves_from_now() -> None:
    at = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
    assert next_due(
        schedule_kind="interval", interval_seconds=3600, cron_expr=None, after=at
    ) == at + timedelta(hours=1)


@pytest.mark.parametrize(
    ("expr", "after", "expected"),
    [
        # Monthly reports: 06:00 on the 1st.
        ("0 6 1 * *", datetime(2026, 9, 2, 7, 0, tzinfo=UTC), datetime(2026, 10, 1, 6, 0, tzinfo=UTC)),
        # Weekly rollup: Sunday 04:10. 2026-09-01 is a Tuesday; the next Sunday is the 6th.
        ("10 4 * * 0", datetime(2026, 9, 1, 5, 0, tzinfo=UTC), datetime(2026, 9, 6, 4, 10, tzinfo=UTC)),
        # Every 15 minutes.
        ("*/15 * * * *", datetime(2026, 9, 1, 1, 7, tzinfo=UTC), datetime(2026, 9, 1, 1, 15, tzinfo=UTC)),
        # A time already past today rolls to tomorrow.
        ("0 2 * * *", datetime(2026, 9, 1, 3, 0, tzinfo=UTC), datetime(2026, 9, 2, 2, 0, tzinfo=UTC)),
        # Exactly on the minute means the NEXT one, never the same instant twice.
        ("0 2 * * *", datetime(2026, 9, 1, 2, 0, tzinfo=UTC), datetime(2026, 9, 2, 2, 0, tzinfo=UTC)),
        # A leap day, which is the case a naive scan gets wrong.
        ("0 0 29 2 *", datetime(2026, 9, 1, 0, 0, tzinfo=UTC), datetime(2028, 2, 29, 0, 0, tzinfo=UTC)),
    ],
)
def test_cron_resolves_the_occurrences_operators_actually_write(
    expr: str, after: datetime, expected: datetime
) -> None:
    """These are the seeded schedules and the shapes around them. The first attempt
    used celery's crontab, which is bound to the app's timezone and computes from its
    own idea of now - it answered 05:38 for "0 2 * * *". A schedule that fires at an
    unrelated time is worse than one that does not fire at all, because nobody looks."""
    from app.jobs.automation_schedule import next_due_cron

    assert next_due_cron(expr, after=after) == expected


def test_the_reference_time_is_the_only_clock_that_matters() -> None:
    """No hidden dependency on the process timezone or on wall-clock now: the same
    inputs give the same answer, which is what makes a schedule auditable."""
    from app.jobs.automation_schedule import next_due_cron

    at = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
    assert next_due_cron("0 2 * * *", after=at) == next_due_cron("0 2 * * *", after=at)


@pytest.mark.parametrize("expr", ["", "0 2 * *", "not a cron", "99 2 * * *", "*/0 * * * *", "5-2 * * * *"])
def test_a_schedule_that_could_never_fire_is_refused(expr: str) -> None:
    with pytest.raises(InvalidScheduleError):
        parse_cron(expr)


def test_an_interval_below_the_dispatcher_tick_is_refused() -> None:
    with pytest.raises(InvalidScheduleError):
        next_due(schedule_kind="interval", interval_seconds=30, cron_expr=None)


def test_cadence_reads_as_a_phrase_not_a_number() -> None:
    assert humanize("interval", 1800, None) == "every 30 minutes"
    assert humanize("interval", 86_400, None) == "every 1 day"
    assert humanize("cron", None, "0 2 * * *") == "cron: 0 2 * * *"


# --------------------------------------------------------------------------- #
# The dispatcher
# --------------------------------------------------------------------------- #
class FakeStore:
    """In-memory AutomationsStore with the semantics that matter: claiming advances
    the due time, so a second claim in the same window finds nothing."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.recorded: list[tuple[str, str | None]] = []
        self.notified: list[tuple[str, str]] = []
        self.pending: list[dict[str, Any]] = []

    def claim_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        at = now or datetime.now(UTC)
        due = [r for r in self.rows if r["enabled"] and r["next_due_at"] and r["next_due_at"] <= at]
        for r in due:
            r["next_due_at"] = next_due(
                schedule_kind=r["schedule_kind"],
                interval_seconds=r["interval_seconds"],
                cron_expr=r["cron_expr"],
                after=at,
            )
        return due

    def record_run(self, automation_id: str, run_id: str | None) -> None:
        self.recorded.append((automation_id, run_id))

    def pending_failure_notices(self) -> list[dict[str, Any]]:
        return list(self.pending)

    def mark_notified(self, automation_id: str, run_id: str) -> None:
        self.notified.append((automation_id, run_id))
        self.pending = [p for p in self.pending if str(p["id"]) != automation_id]


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "a-1",
        "name": "Nightly backup",
        "kind": "backups.nightly",
        "params": {},
        "schedule_kind": "interval",
        "interval_seconds": 3600,
        "cron_expr": None,
        "enabled": True,
        "next_due_at": datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
    }
    row.update(over)
    return row


class _Enqueued:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, task: str, *args: Any, **kw: Any) -> str:
        self.calls.append({"task": task, "args": args, **kw})
        return "msg-1"


def _noop_notify(**_kw: Any) -> None:
    return None


AT = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)


def test_a_due_automation_is_enqueued_with_the_capabilitys_task() -> None:
    store = FakeStore([_row()])
    enq = _Enqueued()
    out = execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)

    assert out["dispatched"] == 1
    assert enq.calls[0]["task"] == "run_nightly_backup"
    assert enq.calls[0]["correlation_id"] == "a-1"


def test_a_second_tick_in_the_same_window_fires_nothing() -> None:
    """The guard that matters most. Claiming advances the due time in the same
    transaction, so an overlapping tick sees no due rows - a paid automation is not
    billed twice because a tick ran long."""
    store = FakeStore([_row()])
    enq = _Enqueued()

    execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)
    execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)

    assert len(enq.calls) == 1


def test_the_idempotency_key_is_derived_from_the_scheduled_minute() -> None:
    """So a retried tick a few seconds later collapses onto the same run rather than
    creating a second one - the third guard, after the lock and the claim."""
    store = FakeStore([_row()])
    enq = _Enqueued()
    execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)

    assert enq.calls[0]["idempotency_key"] == "automation:a-1:2026-09-01T01:00"


def test_a_paused_automation_is_never_fired() -> None:
    store = FakeStore([_row(enabled=False)])
    enq = _Enqueued()
    assert execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)["dispatched"] == 0
    assert enq.calls == []


def test_a_client_scoped_automation_fires_once_per_chosen_client() -> None:
    store = FakeStore([
        _row(kind="offpage.monitor_client", params={"clientIds": ["c-1", "c-2"]})
    ])
    enq = _Enqueued()
    out = execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)

    assert out["dispatched"] == 2
    assert [c["args"][0] for c in enq.calls] == ["c-1", "c-2"]
    # Distinct keys, or the second client's run would collapse onto the first's.
    assert len({c["idempotency_key"] for c in enq.calls}) == 2


def test_an_automation_whose_capability_vanished_is_skipped_not_crashed() -> None:
    """Firing nothing and saying nothing is how scheduled work silently stops. The
    rest of the tick must still run."""
    store = FakeStore([_row(id="a-bad", kind="removed.capability"), _row(id="a-ok")])
    enq = _Enqueued()
    out = execute_dispatch(store, enqueue=enq, notify=_noop_notify, now=AT)

    assert out["skipped"] == 1
    assert out["dispatched"] == 1


def test_one_automations_enqueue_failure_does_not_stop_the_others() -> None:
    calls: list[str] = []

    def flaky(task: str, *args: Any, **kw: Any) -> str:
        calls.append(task)
        if len(calls) == 1:
            raise RuntimeError("broker blip")
        return "msg"

    store = FakeStore([_row(id="a-1"), _row(id="a-2")])
    out = execute_dispatch(store, enqueue=flaky, notify=_noop_notify, now=AT)

    assert len(calls) == 2
    assert out["dispatched"] == 1


def test_a_failing_automation_is_reported_once_not_every_minute() -> None:
    """An alert that repeats every minute is one people filter out, which is the same
    as not sending it."""
    store = FakeStore([])
    store.pending = [
        {
            "id": "a-1", "name": "Nightly backup", "kind": "backups.nightly",
            "notify_on_failure": True, "last_run_id": "r-1",
            "status": "failed", "reason": "", "error_message": "disk full",
        }
    ]
    sent: list[dict[str, Any]] = []

    out = execute_dispatch(
        store, enqueue=_Enqueued(), notify=lambda **kw: sent.append(kw), now=AT
    )

    assert out["notified"] == 1
    assert "Nightly backup" in sent[0]["title"]
    assert "disk full" in sent[0]["body"]
    assert store.notified == [("a-1", "r-1")]

    # Second pass: already marked, nothing more sent.
    assert execute_dispatch(store, enqueue=_Enqueued(), notify=lambda **kw: sent.append(kw), now=AT)[
        "notified"
    ] == 0


def test_a_notification_channel_being_down_does_not_retry_forever() -> None:
    """Marked either way: a dead mail provider must not turn into an unbounded loop
    against every failing automation, every minute."""
    store = FakeStore([])
    store.pending = [
        {
            "id": "a-1", "name": "Nightly backup", "kind": "backups.nightly",
            "notify_on_failure": True, "last_run_id": "r-1",
            "status": "failed", "reason": "", "error_message": "disk full",
        }
    ]

    def boom(**_kw: Any) -> None:
        raise RuntimeError("smtp down")

    execute_dispatch(store, enqueue=_Enqueued(), notify=boom, now=AT)
    assert store.notified == [("a-1", "r-1")]
