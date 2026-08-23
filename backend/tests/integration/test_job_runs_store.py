"""Integration: the job contract's SQL, proven against real Postgres.

The unit suite (``tests/test_job_contract.py``) proves the runner's LOGIC against an
in-memory store. It cannot prove the four things that only exist in the database, and
those four are exactly where a silent double-spend would come from:

  (A) the partial unique index on ``idempotency_key`` really does resolve a race, and
      the ``ON CONFLICT ... WHERE`` inference clause actually compiles;
  (B) the per-client concurrency cap is a check-then-set inside ONE transaction under
      an advisory lock, so two workers cannot both start the same client's Nth job;
  (C) the CHECK constraints make a lie unrepresentable - a ``degraded`` row with no
      reason, a ``failed`` row with no error type, and a terminal row with no
      ``finished_at`` are all rejected by Postgres, not merely discouraged in Python;
  (D) the reaper actually reclaims a run whose worker died.

Skips unless DATABASE_ADMIN_URL is set (migration 0080 applied).
"""

from __future__ import annotations

import contextlib
import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from app.db.job_runs_repo import JobRunsStore
from app.jobs.contract import StartOutcome
from app.jobs.status import JobQueue, JobStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def store() -> Any:
    settings = get_settings()
    if not settings.database_admin_url:
        pytest.skip("local Postgres not configured (DATABASE_ADMIN_URL)")
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert admin_pool is not None
    admin_pool.open()
    set_pools(None, admin_pool)
    created: list[str] = []
    try:
        yield JobRunsStore(), created
    finally:
        if created:
            with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
                cur.execute("delete from public.job_dead_letters where run_id = any(%s)", (created,))
                cur.execute("delete from public.job_runs where id = any(%s)", (created,))
        clear_pools()
        admin_pool.close()


def _claim(s: JobRunsStore, created: list[str], **over: Any) -> tuple[dict[str, Any], bool]:
    kw: dict[str, Any] = {
        "job_name": "test.job",
        "task": "test_job",
        "queue": JobQueue.STANDARD.value,
        "idempotency_key": f"itest:{uuid.uuid4()}",
        "correlation_id": str(uuid.uuid4()),
        "parent_run_id": None,
        "celery_task_id": "task-1",
        "client_id": None,
        "client_name": "",
        "scope_type": "test",
        "scope_id": None,
        "max_attempts": 1,
    }
    kw.update(over)
    row, was_created = s.claim(**kw)
    if was_created:
        created.append(str(row["id"]))
    return row, was_created


# --------------------------------------------------------------------------- #
# (A) idempotency
# --------------------------------------------------------------------------- #
async def test_a_repeated_idempotency_key_returns_the_same_run(store: Any) -> None:
    s, created = store
    key = f"itest:{uuid.uuid4()}"
    first, created_first = _claim(s, created, idempotency_key=key)
    second, created_second = _claim(s, created, idempotency_key=key)

    assert created_first is True
    assert created_second is False, "the partial unique index did not resolve the duplicate"
    assert str(second["id"]) == str(first["id"])


async def test_a_null_key_never_conflicts(store: Any) -> None:
    """Opting out must not accidentally serialise every un-keyed job onto one row."""
    s, created = store
    a, made_a = _claim(s, created, idempotency_key=None)
    b, made_b = _claim(s, created, idempotency_key=None)
    assert made_a and made_b
    assert str(a["id"]) != str(b["id"])


