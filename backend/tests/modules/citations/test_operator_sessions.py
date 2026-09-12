"""Operator sessions (0130, Phase 4): the batch layer over the human queue.

The properties under test, in order of how expensive they'd be to get wrong:

* TERMINAL IS SERVER-WRITTEN ONLY - the telemetry endpoint cannot write a terminal
  ui_state (unrepresentable in its schema) and cannot move a task backwards (409).
* ONE ACTIVE SESSION PER OPERATOR - creation refuses, and the ad-hoc claim endpoint
  refuses while a session is live (409, never a silently split lease).
* BATCH RELEASE IS TRANSACTIONAL - the last-terminal task and the release of batch
  N+1 happen in ONE transaction inside the repo (asserted structurally on the SQL,
  the same way the drift-recorder contract is pinned; the routing half is exercised
  through the post-terminal hooks with a fake repo).
* SPEC FAIL-CLOSED - a task card for a directory with no ACTIVE spec ships
  hasSpec=false and zero selectors, so the extension offers copy-buttons and can
  never type a client's phone number into a guessed field.
* LEASE REAP - a session whose heartbeat went silent past the lease is stale, and
  the reap is what keeps the one-active-session index from wedging an operator.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

import app.modules.citations.router  # noqa: F401  (populates sys.modules)
from app.core.auth import get_current_user
from app.modules.citations.operator_auth import (
    require_operator_lead,
    resolve_operator,
    resolve_operator_write,
)
from app.modules.citations.repo import get_citation_queue_repo, get_citation_queue_repo_write
from app.modules.citations.sessions import (
    SESSION_LEASE_SECONDS,
    TERMINAL_UI_STATES,
    UI_STATE_ORDER,
    ActiveSessionExistsError,
    NoSessionWorkError,
    OperatorSessionsRepo,
    batch_no_for,
    get_operator_sessions_repo,
    get_operator_sessions_repo_write,
    session_is_stale,
    telemetry_transition_allowed,
)

from .test_queue import FakeQueueRepo, _held_row
from .test_router import _user

pytestmark = pytest.mark.unit

citations_router = sys.modules["app.modules.citations.router"]


# --------------------------------------------------------------------------- #
# The pure state machine.
# --------------------------------------------------------------------------- #
class TestTelemetryTransitions:
    def test_every_strictly_forward_non_terminal_move_is_allowed(self) -> None:
        ladder = sorted(UI_STATE_ORDER, key=UI_STATE_ORDER.__getitem__)
        for i, current in enumerate(ladder):
            for new in ladder[i + 1 :]:
                assert telemetry_transition_allowed(current, new), (current, new)

    def test_backwards_and_repeat_moves_are_refused(self) -> None:
        assert not telemetry_transition_allowed("filled", "opened")
        assert not telemetry_transition_allowed("opened", "opened")
        assert not telemetry_transition_allowed("awaiting_submit", "released")

    def test_no_terminal_value_is_ever_reachable_by_telemetry(self) -> None:
        """The whole authority model: submitted/skipped/deferred/blocked are the
        SERVER's verdicts. A UI report must not be able to fake one."""
        for terminal in TERMINAL_UI_STATES:
            for current in UI_STATE_ORDER:
                assert not telemetry_transition_allowed(current, terminal), terminal

    def test_a_terminal_task_accepts_nothing_further(self) -> None:
        for terminal in TERMINAL_UI_STATES:
            for new in UI_STATE_ORDER:
                assert not telemetry_transition_allowed(terminal, new)

    def test_unknown_states_are_refused_not_guessed(self) -> None:
        assert not telemetry_transition_allowed("opened", "hovered")
        assert not telemetry_transition_allowed("", "opened")


class TestBatchMath:
    def test_tasks_land_in_one_based_batches_of_batch_size(self) -> None:
        assert [batch_no_for(i, 10) for i in (0, 9, 10, 19, 20)] == [1, 1, 2, 2, 3]

    def test_batch_size_one_gives_one_task_per_batch(self) -> None:
        assert [batch_no_for(i, 1) for i in range(3)] == [1, 2, 3]

    def test_a_degenerate_batch_size_never_divides_by_zero(self) -> None:
        assert batch_no_for(5, 0) == 6  # clamped to 1


