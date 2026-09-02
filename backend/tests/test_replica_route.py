"""Design Replication endpoints: the copyright gate, the SSRF gate, and the ledger
read - no DB, no broker, no browser. The repo and starter are fakes injected
through ``dependency_overrides``; ``record_activity`` is best-effort and patched
to a recorder; the SSRF guard is patched per-test (its real DNS resolution is
covered by its own suite)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.security import PrivateAddressError
from app.db.clients_repo import get_clients_repo
from app.db.job_runs_repo import get_job_runs_repo
from app.main import create_app
from app.routers.replica import get_replica_starter
from workers.tasks.replica import degrade_code, replica_idempotency_key, result_payload

pytestmark = pytest.mark.unit

_CLIENT_ID = "11111111-1111-1111-1111-111111111111"
_JOB_ID = "22222222-2222-2222-2222-222222222222"


def _user(role: str = "manager") -> Any:
    from app.core.auth import CurrentUser

    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000a1", email="op@aios.dev",
        role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=None,
    )


class _FakeClients:
    def get_client(self, client_id: str) -> dict[str, Any] | None:
        if client_id == _CLIENT_ID:
            return {"id": client_id, "name": "Alligator Pools"}
        return None


class _FakeRuns:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, dict[str, Any]] = {}

    def get_run_by_celery_task_id(self, task_id: str,
                                  *, job_name: str | None = None) -> dict[str, Any] | None:
        return self.rows.get(task_id)

    def get_run_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        return self.by_key.get(key)


@pytest.fixture
def runs() -> _FakeRuns:
    return _FakeRuns()


@pytest.fixture
def client(runs: _FakeRuns, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app: FastAPI = create_app()
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    app.dependency_overrides[get_clients_repo] = lambda: _FakeClients()
    app.dependency_overrides[get_job_runs_repo] = lambda: runs
    starts: list[dict[str, Any]] = []

    def _start(repo: Any, **kw: Any) -> str:
        starts.append(kw)
        return _JOB_ID

    app.dependency_overrides[get_replica_starter] = lambda: _start
    app.state.starts = starts  # type: ignore[attr-defined]
    monkeypatch.setattr("app.routers.replica.validate_public_host", lambda url: None)

    async def _no_activity(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr("app.routers.replica.record_activity", _no_activity)
    return TestClient(app)


def _body(**over: Any) -> dict[str, Any]:
    body = {"client_id": _CLIENT_ID, "url": "https://alligatorpools.com/",
            "owner_confirmed_source": True}
    body.update(over)
    return body


def _message(resp: httpx.Response) -> str:
    return str(resp.json()["error"]["message"])


class TestTheCopyrightGate:
    def test_without_the_assertion_nothing_is_enqueued(self, client: TestClient) -> None:
        resp = client.post("/api/v1/replica", json=_body(owner_confirmed_source=False))
        assert resp.status_code == 400
        assert "owns the source" in _message(resp)
        assert client.app.state.starts == []  # type: ignore[union-attr]

    def test_a_private_url_is_refused(self, client: TestClient,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        def _refuse(url: str) -> None:
            raise PrivateAddressError("resolves to 127.0.0.1")

        monkeypatch.setattr("app.routers.replica.validate_public_host", _refuse)
        resp = client.post("/api/v1/replica", json=_body())
        assert resp.status_code == 400
        assert "public address" in _message(resp)


class TestTheHappyPath:
    def test_accepted_and_enqueued_with_the_snapshot(self, client: TestClient) -> None:
        resp = client.post("/api/v1/replica", json=_body(title="Replica", slug="home-v1"))
        assert resp.status_code == 202
        assert resp.json() == {"job_id": _JOB_ID, "status": "queued"}
        (kw,) = client.app.state.starts  # type: ignore[union-attr]
        assert kw["client_id"] == _CLIENT_ID
        assert kw["client_name"] == "Alligator Pools"
        assert kw["slug"] == "home-v1"

    def test_an_unknown_client_is_a_404(self, client: TestClient) -> None:
        resp = client.post("/api/v1/replica", json=_body(
            client_id="99999999-9999-9999-9999-999999999999"))
        assert resp.status_code == 404


class TestTheStatusRead:
    def test_no_ledger_row_yet_reads_queued_not_404(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/replica/{_JOB_ID}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_a_terminal_row_maps_onto_the_contract_shape(self, client: TestClient,
                                                          runs: _FakeRuns) -> None:
        runs.rows[_JOB_ID] = {
            "status": "completed", "reason": None, "error_type": None,
            "error_message": None,
            "result": {"post_id": 157, "preview_url": "https://spotino.org/?page_id=157",
                       "sections": 8, "widgets": 97, "notes": ["navbar recognised"]},
        }
        got = client.get(f"/api/v1/replica/{_JOB_ID}").json()
        assert got == {"job_id": _JOB_ID, "status": "completed",
                       "preview_url": "https://spotino.org/?page_id=157",
                       "post_id": 157, "sections": 8, "widgets": 97,
                       "notes": ["navbar recognised"],
                       # A run that predates the design capture carries no profile, and
                       # null is the honest answer: the caller must fall back to
                       # measuring the site itself rather than build on a guess.
                       "design_profile": None}

    def test_the_measured_design_reaches_the_caller(self, client: TestClient,
                                                    runs: _FakeRuns) -> None:
        """QA 20: the replicated design is what the content flow builds pages ON.

        The replicator always measured a richer design system than the content
        analyzer does and then discarded it. Carrying it out on the job result is what
        lets "replicate a design, then generate N pages on it" be one flow instead of
        two Playwright captures of the same URL.
        """
        profile = {"palette": {"primary": "#0f172a", "accent": "#e11d48"},
                   "layout": {"container_width": "1140px"}}
        runs.rows[_JOB_ID] = {
            "status": "completed", "reason": None, "error_type": None,
            "error_message": None,
            "result": {"post_id": 157, "preview_url": "u", "sections": 8, "widgets": 97,
                       "notes": [], "design_profile": profile},
        }
        got = client.get(f"/api/v1/replica/{_JOB_ID}").json()
        assert got["design_profile"] == profile

    def test_a_degraded_rows_reason_reaches_notes(self, client: TestClient,
                                                  runs: _FakeRuns) -> None:
        runs.rows[_JOB_ID] = {
            "status": "degraded", "reason": "capture degraded: page unreachable",
            "error_type": None, "error_message": None, "result": {"notes": []},
        }
        got = client.get(f"/api/v1/replica/{_JOB_ID}").json()
        assert got["status"] == "degraded"
        assert "capture degraded: page unreachable" in got["notes"]

    def test_a_handle_that_is_not_a_uuid_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/replica/not-a-uuid").status_code == 404


class TestTheWorkerCore:
    def test_the_idempotency_key_is_the_work_not_the_run(self) -> None:
        a = replica_idempotency_key("c1", "https://x.example/", "home")
        assert a == replica_idempotency_key("c1", "https://x.example/", "home")
        assert a != replica_idempotency_key("c1", "https://x.example/", "home-v2")
        assert a != replica_idempotency_key("c2", "https://x.example/", "home")

    @pytest.mark.parametrize(("last_note", "code"), [
        ("capture degraded: no desktop viewport was measured", "capture_degraded"),
        ("layout degraded: no sections were inferred; nothing to publish", "layout_degraded"),
        ("refused by the oracle: unknown key", "oracle_refused"),
        ("publish failed: HTTPStatusError: 500", "wp_publish_failed"),
        ("something else entirely", "replica_degraded"),
    ])
    def test_the_stage_that_stopped_names_the_reason_code(self, last_note: str,
                                                          code: str) -> None:
        assert degrade_code([last_note]) == code

    def test_the_result_payload_records_the_assertion(self) -> None:
        class R:
            post_id = 157
            preview_url = "https://spotino.org/?page_id=157"
            sections = 8
            widgets = 97
            notes = ["ok"]

        payload = result_payload(R(), url="https://alligatorpools.com/")
        assert payload["owner_confirmed_source"] is True
        assert payload["post_id"] == 157


class TestARunCanBeRepeated:
    """The starter itself, not the stubbed one the route tests inject.

    THE BUG THIS PINS. `get_replica_starter` returned the stored handle for ANY
    prior run carrying a celery id, without ever looking at how that run ENDED. So
    the first replication of a (client, url, slug) was the only one that could ever
    happen: a run that degraded on a truncated capture, or was `blocked` because
    WordPress was not connected yet, answered every later POST with its own dead
    handle. The operator connected the site, clicked "Replicate design" again, got a
    202, and watched the same terminal row it already had. Nothing was enqueued and
    nothing said so.
    """

    @staticmethod
    def _starter(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[dict[str, Any]]]:
        calls: list[dict[str, Any]] = []

        def _enqueue(task: str, *args: Any, **kw: Any) -> str:
            calls.append({"task": task, "args": args, **kw})
            return f"new-handle-{len(calls)}"

        monkeypatch.setattr("app.jobs.celery_task.enqueue", _enqueue)
        return get_replica_starter(), calls

    def _run(self, repo: _FakeRuns, starter: Any) -> str:
        return str(starter(repo, client_id=_CLIENT_ID, url="https://x.example/",
                           title=None, slug=None, client_name="X"))

    def test_a_run_still_in_flight_collapses_to_the_existing_handle(
        self, runs: _FakeRuns, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What idempotency is actually FOR: a double-click is one capture."""
        starter, calls = self._starter(monkeypatch)
        key = replica_idempotency_key(_CLIENT_ID, "https://x.example/", None)
        runs.by_key[key] = {"celery_task_id": "in-flight", "status": "running"}
        assert self._run(runs, starter) == "in-flight"
        assert calls == [], "an in-flight rebuild must not be enqueued twice"

    @pytest.mark.parametrize("status", ["degraded", "blocked", "failed", "completed",
                                        "cancelled"])
    def test_a_terminal_run_does_not_block_a_fresh_one(
        self, runs: _FakeRuns, monkeypatch: pytest.MonkeyPatch, status: str
    ) -> None:
        starter, calls = self._starter(monkeypatch)
        key = replica_idempotency_key(_CLIENT_ID, "https://x.example/", None)
        runs.by_key[key] = {"celery_task_id": "old-dead-handle", "status": status}
        handle = self._run(runs, starter)
        assert handle != "old-dead-handle", (
            f"a {status} run answered the new request with its own dead handle"
        )
        assert len(calls) == 1, "the rebuild must actually be enqueued"

    def test_the_fresh_run_gets_a_key_the_claim_will_accept(
        self, runs: _FakeRuns, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A new HANDLE alone is not enough and this is the half that is easy to miss.

        `job_runs` holds a unique index on `idempotency_key` across the whole table,
        terminal rows included. Re-enqueueing under the spent key would be claimed
        with created=False, the runner would decline the work, and the new handle
        would map to no row - "queued" forever, which is worse than the bug it
        replaced. So the generation must advance past every terminal row.
        """
        starter, calls = self._starter(monkeypatch)
        url = "https://x.example/"
        for generation in (1, 2, 3):
            runs.by_key[replica_idempotency_key(_CLIENT_ID, url, None, generation)] = {
                "celery_task_id": f"dead-{generation}", "status": "degraded",
            }
        self._run(runs, starter)
        assert calls[0]["generation"] == 4
        fresh = replica_idempotency_key(_CLIENT_ID, url, None, 4)
        assert fresh not in runs.by_key, "generation 4 must be an unspent key"

    def test_generation_one_is_byte_identical_to_the_original_key(self) -> None:
        """Every run already in the ledger has to keep matching its own key."""
        base = replica_idempotency_key(_CLIENT_ID, "https://x.example/", "home")
        assert base == replica_idempotency_key(_CLIENT_ID, "https://x.example/", "home", 1)
        assert base == f"replica.publish:{_CLIENT_ID}:https://x.example/:home"
        assert replica_idempotency_key(_CLIENT_ID, "https://x.example/", "home", 2) != base