# --------------------------------------------------------------------------- #
# (B) the per-client concurrency cap
# --------------------------------------------------------------------------- #
async def test_the_cap_stops_the_second_job_of_a_client_from_starting(store: Any) -> None:
    s, created = store
    client_id = _seed_client(created)
    first, _ = _claim(s, created, client_id=client_id)
    second, _ = _claim(s, created, client_id=client_id)

    started = s.start(str(first["id"]), celery_task_id="w1", client_concurrency=1, max_attempts=1)
    assert started.outcome is StartOutcome.STARTED
    assert started.row is not None
    assert started.row["attempt"] == 1
    assert started.row["status"] == JobStatus.RUNNING.value

    capped = s.start(str(second["id"]), celery_task_id="w2", client_concurrency=1, max_attempts=1)
    assert capped.outcome is StartOutcome.CAPPED
    assert capped.in_flight == 1

    # Free the slot and the same run starts.
    s.finish(
        str(first["id"]),
        status=JobStatus.COMPLETED.value,
        detail="done",
        reason="",
        reason_code="",
        error_type="",
        error_message="",
        cost_usd=Decimal("0"),
        result=None,
    )
    now_free = s.start(str(second["id"]), celery_task_id="w2", client_concurrency=1, max_attempts=1)
    assert now_free.outcome is StartOutcome.STARTED


async def test_a_platform_wide_job_is_never_capped(store: Any) -> None:
    """A sweep that belongs to no tenant must not consume a tenant's slots."""
    s, created = store
    first, _ = _claim(s, created, client_id=None)
    second, _ = _claim(s, created, client_id=None)
    assert s.start(str(first["id"]), celery_task_id="w1", client_concurrency=1, max_attempts=1).started
    assert s.start(str(second["id"]), celery_task_id="w2", client_concurrency=1, max_attempts=1).started


async def test_a_run_can_only_be_started_once(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created)
    assert s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1).started
    again = s.start(str(row["id"]), celery_task_id="w2", client_concurrency=0, max_attempts=1)
    assert again.outcome is StartOutcome.NOT_CLAIMABLE


async def test_a_cancelled_run_refuses_to_start(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created)
    assert s.request_cancel(str(row["id"]), requested_by=None) is not None
    result = s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    assert result.outcome is StartOutcome.CANCELLED


async def test_cancelling_a_finished_run_does_nothing(store: Any) -> None:
    """"Cancelled" must never overwrite a real outcome with a fiction."""
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    s.finish(
        str(row["id"]),
        status=JobStatus.COMPLETED.value,
        detail="done",
        reason="",
        reason_code="",
        error_type="",
        error_message="",
        cost_usd=Decimal("0"),
        result=None,
    )
    assert s.request_cancel(str(row["id"]), requested_by=None) is None
    assert s.get(str(row["id"]))["status"] == JobStatus.COMPLETED.value