class TestLeaseReap:
    def test_a_recent_heartbeat_is_not_stale(self) -> None:
        now = datetime.now(UTC)
        assert not session_is_stale(now - timedelta(seconds=60), now)

    def test_silence_past_the_lease_is_stale(self) -> None:
        now = datetime.now(UTC)
        assert session_is_stale(now - timedelta(seconds=SESSION_LEASE_SECONDS + 1), now)

    def test_a_naive_timestamp_is_anchored_not_crashed(self) -> None:
        now = datetime.now(UTC)
        naive = (now - timedelta(seconds=30)).replace(tzinfo=None)
        assert not session_is_stale(naive, now)

    def test_no_timestamp_at_all_reads_as_stale(self) -> None:
        """A session that never heartbeat is not alive; unknown must not read as
        active forever."""
        assert session_is_stale(None, datetime.now(UTC))


# --------------------------------------------------------------------------- #
# Structural contracts on the repo SQL (the transactional shape).
# --------------------------------------------------------------------------- #
class TestRepoTransactionalShape:
    def test_terminal_mark_and_batch_release_share_one_transaction(self) -> None:
        """THE deliverable's core rule: 'inside the terminal handlers, when the last
        task of the current batch goes terminal, the SAME transaction flips batch N+1
        to released, claims them, bumps current_batch'. One `rls_connection` block per
        public method is what makes that true - the release helper takes the CURSOR,
        never opens its own connection."""
        src = inspect.getsource(OperatorSessionsRepo.mark_citation_terminal)
        assert src.count("rls_connection") == 1
        assert "_release_next_batches(cur" in src
        src2 = inspect.getsource(OperatorSessionsRepo._task_terminal)
        assert src2.count("rls_connection") == 1
        assert "_release_next_batches(cur" in src2
        helper = inspect.getsource(OperatorSessionsRepo._release_next_batches)
        assert "rls_connection" not in helper, "the release helper must ride the caller's txn"

    def test_the_release_serializes_on_the_session_row(self) -> None:
        """Two terminal handlers racing on a batch's last two items must serialize,
        not double-release: the session row is locked FOR UPDATE first."""
        src = inspect.getsource(OperatorSessionsRepo._release_next_batches)
        assert "for update" in src
        assert "current_batch" in src

    def test_selection_excludes_claimed_rows_with_skip_locked(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo._select_candidates)
        assert "for update of c skip locked" in src
        assert "claimed_by is null or c.claim_expires_at < now()" in src
        assert "<> 'F'" in src, "route-F rows must never enter a session"

    def test_claims_ride_the_existing_lease_columns(self) -> None:
        """No parallel claim mechanism: sessions stamp the queue's OWN columns."""
        src = inspect.getsource(OperatorSessionsRepo._claim_and_release)
        for col in ("claimed_by", "claimed_at", "claim_expires_at", "human_attempts"):
            assert col in src, col

    def test_the_repo_never_touches_the_privileged_pool(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo)
        assert "privileged_connection" not in src

    def test_active_session_reaps_a_stale_one(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo.active_session)
        assert "session_is_stale" in src
        assert "_abandon" in src
        reap = inspect.getsource(OperatorSessionsRepo._abandon)
        assert "'abandoned'" in reap
        assert "claimed_by = null" in reap, "a reap must release the claims it held"

    def test_heartbeat_spreads_seconds_instead_of_multiplying_them(self) -> None:
        """Banking the full delta onto every open tab would multiply minutes by the
        batch size and corrupt the median the cost model rests on."""
        src = inspect.getsource(OperatorSessionsRepo.heartbeat)
        assert "/ h.n" in src, "the per-row share must divide by the held count"
        assert "worked_seconds + " in src, "seconds ACCUMULATE (per-item semantics)"


