"""Earning a place on the whitelist: the API a spec has to pass through.

The whitelist starts empty and grows one dated verification at a time. These routes are
the only way in, and the rules they enforce live in the DATABASE - a CHECK for the earned
contract, triggers for immutability and host binding. The routes are a thin caller, so
these tests mostly assert that a refusal REACHES the operator intact rather than being
swallowed or restated.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import app.modules.citations.router  # noqa: F401  (populates sys.modules)
from app.core.auth import get_current_user
from app.modules.citations.repo import get_directory_specs_repo
from app.services.citation_liveness import LivenessProbe

from .test_router import _user

pytestmark = pytest.mark.unit

citations_router = sys.modules["app.modules.citations.router"]


def _spec_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "spec-1",
        "directory_id": "dir-1",
        "directory_name": "Ourbis",
        "spec": {
            "url": "https://www.ourbis.ca/en/add",
            "fields": [{"selector": "#name", "value_key": "business_name"}],
            "submit_selector": "#go",
            "success_indicator": "text=thank",
        },
        "active": False,
        "verified_at": None,
        "first_live_url": "",
        "success_count": 0,
        "failure_count": 0,
        "drift_detected_at": None,
        "drift_selector": "",
        "deactivated_reason": "",
    }
    row.update(over)
    return row


class FakeSpecsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.activated: list[str] = []
        self.raise_on_create: Exception | None = None
        self.raise_on_activate: Exception | None = None
        self.verify_returns: dict[str, Any] | None = _spec_row()
        self.first_live_returns: dict[str, Any] | None = _spec_row()

    def list_specs(self, *, directory_id: str | None = None) -> list[dict[str, Any]]:
        return list(self.rows.values())

    def get_spec(self, spec_id: str) -> dict[str, Any] | None:
        return self.rows.get(spec_id)

    def create_spec(self, *, directory_id: str, spec: dict[str, Any]) -> dict[str, Any] | None:
        if self.raise_on_create:
            raise self.raise_on_create
        row = _spec_row(directory_id=directory_id, spec=spec)
        self.created.append(spec)
        self.rows["spec-1"] = row
        return row

    def record_verification(self, spec_id: str, **kw: Any) -> dict[str, Any] | None:
        return self.verify_returns

    def record_first_live(self, spec_id: str, *, live_url: str) -> dict[str, Any] | None:
        return self.first_live_returns

    def activate(self, spec_id: str) -> dict[str, Any] | None:
        if self.raise_on_activate:
            raise self.raise_on_activate
        self.activated.append(spec_id)
        return _spec_row(active=True)

    def deactivate(self, spec_id: str, *, reason: str) -> dict[str, Any] | None:
        return _spec_row(deactivated_reason=reason)


@pytest.fixture
def specs(app: Any) -> FakeSpecsRepo:  # type: ignore[misc]
    fake = FakeSpecsRepo()
    app.dependency_overrides[get_directory_specs_repo] = lambda: fake
    return fake


@pytest.fixture
def wire(app: Any, specs: FakeSpecsRepo) -> Callable[[str], None]:  # type: ignore[misc]
    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.fixture(autouse=True)
def _stub_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citations_router, "is_public_url", lambda url: "127.0.0.1" not in url)
    monkeypatch.setattr(
        citations_router, "http_liveness_probe",
        lambda url: LivenessProbe(status_code=200, text="<p>Acme</p>", final_url=url),
    )


class _FakeDiag:
    message_primary = (
        "spec url host (169.254.169.254) must belong to the directory host (ourbis.ca) - "
        "a spec is not a free navigation target"
    )


class _FakePgError(Exception):
    diag = _FakeDiag()


# --------------------------------------------------------------------------- #
# The refusals must reach the operator intact.
# --------------------------------------------------------------------------- #
async def test_a_host_binding_refusal_is_a_409_carrying_the_databases_own_message(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None]
) -> None:
    """The SSRF guard lives in a trigger. Restating its rule in Python would mean a
    second copy that drifts; the database's message names the exact constraint, which is
    what an operator needs to fix the spec."""
    specs.raise_on_create = _FakePgError()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/specs",
        json={
            "directoryId": "dir-1", "url": "https://169.254.169.254/latest/",
            "fields": [], "submitSelector": "#go",
        },
    )
    assert resp.status_code == 409, resp.text
    assert "free navigation target" in resp.json()["error"]["message"]


async def test_an_unearned_activation_surfaces_the_check_constraint(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None]
) -> None:
    class _UnearnedError(Exception):
        class diag:  # noqa: N801
            message_primary = (
                'new row for relation "directory_specs" violates check constraint '
                '"directory_specs_active_is_earned"'
            )

    specs.raise_on_activate = _UnearnedError()
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/specs/spec-1/activate")
    assert resp.status_code == 409
    assert "active_is_earned" in resp.json()["error"]["message"]


async def test_a_non_psycopg_error_still_produces_a_usable_409(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None]
) -> None:
    """The handler reads `.diag` defensively - a second exception inside an error handler
    is the worst possible failure mode."""
    specs.raise_on_create = RuntimeError("connection reset")
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/specs",
        json={"directoryId": "dir-1", "url": "https://www.ourbis.ca/add",
              "fields": [], "submitSelector": "#go"},
    )
    assert resp.status_code == 409
    assert "connection reset" in resp.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# Half (b) is CHECKED, not asserted.
# --------------------------------------------------------------------------- #
async def test_a_first_live_url_that_does_not_answer_is_refused(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A spec must not earn the whitelist on a URL nobody could load. Half the point of
    the whitelist is that its evidence is real."""
    monkeypatch.setattr(
        citations_router, "http_liveness_probe",
        lambda url: LivenessProbe(status_code=404, text=""),
    )
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/specs/spec-1/first-live",
        json={"liveUrl": "https://www.ourbis.ca/en/biz/gone"},
    )
    assert resp.status_code == 409
    assert "did not answer" in resp.json()["error"]["message"]