# --------------------------------------------------------------------------- #
# (C) the CHECK constraints - the lies Postgres refuses to store
# --------------------------------------------------------------------------- #
async def test_postgres_rejects_a_degraded_run_with_no_reason(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        s.finish(
            str(row["id"]),
            status=JobStatus.DEGRADED.value,
            detail="partly worked",
            reason="",  # the lie
            reason_code="wp_rest_rejected",
            error_type="",
            error_message="",
            cost_usd=Decimal("0"),
            result=None,
        )


async def test_postgres_rejects_a_failed_run_with_no_error_type(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        s.finish(
            str(row["id"]),
            status=JobStatus.FAILED.value,
            detail="broke",
            reason="",
            reason_code="",
            error_type="",
            error_message="",
            cost_usd=Decimal("0"),
            result=None,
        )


async def test_postgres_rejects_a_terminal_row_with_no_finish_time(store: Any) -> None:
    """Written directly, bypassing the store, because the store always sets now()."""
    s, created = store
    row, _ = _claim(s, created)
    with pytest.raises(psycopg.errors.CheckViolation), privileged_connection() as cur:
        cur.execute(
            "update public.job_runs set status = 'completed' where id = %s",
            (str(row["id"]),),
        )


async def test_a_completed_run_records_cost_and_result(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    finished = s.finish(
        str(row["id"]),
        status=JobStatus.COMPLETED.value,
        detail="10 pages live",
        reason="",
        reason_code="",
        error_type="",
        error_message="",
        cost_usd=Decimal("2.250000"),
        result={"pages": 10},
    )
    assert finished is not None
    assert finished["cost_usd"] == Decimal("2.250000")
    assert finished["result"] == {"pages": 10}
    assert finished["finished_at"] is not None


async def test_finish_is_idempotent_and_never_overwrites_a_terminal_state(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    kw: dict[str, Any] = {
        "detail": "",
        "reason": "",
        "reason_code": "",
        "error_type": "",
        "error_message": "",
        "cost_usd": Decimal("0"),
        "result": None,
    }
    assert s.finish(str(row["id"]), status=JobStatus.COMPLETED.value, **kw) is not None
    assert s.finish(str(row["id"]), status=JobStatus.CANCELLED.value, **kw) is None
    assert s.get(str(row["id"]))["status"] == JobStatus.COMPLETED.value


# --------------------------------------------------------------------------- #
# retry accounting + the dead letter
# --------------------------------------------------------------------------- #
async def test_a_deferral_does_not_consume_an_attempt(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created, max_attempts=3)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=3)
    s.defer(str(row["id"]), scheduled_for_seconds=30, detail="waiting")
    after = s.get(str(row["id"]))
    assert after["status"] == JobStatus.QUEUED.value
    assert after["attempt"] == 1, "defer must not increment - only start() counts an attempt"
    assert after["scheduled_for"] is not None

    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=3)
    assert s.get(str(row["id"]))["attempt"] == 2


async def test_the_dead_letter_copies_its_facts_from_the_run(store: Any) -> None:
    s, created = store
    client_id = _seed_client(created)
    key = f"itest:{uuid.uuid4()}"
    row, _ = _claim(s, created, client_id=client_id, client_name="Acme", idempotency_key=key)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    s.finish(
        str(row["id"]),
        status=JobStatus.FAILED.value,
        detail="broke",
        reason="",
        reason_code="permanent_error",
        error_type="PermanentJobError",
        error_message="nope",
        cost_usd=Decimal("0"),
        result=None,
    )
    dl_id = s.dead_letter(
        str(row["id"]),
        payload={"args": ["a"], "kwargs": {"b": 1}},
        reason_code="permanent_error",
        error_type="PermanentJobError",
        error_message="nope",
        traceback="Traceback...",
    )
    assert dl_id is not None
    with privileged_connection() as cur:
        cur.execute("select * from public.job_dead_letters where id = %s", (dl_id,))
        dl = cur.fetchone()
    assert dl["job_name"] == "test.job"
    assert dl["idempotency_key"] == key
    assert str(dl["client_id"]) == client_id
    assert dl["payload"] == {"args": ["a"], "kwargs": {"b": 1}}
    assert dl["attempts"] == 1
    assert dl["resolved_at"] is None and dl["replayed_at"] is None


async def test_a_dead_letter_cannot_be_resolved_without_a_note(store: Any) -> None:
    """A queue closed with no reasons written is a graveyard, not a queue."""
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    s.finish(
        str(row["id"]),
        status=JobStatus.FAILED.value,
        detail="broke",
        reason="",
        reason_code="permanent_error",
        error_type="E",
        error_message="",
        cost_usd=Decimal("0"),
        result=None,
    )
    dl_id = s.dead_letter(
        str(row["id"]), payload={}, reason_code="permanent_error", error_type="E",
        error_message="", traceback=""
    )
    with pytest.raises(psycopg.errors.CheckViolation), privileged_connection() as cur:
        cur.execute(
            "update public.job_dead_letters set resolved_at = now() where id = %s", (dl_id,)
        )


# --------------------------------------------------------------------------- #
# (D) the reaper
# --------------------------------------------------------------------------- #
async def test_the_reaper_reclaims_a_run_whose_worker_died(store: Any) -> None:
    """A run left `running` forever holds a concurrency slot against its client, which
    silently drops that client's throughput to zero."""
    s, created = store
    row, _ = _claim(s, created, queue=JobQueue.INTERACTIVE.value)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    # Backdate the heartbeat past the interactive class's budget (60s + 300s grace).
    with privileged_connection() as cur:
        cur.execute(
            "update public.job_runs set heartbeat_at = now() - interval '1 hour' where id = %s",
            (str(row["id"]),),
        )

    reaped = s.reap_stale_runs()
    assert str(row["id"]) in {str(r["id"]) for r in reaped}
    after = s.get(str(row["id"]))
    assert after["status"] == JobStatus.FAILED.value
    assert after["error_type"] == "JobHeartbeatLost"
    assert after["finished_at"] is not None


async def test_the_reaper_leaves_a_healthy_long_job_alone(store: Any) -> None:
    s, created = store
    row, _ = _claim(s, created, queue=JobQueue.LONG.value)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    s.heartbeat(str(row["id"]))
    reaped_ids = {str(r["id"]) for r in s.reap_stale_runs()}
    assert str(row["id"]) not in reaped_ids
    assert s.get(str(row["id"]))["status"] == JobStatus.RUNNING.value


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
_clients: list[str] = []


def _seed_client(created: list[str]) -> str:
    """A real client row, because job_runs.client_id is a foreign key."""
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.clients (name, delivery_tier) values (%s, 'free') returning id",
            (f"JobContract Co {uuid.uuid4().hex[:8]}",),
        )
        client_id = str(cur.fetchone()["id"])
    _clients.append(client_id)
    return client_id


@pytest.fixture(autouse=True, scope="module")
def _cleanup_clients() -> Any:
    yield
    if not _clients:
        return
    with contextlib.suppress(Exception):
        settings = get_settings()
        pool = build_admin_pool(settings.database_admin_url)
        if pool is None:
            return
        pool.open()
        with privileged_connection(pool=pool) as cur:
            cur.execute("delete from public.job_dead_letters where client_id = any(%s)", (_clients,))
            cur.execute("delete from public.job_runs where client_id = any(%s)", (_clients,))
            cur.execute("delete from public.clients where id = any(%s)", (_clients,))
        pool.close()


async def test_start_restamps_the_attempt_budget_from_the_code(store: Any) -> None:
    """A row created by the DLQ-replay endpoint does not know the job's spec, and a
    row created before the spec changed carries a stale budget. Either would violate
    the `attempt <= max_attempts` CHECK on the job's second attempt, so ``start()``
    stamps the budget the running CODE believes in.
    """
    s, created = store
    row, _ = _claim(s, created, max_attempts=1)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=3)
    assert s.get(str(row["id"]))["max_attempts"] == 3

    s.defer(str(row["id"]), scheduled_for_seconds=0, detail="retrying")
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=3)
    after = s.get(str(row["id"]))
    assert after["attempt"] == 2 and after["max_attempts"] == 3


async def test_postgres_rejects_a_degraded_run_with_no_machine_code(store: Any) -> None:
    """Prose alone makes a partial outcome un-countable, so the DB requires both.

    Without this, the only way to ask "how often does a publish degrade for missing
    credentials" is to grep free text that every call site phrases differently.
    """
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        s.finish(
            str(row["id"]),
            status=JobStatus.DEGRADED.value,
            detail="partly worked",
            reason="published 2 of 10 pages",
            reason_code="",  # the un-countable half
            error_type="",
            error_message="",
            cost_usd=Decimal("0"),
            result=None,
        )


async def test_postgres_rejects_a_reason_code_that_is_a_sentence(store: Any) -> None:
    """The code must stay a stable identifier, or grouping by it is meaningless."""
    s, created = store
    row, _ = _claim(s, created)
    s.start(str(row["id"]), celery_task_id="w1", client_concurrency=0, max_attempts=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        s.finish(
            str(row["id"]),
            status=JobStatus.BLOCKED.value,
            detail="no credentials",
            reason="no WordPress credentials are configured for this site",
            reason_code="No WordPress credentials configured",
            error_type="",
            error_message="",
            cost_usd=Decimal("0"),
            result=None,
        )
