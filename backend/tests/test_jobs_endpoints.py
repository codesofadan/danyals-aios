"""Unit tests for the job-contract operator surface (``/api/v1/jobs/*``).

Faked repo + store + enqueue; no DB, no broker. What is actually being pinned:

  * the STAFF boundary - a portal client is 403'd out of the whole namespace, and
    stopping or replaying work is lead-only;
  * that ``degraded`` is reported as its own number and never added to a success
    count, which is the entire reason the vocabulary distinguishes them;
  * that REPLAY cannot double-spend - it uses a fresh idempotency key (reusing the
    original would silently skip the work), it refuses an already-replayed letter,
    and if it loses the race it does not enqueue at all;
  * that a dead letter cannot be closed without a written decision.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import app.routers.jobs as jobs_router
from app.core.auth import CurrentUser, get_current_user
from app.db.job_runs_repo import get_job_runs_repo
from app.schemas.jobs import JobRunResponse

pytestmark = pytest.mark.unit

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_DL_ID = "22222222-2222-4222-8222-222222222222"
_CLIENT_ID = "33333333-3333-4333-8333-333333333333"
_CORRELATION = "44444444-4444-4444-8444-444444444444"


def _run(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _RUN_ID,
        "job_name": "content.publish",
        "task": "publish_content_job",
        "queue": "long",
        "idempotency_key": "content.publish:job-7",
        "correlation_id": _CORRELATION,
        "parent_run_id": None,
        "client_id": _CLIENT_ID,
        "client_name": "Acme",
        "scope_type": "content_job",
        "scope_id": None,
        "status": "completed",
        "attempt": 1,
        "max_attempts": 3,
        "scheduled_for": None,
        "started_at": None,
        "finished_at": None,
        "heartbeat_at": None,
        "cancel_requested_at": None,
        "detail": "",
        "reason": "",
        "reason_code": "",
        "error_type": "",
        "error_message": "",
        "cost_usd": 0,
        "result": None,
        "created_at": None,
    }
    row.update(over)
    return row


def _dead_letter(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _DL_ID,
        "run_id": _RUN_ID,
        "job_name": "content.publish",
        "task": "publish_content_job",
        "queue": "long",
        "client_id": _CLIENT_ID,
        "client_name": "Acme",
        "scope_type": "content_job",
        "scope_id": None,
        "correlation_id": _CORRELATION,
        "idempotency_key": "content.publish:job-7",
        "payload": {"args": ["job-7"], "kwargs": {"force": True}},
        "attempts": 3,
        "reason_code": "retries_exhausted",
        "error_type": "RetryableJobError",
        "error_message": "provider 503",
        "traceback": "Traceback...",
        "dead_lettered_at": None,
        "first_failed_at": None,
        "replayed_at": None,
        "replayed_run_id": None,
        "resolved_at": None,
        "resolution": "",
    }
    row.update(over)
    return row


class FakeRepo:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.dead_letters: list[dict[str, Any]] = []
        self.counts: list[dict[str, Any]] = []
        self.open_dlq = 0
        self.list_kwargs: dict[str, Any] = {}

    def list_runs(self, **kw: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kw
        return self.runs

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return next((r for r in self.runs if str(r["id"]) == run_id), None)

    def list_dead_letters(self, **kw: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kw
        return self.dead_letters

    def get_dead_letter(self, dl_id: str) -> dict[str, Any] | None:
        return next((d for d in self.dead_letters if str(d["id"]) == dl_id), None)

    def counts_by_status(self, *, since_hours: int = 24) -> list[dict[str, Any]]:
        return self.counts

    def count_open_dead_letters(self) -> int:
        return self.open_dlq

    def in_flight_by_client(self) -> list[dict[str, Any]]:
        return [{"client_id": _CLIENT_ID, "client_name": "Acme", "queue": "long", "running": 2}]


class FakeStore:
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.cancel_result: dict[str, Any] | None = None
        self.claim_result: tuple[dict[str, Any], bool] = ({"id": "run-new", "correlation_id": _CORRELATION}, True)
        self.mark_replayed_result: dict[str, Any] | None = None
        self.resolve_result: dict[str, Any] | None = None
        self.claims: list[dict[str, Any]] = []

    def request_cancel(self, run_id: str, *, requested_by: str | None) -> dict[str, Any] | None:
        self.cancelled.append(run_id)
        return self.cancel_result

    def claim(self, **kw: Any) -> tuple[dict[str, Any], bool]:
        self.claims.append(kw)
        return self.claim_result

    def mark_replayed(self, dl_id: str, **kw: Any) -> dict[str, Any] | None:
        return self.mark_replayed_result

    def resolve_dead_letter(self, dl_id: str, **kw: Any) -> dict[str, Any] | None:
        return self.resolve_result


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(jobs_router, "job_runs_store", lambda: fake)

    async def _no_activity(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(jobs_router, "record_activity", _no_activity)
    return fake


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _enqueue(task_name: str, *args: Any, **kwargs: Any) -> str:
        calls.append({"task": task_name, "args": args, **kwargs})
        return "msg-1"

    monkeypatch.setattr(jobs_router, "enqueue", _enqueue)
    return calls


@pytest.fixture
def wire(app: FastAPI, repo: FakeRepo) -> Callable[..., None]:
    app.dependency_overrides[get_job_runs_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


# --------------------------------------------------------------------------- #
# The staff boundary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path",
    ["/api/v1/jobs/runs", "/api/v1/jobs/summary", "/api/v1/jobs/dead-letters", "/api/v1/jobs/in-flight"],
)
async def test_a_portal_client_cannot_see_the_execution_history(
    client: httpx.AsyncClient, wire: Callable[..., None], path: str
) -> None:
    wire("client")
    assert (await client.get(path)).status_code == 403


async def test_any_staff_can_read_the_runs_board(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None]
) -> None:
    repo.runs.append(_run())
    wire("viewer", "u-v")
    resp = await client.get("/api/v1/jobs/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["jobName"] == "content.publish"
    assert body[0]["succeeded"] is True


async def test_a_non_lead_cannot_cancel_or_replay(
    client: httpx.AsyncClient, wire: Callable[..., None], store: FakeStore
) -> None:
    wire("specialist", "u-s")
    assert (await client.post(f"/api/v1/jobs/runs/{_RUN_ID}/cancel", json={})).status_code == 403
    assert (await client.post(f"/api/v1/jobs/dead-letters/{_DL_ID}/replay")).status_code == 403
    assert store.cancelled == []


# --------------------------------------------------------------------------- #
# Degraded is not success
# --------------------------------------------------------------------------- #
async def test_the_summary_never_folds_degraded_into_a_success_count(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None]
) -> None:
    repo.counts = [
        {"status": "completed", "runs": 10, "cost_usd": 1.5},
        {"status": "degraded", "runs": 4, "cost_usd": 0.5},
        {"status": "blocked", "runs": 2, "cost_usd": 0},
        {"status": "failed", "runs": 1, "cost_usd": 0.25},
        {"status": "cancelled", "runs": 3, "cost_usd": 0},
    ]
    repo.open_dlq = 7
    wire("analyst", "u-a")

    body = (await client.get("/api/v1/jobs/summary")).json()
    assert body["totalRuns"] == 20
    assert body["succeededRuns"] == 10, "only `completed` may count as a success"
    assert body["needsAttentionRuns"] == 7, "degraded + blocked + failed"
    assert body["totalCostUsd"] == 2.25
    assert body["openDeadLetters"] == 7
    degraded = next(r for r in body["byStatus"] if r["status"] == "degraded")
    assert degraded["succeeded"] is False


def test_a_degraded_run_serialises_as_not_succeeded_and_keeps_its_reason() -> None:
    row = _run(
        status="degraded",
        reason="published 2 of 10 pages; 8 rejected by the site's REST API",
        reason_code="wp_rest_rejected",
        detail="partial publish",
    )
    body = JobRunResponse.from_row(row)
    assert body.succeeded is False
    assert body.needs_attention is True
    assert "2 of 10" in body.reason
    assert body.reason_code == "wp_rest_rejected", (
        "the machine-readable half must reach the wire, or an operator surface can only "
        "group partial outcomes by grepping prose"
    )


async def test_needs_attention_is_passed_through_to_the_query(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None]
) -> None:
    wire("viewer", "u-v")
    await client.get("/api/v1/jobs/runs?needsAttention=true")
    assert repo.list_kwargs["needs_attention"] is True


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #
async def test_a_lead_can_cancel_a_running_job(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None], store: FakeStore
) -> None:
    repo.runs.append(_run(status="running"))
    store.cancel_result = _run(status="running", cancel_requested_at="2026-08-23T00:00:00Z")
    wire("manager", "u-m")

    resp = await client.post(f"/api/v1/jobs/runs/{_RUN_ID}/cancel", json={"reason": "wrong client"})
    assert resp.status_code == 200
    assert resp.json()["cancelRequested"] is True
    assert store.cancelled == [_RUN_ID]


async def test_cancelling_a_finished_run_is_a_conflict_not_a_lie(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None], store: FakeStore
) -> None:
    """Overwriting a real outcome with 'cancelled' would put a fiction in the ledger."""
    repo.runs.append(_run(status="completed"))
    store.cancel_result = None
    wire("owner", "u-o")

    resp = await client.post(f"/api/v1/jobs/runs/{_RUN_ID}/cancel", json={})
    assert resp.status_code == 409
    assert "completed" in resp.json()["error"]["message"]


async def test_cancelling_an_unknown_run_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None], store: FakeStore
) -> None:
    wire("owner", "u-o")
    resp = await client.post(f"/api/v1/jobs/runs/{_RUN_ID}/cancel", json={})
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Replay - the one action that deliberately re-spends
# --------------------------------------------------------------------------- #
async def test_replay_uses_a_fresh_key_and_re_enqueues_the_original_arguments(
    client: httpx.AsyncClient,
    repo: FakeRepo,
    wire: Callable[..., None],
    store: FakeStore,
    sent: list[dict[str, Any]],
) -> None:
    """Reusing the ORIGINAL key would find the old terminal run and silently skip the
    work - the replay would report success and do nothing at all."""
    repo.dead_letters.append(_dead_letter())
    store.mark_replayed_result = _dead_letter(replayed_at="2026-08-23T00:00:00Z")
    wire("admin", "u-ad")

    resp = await client.post(f"/api/v1/jobs/dead-letters/{_DL_ID}/replay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["idempotencyKey"] == f"replay:{_DL_ID}"
    assert body["idempotencyKey"] != _dead_letter()["idempotency_key"]
    assert body["runId"] == "run-new"

    assert store.claims[0]["idempotency_key"] == f"replay:{_DL_ID}"
    assert store.claims[0]["parent_run_id"] == _RUN_ID
    assert store.claims[0]["correlation_id"] == _CORRELATION

    assert sent[0]["task"] == "publish_content_job"
    assert sent[0]["args"] == ("job-7",)
    assert sent[0]["force"] is True
    assert sent[0]["idempotency_key"] == f"replay:{_DL_ID}"


async def test_an_already_replayed_dead_letter_is_refused(
    client: httpx.AsyncClient,
    repo: FakeRepo,
    wire: Callable[..., None],
    store: FakeStore,
    sent: list[dict[str, Any]],
) -> None:
    repo.dead_letters.append(_dead_letter(replayed_at="2026-08-23T00:00:00Z"))
    wire("admin", "u-ad")
    resp = await client.post(f"/api/v1/jobs/dead-letters/{_DL_ID}/replay")
    assert resp.status_code == 409
    assert sent == [], "a refused replay must not enqueue anything"


async def test_losing_the_replay_race_enqueues_nothing(
    client: httpx.AsyncClient,
    repo: FakeRepo,
    wire: Callable[..., None],
    store: FakeStore,
    sent: list[dict[str, Any]],
) -> None:
    """Two leads clicking replay at once must produce one execution, not two - this is
    the only operator action that deliberately re-spends money."""
    repo.dead_letters.append(_dead_letter())
    store.mark_replayed_result = None  # someone else claimed it first
    wire("admin", "u-ad")

    resp = await client.post(f"/api/v1/jobs/dead-letters/{_DL_ID}/replay")
    assert resp.status_code == 409
    assert sent == []


async def test_a_second_replay_of_the_same_letter_cannot_create_a_second_run(
    client: httpx.AsyncClient,
    repo: FakeRepo,
    wire: Callable[..., None],
    store: FakeStore,
    sent: list[dict[str, Any]],
) -> None:
    """The claim's unique key is the backstop: if a run already exists for this
    replay key, the endpoint refuses rather than enqueueing beside it."""
    repo.dead_letters.append(_dead_letter())
    store.claim_result = ({"id": "run-existing", "correlation_id": _CORRELATION}, False)
    wire("admin", "u-ad")

    resp = await client.post(f"/api/v1/jobs/dead-letters/{_DL_ID}/replay")
    assert resp.status_code == 409
    assert sent == []


# --------------------------------------------------------------------------- #
# Resolve
# --------------------------------------------------------------------------- #
async def test_a_dead_letter_cannot_be_closed_without_a_decision(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None], store: FakeStore
) -> None:
    repo.dead_letters.append(_dead_letter())
    wire("owner", "u-o")
    for blank in ("", "   "):
        resp = await client.post(
            f"/api/v1/jobs/dead-letters/{_DL_ID}/resolve", json={"resolution": blank}
        )
        assert resp.status_code == 422


async def test_resolving_records_the_decision(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None], store: FakeStore
) -> None:
    repo.dead_letters.append(_dead_letter())
    store.resolve_result = _dead_letter(
        resolved_at="2026-08-23T00:00:00Z", resolution="site had no REST API; moved to manual"
    )
    wire("owner", "u-o")

    resp = await client.post(
        f"/api/v1/jobs/dead-letters/{_DL_ID}/resolve",
        json={"resolution": "site had no REST API; moved to manual"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolution"].startswith("site had no REST API")
    assert body["open"] is False


async def test_resolving_an_already_resolved_letter_is_a_conflict(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[..., None], store: FakeStore
) -> None:
    repo.dead_letters.append(_dead_letter())
    store.resolve_result = None
    wire("owner", "u-o")
    resp = await client.post(
        f"/api/v1/jobs/dead-letters/{_DL_ID}/resolve", json={"resolution": "already done"}
    )
    assert resp.status_code == 409