async def test_a_private_first_live_url_is_refused_without_fetching(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _spy(url: str) -> LivenessProbe:
        calls.append(url)
        return LivenessProbe(status_code=200, text="x")

    monkeypatch.setattr(citations_router, "http_liveness_probe", _spy)
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/specs/spec-1/first-live",
        json={"liveUrl": "http://127.0.0.1:8000/x"},
    )
    assert resp.status_code == 422
    assert calls == []


async def test_a_second_verification_is_refused_because_it_is_write_once(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None]
) -> None:
    """A stale verification must not be quietly refreshed to make an old spec look
    recently checked - the date is the whole value."""
    specs.verify_returns = None
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/specs/spec-1/verify", json={})
    assert resp.status_code == 409
    assert "written once" in resp.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# The board says what is still missing.
# --------------------------------------------------------------------------- #
async def test_the_board_reports_what_each_spec_still_owes(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None]
) -> None:
    """A half-earned spec must read as half-earned, not merely 'not active'."""
    specs.rows = {
        "a": _spec_row(id="a"),                                     # neither half
        "b": _spec_row(id="b", verified_at="2026-08-29T00:00:00Z"),  # (a) only
        "c": _spec_row(id="c", verified_at="2026-08-29T00:00:00Z",
                       first_live_url="https://www.ourbis.ca/x", active=True),
        "d": _spec_row(id="d", drift_detected_at="2026-08-29T00:00:00Z",
                       drift_selector="#name"),
    }
    wire("owner")
    body = (await client.get("/api/v1/citation-builder/specs")).json()
    assert body["active"] == 1
    assert body["verifiedNotLive"] == 1
    assert body["unverified"] == 2
    assert body["drifted"] == 1
    by_id = {s["id"]: s for s in body["specs"]}
    assert by_id["a"]["blocking"] == [
        "needs a dated human DOM verification",
        "needs one submission that produced a public listing URL",
    ]
    assert by_id["b"]["blocking"] == ["needs one submission that produced a public listing URL"]
    assert by_id["c"]["blocking"] == []
    assert "#name" in by_id["d"]["blocking"][-1]
    assert "cannot be repaired in place" in by_id["d"]["blocking"][-1]


async def test_writing_a_spec_requires_a_lead(
    client: httpx.AsyncClient, specs: FakeSpecsRepo, wire: Callable[[str], None]
) -> None:
    wire("specialist")  # staff, not a lead
    resp = await client.post(
        "/api/v1/citation-builder/specs",
        json={"directoryId": "d", "url": "https://www.ourbis.ca/add",
              "fields": [], "submitSelector": "#go"},
    )
    assert resp.status_code == 403


async def test_activation_promotes_the_directory_to_route_b() -> None:
    """The route move is the point, not bookkeeping: gating the loader on route='B' while
    nothing could ever SET it produced a whitelist that could never have a member."""
    import inspect

    from app.modules.citations.repo import DirectorySpecsRepo

    src = inspect.getsource(DirectorySpecsRepo.activate)
    assert "update public.directories set route = 'B'" in src
    assert "route <> 'F'" in src, "a prohibited directory must never be promoted"