# --------------------------------------------------------------------------- #
# Route behavior over a fake repo.
# --------------------------------------------------------------------------- #
_NOW_ISO = datetime.now(UTC).isoformat()


def _session_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "client_id": "cl-secret",
        "client_name": "Acme Dental",
        "operator_id": "00000000-0000-0000-0000-0000000000a1",
        "status": "active",
        "kind": "citation",
        "batch_size": 10,
        "current_batch": 1,
        "task_count": 2,
        "total_batches": 1,
        "created_at": _NOW_ISO,
        "updated_at": _NOW_ISO,
        "closed_at": None,
    }
    row.update(over)
    return row


def _task_row(**over: Any) -> dict[str, Any]:
    """A joined card row: task columns + the SAME aliases a queue item carries."""
    row = _held_row()
    row.update(
        {
            "task_id": "aaaaaaa1-0000-0000-0000-000000000001",
            "batch_no": 1,
            "position": 0,
            "ui_state": "released",
            "ui_state_at": None,
            "telemetry": {},
            "directory_id": "dir-9",
        }
    )
    row.update(over)
    return row


class FakeSessionsRepo:
    """In-memory stand-in for OperatorSessionsRepo."""

    def __init__(self) -> None:
        self.active: dict[str, Any] | None = None
        self.session: dict[str, Any] | None = None
        self.tasks: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.terminal_marks: list[tuple[str, str]] = []
        self.skips: list[tuple[str, str]] = []
        self.defers: list[str] = []
        self.telemetry_calls: list[tuple[str, str]] = []
        self.heartbeats: list[int] = []
        self.counts: list[dict[str, Any]] = []
        self.raise_on_create: Exception | None = None
        self.telemetry_result: dict[str, Any] | None = None
        self.telemetry_error: ValueError | None = None

    def active_session(self, *, reap_stale: bool = True) -> dict[str, Any] | None:
        return self.active

    def create_session(self, **kw: Any) -> dict[str, Any]:
        if self.raise_on_create is not None:
            raise self.raise_on_create
        self.created.append(kw)
        assert self.session is not None
        return self.session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.session

    def list_sessions(self, *, mine: bool = True, active: bool = False) -> list[dict[str, Any]]:
        return [self.session] if self.session else []

    def session_task_rows(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.tasks)

    def heartbeat(self, session_id: str, *, worked_seconds: int) -> dict[str, Any] | None:
        if self.session is None or self.session.get("status") != "active":
            return None
        self.heartbeats.append(worked_seconds)
        return {"ok": True, "extended": len(self.tasks)}

    def close_session(self, session_id: str) -> dict[str, Any] | None:
        if self.session is None:
            return None
        self.session = {**self.session, "status": "completed", "closed_at": _NOW_ISO}
        return self.session

    def record_telemetry(
        self, session_id: str, task_id: str, *, new_state: str, detail: str = ""
    ) -> dict[str, Any] | None:
        if self.telemetry_error is not None:
            raise self.telemetry_error
        self.telemetry_calls.append((task_id, new_state))
        return self.telemetry_result

    def mark_citation_terminal(
        self, citation_id: str, terminal_state: str, *, meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        self.terminal_marks.append((citation_id, terminal_state))
        return {"sessionId": "s1", "batchNo": 1, "released": 0}

    def skip_task(self, session_id: str, task_id: str, *, reason: str) -> dict[str, Any] | None:
        self.skips.append((task_id, reason))
        return {"sessionId": session_id, "taskId": task_id, "batchNo": 1, "released": 0}

    def defer_task(self, session_id: str, task_id: str) -> dict[str, Any] | None:
        self.defers.append(task_id)
        return {"sessionId": session_id, "taskId": task_id, "batchNo": 3, "released": 0}

    def client_work_counts(self) -> list[dict[str, Any]]:
        return list(self.counts)


@pytest.fixture
def sessions(app: Any) -> FakeSessionsRepo:  # type: ignore[misc]
    fake = FakeSessionsRepo()
    app.dependency_overrides[get_operator_sessions_repo] = lambda: fake
    app.dependency_overrides[get_operator_sessions_repo_write] = lambda: fake
    return fake


@pytest.fixture
def queue(app: Any) -> FakeQueueRepo:  # type: ignore[misc]
    fake = FakeQueueRepo()
    app.dependency_overrides[get_citation_queue_repo] = lambda: fake
    app.dependency_overrides[get_citation_queue_repo_write] = lambda: fake
    return fake


@pytest.fixture
def wire(app: Any, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:  # type: ignore[misc]
    """Authenticate as a role on every session-facing resolver (same seams as the
    queue tests, plus the two session-specific composed resolvers). The hybrid
    QueueReader (session-clients) resolves bearer auth by CALLING
    `operator_auth.get_current_user`, so it is patched in that namespace exactly as
    test_router.py's wire does - a dependency override never reaches it."""

    def _as(role: str) -> None:
        u = _user(role)
        app.dependency_overrides[get_current_user] = lambda: u
        app.dependency_overrides[resolve_operator] = lambda: u
        app.dependency_overrides[resolve_operator_write] = lambda: u
        app.dependency_overrides[require_operator_lead] = lambda: u
        app.dependency_overrides[citations_router.resolve_session_card_reader] = lambda: u
        app.dependency_overrides[citations_router.resolve_session_lead] = lambda: u

        import app.modules.citations.operator_auth as operator_auth

        async def _bearer(*a: Any, **kw: Any) -> Any:
            return u

        monkeypatch.setattr(operator_auth, "get_current_user", _bearer)

    return _as


@pytest.fixture
def repo(app: Any) -> Any:  # type: ignore[misc]
    """The CitationsRepo used only for client_name_for on session create."""

    class _Repo:
        def client_name_for(self, client_id: str) -> str | None:
            return "Acme Dental" if client_id != "cl-unknown" else None

    from app.modules.citations.repo import get_citations_repo

    fake = _Repo()
    app.dependency_overrides[get_citations_repo] = lambda: fake
    app.dependency_overrides[citations_router.get_citations_repo_session] = lambda: fake
    return fake


# --- one-active-session + creation -------------------------------------------------
async def test_a_second_session_is_refused_409(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.raise_on_create = ActiveSessionExistsError()
    resp = await client.post(
        "/api/v1/citation-builder/sessions", json={"clientId": "cl-1"}
    )
    assert resp.status_code == 409
    assert "active session" in resp.json()["error"]["message"]


async def test_a_session_with_nothing_to_work_is_refused_not_created_empty(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.raise_on_create = NoSessionWorkError()
    resp = await client.post(
        "/api/v1/citation-builder/sessions", json={"clientId": "cl-1"}
    )
    assert resp.status_code == 409
    assert "Nothing to work" in resp.json()["error"]["message"]


async def test_creation_returns_the_batch_one_cards(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.session = _session_row()
    sessions.tasks = [
        _task_row(),
        _task_row(task_id="aaaaaaa1-0000-0000-0000-000000000002", batch_no=2, ui_state="pending"),
    ]
    resp = await client.post(
        "/api/v1/citation-builder/sessions",
        json={"clientId": "cl-1", "batchSize": 1, "fromGaps": {"limit": 2}},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["client"] == "Acme Dental"
    assert [t["uiState"] for t in body["tasks"]] == ["released", "pending"]
    assert body["tasks"][0]["citationId"] == "cit-1"
    assert body["tasks"][0]["addUrl"] == "https://brownbook.net/add"
    # And the creation params reached the repo.
    assert sessions.created[0]["client_name"] == "Acme Dental"
    assert sessions.created[0]["batch_size"] == 1


async def test_an_unknown_client_is_a_404_before_any_session_exists(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/sessions", json={"clientId": "cl-unknown"}
    )
    assert resp.status_code == 404
    assert sessions.created == []


async def test_batch_size_is_bounded_1_to_25(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    wire("owner")
    for bad in (0, 26):
        resp = await client.post(
            "/api/v1/citation-builder/sessions",
            json={"clientId": "cl-1", "batchSize": bad},
        )
        assert resp.status_code == 422, bad


# --- the ad-hoc claim refusal -------------------------------------------------------
async def test_adhoc_claim_is_refused_while_a_session_is_active(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, queue: FakeQueueRepo,
    wire: Callable[[str], None],
) -> None:
    """A session already owns a batch of claims; an ad-hoc claim beside it would split
    the lease accounting. 409 with a pointer at the session, never a silent second
    lease."""
    wire("owner")
    sessions.active = _session_row()
    queue.available = [_held_row()]
    resp = await client.post("/api/v1/citation-builder/queue/claim", json={})
    assert resp.status_code == 409
    assert "session" in resp.json()["error"]["message"].lower()
    assert queue.held == {}, "the row must not have been claimed"


async def test_adhoc_claim_works_again_once_the_session_is_gone(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, queue: FakeQueueRepo,
    wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.active = None  # closed, or lease-reaped by active_session() itself
    queue.available = [_held_row()]
    resp = await client.post("/api/v1/citation-builder/queue/claim", json={})
    assert resp.status_code == 200
    assert resp.json()["citationId"] == "cit-1"


# --- telemetry: forward-only, terminal unrepresentable ------------------------------
async def test_telemetry_accepts_a_forward_move(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.telemetry_result = {"ui_state": "opened"}
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/telemetry",
        json={"uiState": "opened"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["uiState"] == "opened"
    assert sessions.telemetry_calls == [("t1", "opened")]


async def test_telemetry_refuses_a_backwards_move_with_409(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.telemetry_error = ValueError("telemetry may not move a task filled -> opened")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/telemetry",
        json={"uiState": "opened"},
    )
    assert resp.status_code == 409
    assert "may not move" in resp.json()["error"]["message"]


async def test_terminal_values_are_unrepresentable_in_the_telemetry_schema(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    """Half the authority model is that the wire cannot even SAY 'submitted' here."""
    wire("owner")
    for terminal in ("submitted", "skipped", "deferred", "blocked", "pending", "released"):
        resp = await client.post(
            "/api/v1/citation-builder/sessions/s1/tasks/t1/telemetry",
            json={"uiState": terminal},
        )
        assert resp.status_code == 422, terminal
    assert sessions.telemetry_calls == []


# --- the post-terminal hooks on complete/blocked ------------------------------------
async def test_an_accepted_completion_marks_the_session_task_submitted(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, queue: FakeQueueRepo,
    wire: Callable[[str], None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.citation_liveness import LivenessProbe

    monkeypatch.setattr(citations_router, "is_public_url", lambda url: True)
    monkeypatch.setattr(
        citations_router, "http_liveness_probe",
        lambda url: LivenessProbe(status_code=200, text="<p>Acme Dental</p><p>555-0100</p>", final_url=url),
    )
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/complete",
        json={"liveUrl": "https://brownbook.net/biz/acme"},
    )
    assert resp.status_code == 200 and resp.json()["accepted"] is True
    assert sessions.terminal_marks == [("cit-1", "submitted")]


async def test_a_refused_completion_never_touches_the_session_task(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, queue: FakeQueueRepo,
    wire: Callable[[str], None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """accepted:false keeps the task non-terminal - the operator keeps the tab and the
    claim; nothing was proven, so nothing moves."""
    from app.services.citation_liveness import LivenessProbe

    monkeypatch.setattr(citations_router, "is_public_url", lambda url: True)
    monkeypatch.setattr(
        citations_router, "http_liveness_probe",
        lambda url: LivenessProbe(status_code=200, text="<p>nothing here</p>", final_url=url),
    )
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/complete",
        json={"liveUrl": "https://brownbook.net/biz/acme"},
    )
    assert resp.json()["accepted"] is False
    assert sessions.terminal_marks == []


async def test_a_block_marks_the_session_task_blocked(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, queue: FakeQueueRepo,
    wire: Callable[[str], None],
) -> None:
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/blocked", json={"reason": "paid_only"}
    )
    assert resp.status_code == 204
    assert sessions.terminal_marks == [("cit-1", "blocked")]


async def test_a_broken_session_hook_never_fails_the_completion(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, queue: FakeQueueRepo,
    wire: Callable[[str], None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe accepted the URL; the evidence is written. A session bookkeeping
    failure is logged, never surfaced as a 500 that would teach operators the queue
    eats verified work."""
    from app.services.citation_liveness import LivenessProbe

    monkeypatch.setattr(citations_router, "is_public_url", lambda url: True)
    monkeypatch.setattr(
        citations_router, "http_liveness_probe",
        lambda url: LivenessProbe(status_code=200, text="<p>Acme Dental</p><p>555-0100</p>", final_url=url),
    )

    def _boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("session table down")

    sessions.mark_citation_terminal = _boom  # type: ignore[method-assign]
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/complete",
        json={"liveUrl": "https://brownbook.net/biz/acme"},
    )
    assert resp.status_code == 200 and resp.json()["accepted"] is True


# --- skip / defer -------------------------------------------------------------------
async def test_skip_records_the_reason_and_reports_the_release(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/skip", json={"reason": "already listed"}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "skipped"
    assert sessions.skips == [("t1", "already listed")]


async def test_skip_requires_a_reason(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/skip", json={"reason": ""}
    )
    assert resp.status_code == 422


async def test_defer_rebatches_to_the_tail(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/sessions/s1/tasks/t1/defer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "deferred"
    assert body["batchNo"] == 3  # the fake's tail
    assert sessions.defers == ["t1"]


async def test_skip_and_defer_on_an_unknown_task_are_404(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.skip_task = lambda *a, **k: None  # type: ignore[method-assign]
    sessions.defer_task = lambda *a, **k: None  # type: ignore[method-assign]
    for path in ("skip", "defer"):
        resp = await client.post(
            f"/api/v1/citation-builder/sessions/s1/tasks/tX/{path}",
            json={"reason": "x"} if path == "skip" else None,
        )
        assert resp.status_code == 404, path


# --- heartbeat + close --------------------------------------------------------------
async def test_heartbeat_extends_and_banks(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.session = _session_row()
    sessions.tasks = [_task_row()]
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/heartbeat", json={"workedSeconds": 55}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["extended"] == 1
    assert sessions.heartbeats == [55]


async def test_heartbeat_on_a_dead_session_is_409(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.session = None
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/heartbeat", json={"workedSeconds": 55}
    )
    assert resp.status_code == 409


async def test_close_reports_the_honest_outcome(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.session = _session_row()
    resp = await client.post("/api/v1/citation-builder/sessions/s1/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


# --- the spec fail-closed card ------------------------------------------------------
async def test_a_card_with_no_active_spec_is_fail_closed(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ACTIVE spec => hasSpec=false and EVERY field ships an empty selector. A
    fabricated selector would type a client's phone number into a guessed field."""
    monkeypatch.setattr(citations_router, "db_spec_loader", lambda job: None)
    wire("owner")
    sessions.session = _session_row()
    sessions.tasks = [_task_row()]
    resp = await client.get("/api/v1/citation-builder/sessions/s1")
    assert resp.status_code == 200
    card = resp.json()["tasks"][0]
    assert card["hasSpec"] is False
    assert all(f["selector"] == "" for f in card["fields"])


async def test_a_card_with_an_active_spec_carries_its_selectors(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.directory_specs import FormField, FormSpec

    spec = FormSpec(
        directory_name="Brownbook", url="https://brownbook.net/add",
        fields=(FormField(selector="#name", value_key="business_name"),),
        submit_selector="#go", success_indicator="",
    )
    monkeypatch.setattr(citations_router, "db_spec_loader", lambda job: spec)
    wire("owner")
    sessions.session = _session_row()
    sessions.tasks = [_task_row()]
    resp = await client.get("/api/v1/citation-builder/sessions/s1")
    card = resp.json()["tasks"][0]
    assert card["hasSpec"] is True
    by_key = {f["key"]: f["selector"] for f in card["fields"]}
    assert by_key["business_name"] == "#name"
    assert by_key.get("phone", "") == ""  # only what the spec names, never a guess


# --- scope guards / the 401 sweep ---------------------------------------------------
async def test_every_session_route_401s_unauthenticated(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo,
) -> None:
    """Nothing here is public. The app-wide sweep (`test_route_auth_guard`) also covers
    these; asserted directly because the composed resolvers are exactly the kind of
    wrapper that could quietly drop the 401 floor."""
    for method, path, body in (
        ("GET", "/api/v1/citation-builder/session-clients", None),
        ("GET", "/api/v1/citation-builder/sessions", None),
        ("GET", "/api/v1/citation-builder/sessions/s1", None),
        ("POST", "/api/v1/citation-builder/sessions", {"clientId": "cl-1"}),
        ("POST", "/api/v1/citation-builder/sessions/s1/heartbeat", {"workedSeconds": 1}),
        ("POST", "/api/v1/citation-builder/sessions/s1/close", None),
        ("POST", "/api/v1/citation-builder/sessions/s1/tasks/t1/telemetry", {"uiState": "opened"}),
        ("POST", "/api/v1/citation-builder/sessions/s1/tasks/t1/skip", {"reason": "x"}),
        ("POST", "/api/v1/citation-builder/sessions/s1/tasks/t1/defer", None),
    ):
        resp = await client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path}: {resp.status_code}"


async def test_session_creation_is_refused_to_a_non_lead(
    app: Any, client: httpx.AsyncClient, sessions: FakeSessionsRepo, repo: Any,
) -> None:
    """The composed lead resolver still runs the REAL role gate when only the floor
    resolver is stubbed - an operator token inherits its holder's role and grants
    nothing extra. (`resolve_session_creator` is `require_operator_lead_over` the
    module-level create floor, so overriding the floor by identity leaves the role
    check in place - the same seam design as `resolve_operator_write` under
    `require_operator_lead` on the queue routes.)"""
    app.dependency_overrides[citations_router.resolve_session_create_floor] = (
        lambda: _user("specialist")
    )
    resp = await client.post(
        "/api/v1/citation-builder/sessions", json={"clientId": "cl-1"}
    )
    assert resp.status_code == 403
    assert sessions.created == []


def test_session_routes_are_registered_on_the_real_app() -> None:
    from app.main import create_app

    paths = set(create_app().openapi()["paths"])
    expected = {
        "/api/v1/citation-builder/session-clients",
        "/api/v1/citation-builder/sessions",
        "/api/v1/citation-builder/sessions/{session_id}",
        "/api/v1/citation-builder/sessions/{session_id}/heartbeat",
        "/api/v1/citation-builder/sessions/{session_id}/close",
        "/api/v1/citation-builder/sessions/{session_id}/tasks/{task_id}/telemetry",
        "/api/v1/citation-builder/sessions/{session_id}/tasks/{task_id}/skip",
        "/api/v1/citation-builder/sessions/{session_id}/tasks/{task_id}/defer",
    }
    assert expected <= paths, f"missing: {sorted(expected - paths)}"


# --- operator-token scope guards, exercised through the REAL app --------------------
#
# Same technique as test_operator_route_reach.py: nothing in the dependency graph is
# overridden; only `verify_operator_token` is patched, so every composed resolver runs
# for real and the scope model is what refuses.


def _principal_with(*scopes: str) -> Any:
    from app.services.operator_tokens import OperatorPrincipal

    return OperatorPrincipal(
        token_id="t1", user_id="u1",
        scopes=frozenset(scopes), expires_at=None, issued_at=None,
    )


async def _real_app_codes(
    routes: list[tuple[str, str, dict[str, Any] | None]],
) -> list[int]:
    from asgi_lifespan import LifespanManager

    from app.main import create_app

    app = create_app()
    codes: list[int] = []
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            for method, path, body in routes:
                r = await c.request(
                    method, path, headers={"X-Operator-Token": "aop_x_y"}, json=body
                )
                codes.append(r.status_code)
    return codes


async def test_a_scope_refusal_is_403_and_names_the_scopes_to_fix_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal must not read as "your credential is bad".

    THE BUG THIS PINS. A missing scope used to answer 401. The extension maps every 401
    to `NeedsPairing` and shows the pairing screen, so an operator whose token lacked
    `web2_queue:write` (which `DEFAULT_MINT_SCOPES` deliberately does not grant) was
    told to re-pair — re-paired, received the same citation-only scopes, and was sent
    back to the pairing screen again, forever. The server was reporting the wrong
    problem, so the only fix that would work was never named.

    Two things are asserted, because fixing the code alone would still leave the
    operator guessing: the status is 403, AND the detail names the scopes that would
    satisfy it. A refusal an operator cannot act on is barely better than a loop.
    """
    from asgi_lifespan import LifespanManager

    import app.modules.citations.operator_auth as operator_auth
    from app.main import create_app

    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read", "citation_queue:write"),
    )
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            r = await c.post(
                "/api/v1/citation-builder/sessions",
                headers={"X-Operator-Token": "aop_x_y"},
                json={"clientId": "c1", "kind": "web2_placement"},
            )
    assert r.status_code == 403, "a verified token short a scope is FORBIDDEN, not unauthenticated"
    detail = r.json()["error"]["message"]
    assert "web2_queue:write" in detail, "the refusal must name the scope that would fix it"
    assert "re-pairing" in detail.lower(), "and must say that re-pairing will not help"


async def test_the_task_card_reads_need_client_profile_read_on_top_of_queue_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cards carry the canonical NAP, so a queue-only token must not see them -
    the same rule GET /business-profiles enforces, composed onto the session detail."""
    import app.modules.citations.operator_auth as operator_auth

    route = [("GET", "/api/v1/citation-builder/sessions/s1", None)]
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read", "citation_queue:write"),
    )
    assert (await _real_app_codes(route)) == [403]
    # With the profile scope the refusal is gone (later failures are env, never 401).
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read", "client_profile:read"),
    )
    assert 403 not in (await _real_app_codes(route))


async def test_session_creation_needs_write_plus_profile_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.citations.operator_auth as operator_auth

    route = [("POST", "/api/v1/citation-builder/sessions", {"clientId": "cl-1"})]
    # Write alone: refused (the response carries NAP).
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read", "citation_queue:write"),
    )
    assert (await _real_app_codes(route)) == [403]
    # Profile alone: refused (creation is a queue write).
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("client_profile:read"),
    )
    assert (await _real_app_codes(route)) == [403]


async def test_telemetry_and_heartbeat_need_only_the_write_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry/heartbeat carry no NAP and no evidence - the write scope is the whole
    requirement on the extension path (reads still need :read via the repo floor)."""
    import app.modules.citations.operator_auth as operator_auth

    routes = [
        ("POST", "/api/v1/citation-builder/sessions/s1/heartbeat", {"workedSeconds": 1}),
        ("POST", "/api/v1/citation-builder/sessions/s1/tasks/t1/telemetry", {"uiState": "opened"}),
    ]
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read", "citation_queue:write"),
    )
    assert 403 not in (await _real_app_codes(routes))
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read"),
    )
    assert set(await _real_app_codes(routes)) == {403}


# --- the client selector's counts read ----------------------------------------------
async def test_session_clients_reports_per_client_counts(
    client: httpx.AsyncClient, sessions: FakeSessionsRepo, wire: Callable[[str], None],
) -> None:
    wire("owner")
    sessions.counts = [
        {"client_id": "cl-1", "client_name": "Acme Dental",
         "ready": 4, "verify_first": 2, "candidate_gaps": 7},
    ]
    resp = await client.get("/api/v1/citation-builder/session-clients")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row == {
        "clientId": "cl-1", "client": "Acme Dental",
        "readyForHuman": 4, "verifyFirst": 2, "candidateGaps": 7,
        # 0136: the selector also reports parked extension-lane web2 placements.
        "web2Placements": 0,
    }
