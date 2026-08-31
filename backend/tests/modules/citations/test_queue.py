"""The human work queue: the surface that replaces a desktop script.

Route C - a human working a directory by hand - is ~200 of the 226 catalogue rows and
56% of the loaded cost per live citation. The two levers on that cost are the aggregator
price and MINUTES PER ITEM, so the queue exists to make the minutes smaller and, for the
first time, to measure them.

The load-bearing test in this file is `test_completion_is_refused_when_the_page_does_not
_carry_the_business`. A queue whose completion is an assertion is a queue that manufactures
live citations out of operator optimism.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import app.modules.citations.router  # noqa: F401  (populates sys.modules)
from app.core.auth import get_current_user
from app.modules.citations.operator_auth import require_operator_lead, resolve_operator
from app.modules.citations.repo import CitationQueueRepo, get_citation_queue_repo
from app.services.citation_liveness import LivenessProbe

from .test_router import _user  # the shared CurrentUser factory

pytestmark = pytest.mark.unit

# `app.modules.citations.router` is AMBIGUOUS: the package's __init__ re-exports an
# APIRouter under that exact name, so both the dotted monkeypatch string and
# `import ... as` resolve to the router OBJECT rather than the module. sys.modules is
# the only unambiguous handle on the module itself.
citations_router = sys.modules["app.modules.citations.router"]

_NAME = "Acme Dental"
_PHONE = "555-0100"


def _held_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "cit-1",
        "client_id": "cl-secret",
        "client_name": _NAME,
        "directory": "Brownbook",
        "directory_name": "Brownbook",
        "directory_url": "brownbook.net",
        "directory_add_url": "https://brownbook.net/add",
        "directory_route": "C",
        "directory_tos_source_url": "",
        "submit_status": "ready_for_human",
        "blocked_reason": "captcha_wall",
        "claim_expires_at": None,
        "human_attempts": 1,
        "worked_seconds": 0,
        "bp_business_name": _NAME,
        "bp_address_line1": "123 Main St",
        "bp_address_line2": "",
        "bp_city": "Bellevue",
        "bp_region": "WA",
        "bp_postal_code": "98004",
        "bp_phone": _PHONE,
        "bp_website_url": "https://acme.example",
        "bp_email": "",
        "bp_description": "",
        "bp_categories": ["dentist"],
    }
    row.update(over)
    return row


class FakeQueueRepo:
    """In-memory stand-in for CitationQueueRepo."""

    def __init__(self) -> None:
        self.held: dict[str, dict[str, Any]] = {}
        self.available: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self.blocked: list[dict[str, Any]] = []
        self.released: list[str] = []
        self.heartbeats: list[tuple[str, int]] = []
        self.stats: dict[str, Any] = {"waiting": 0, "in_progress": 0, "median_seconds": None}
        self.claim_valid = True

    def claim_next(self, *, lease_seconds: int, client_id: str | None = None) -> dict[str, Any] | None:
        if not self.available:
            return None
        row = self.available.pop(0)
        self.held[str(row["id"])] = row
        return row

    def held_item(self, citation_id: str) -> dict[str, Any] | None:
        return self.held.get(citation_id) if self.claim_valid else None

    def extend_claim(self, citation_id: str, *, lease_seconds: int, worked_seconds: int) -> bool:
        if not self.claim_valid or citation_id not in self.held:
            return False
        self.heartbeats.append((citation_id, worked_seconds))
        return True

    def release_claim(self, citation_id: str, *, worked_seconds: int = 0) -> bool:
        self.released.append(citation_id)
        return True

    def complete_item(self, citation_id: str, **kw: Any) -> dict[str, Any] | None:
        self.completed.append({"id": citation_id, **kw})
        return {**self.held.get(citation_id, {}), **kw}

    def block_item(self, citation_id: str, **kw: Any) -> dict[str, Any] | None:
        self.blocked.append({"id": citation_id, **kw})
        return self.held.get(citation_id)

    def queue_stats(self) -> dict[str, Any]:
        return self.stats


@pytest.fixture
def queue(app: Any) -> FakeQueueRepo:  # type: ignore[misc]
    fake = FakeQueueRepo()
    app.dependency_overrides[get_citation_queue_repo] = lambda: fake
    return fake


@pytest.fixture
def wire(app: Any, queue: FakeQueueRepo) -> Callable[[str], None]:  # type: ignore[misc]
    """Authenticate as a role.

    The queue routes take `resolve_operator`, not `get_current_user` — they accept a
    dashboard bearer token OR the extension's `X-Operator-Token`, and resolve both to the
    same CurrentUser. `resolve_operator` CALLS `get_current_user` as a plain function
    rather than depending on it (it must run only when no operator header is present), so
    a `get_current_user` override does not reach these routes. Override the dependency
    the route actually declares."""

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[resolve_operator] = lambda: _user(role)
        app.dependency_overrides[require_operator_lead] = lambda: _user(role)

    return _as


def _serving(html: str, status: int = 200) -> Callable[[str], LivenessProbe]:
    return lambda _url: LivenessProbe(status_code=status, text=html, final_url=_url)


@pytest.fixture(autouse=True)
def _stub_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file may touch the network, and `is_public_url` does real DNS.

    Patched via the MODULE OBJECT, not the dotted string: `app.modules.citations.router`
    is ambiguous - the package re-exports an `APIRouter` under that same name in its
    __init__, so the string form resolves to the router object and getattr fails."""
    monkeypatch.setattr(citations_router, "is_public_url", lambda url: "127.0.0.1" not in url)
    monkeypatch.setattr(
        citations_router, "http_liveness_probe", _serving(f"<p>{_NAME}</p><p>{_PHONE}</p>")
    )


# --------------------------------------------------------------------------- #
# THE HONESTY GATE.
# --------------------------------------------------------------------------- #
async def test_completion_is_refused_when_the_page_does_not_carry_the_business(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the queue's exit.

    An operator supplies a URL; we FETCH it and look for the business. If it is not
    there the completion is refused and the item stays claimed. The commonest cause is
    not dishonesty - it is a directory that accepted the submission into a moderation
    queue and has not published yet - and 'not live yet' is the honest answer."""
    monkeypatch.setattr(
        citations_router, "http_liveness_probe", _serving("<p>Find local dentists near you</p>")
    )
    queue.held["cit-1"] = _held_row()
    wire("owner")

    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/complete",
        json={"liveUrl": "https://brownbook.net/biz/acme", "workedSeconds": 240},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is False
    assert "business name" in body["reason"]
    assert queue.completed == [], "a refused completion must not write anything"


async def test_a_verified_listing_completes_and_is_marked_live(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/complete",
        json={"liveUrl": "https://brownbook.net/biz/acme", "workedSeconds": 240, "note": "easy"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert body["submitStatus"] == "live"
    assert set(body["matchedFields"]) == {"business_name", "phone"}
    assert len(queue.completed) == 1
    written = queue.completed[0]
    assert written["submit_status"] == "live"
    assert written["live_url"] == "https://brownbook.net/biz/acme"
    assert written["worked_seconds"] == 240
    assert written["note"] == "easy"


async def test_a_private_url_is_refused_without_fetching(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSRF: the URL is operator-supplied and the fetch runs server-side."""
    calls: list[str] = []
    def _spy(url: str) -> LivenessProbe:
        calls.append(url)
        return LivenessProbe(status_code=200, text=_NAME)

    monkeypatch.setattr(citations_router, "http_liveness_probe", _spy)
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/complete",
        json={"liveUrl": "http://127.0.0.1:8000/admin"},
    )
    assert resp.json()["accepted"] is False
    assert calls == [], "a loopback URL must never be fetched"


# --------------------------------------------------------------------------- #
# The lease.
# --------------------------------------------------------------------------- #
async def test_an_expired_claim_cannot_complete_or_block(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    """A stale browser tab must not keep working an item somebody else now owns."""
    queue.held["cit-1"] = _held_row()
    queue.claim_valid = False
    wire("owner")
    for path, body in (
        ("complete", {"liveUrl": "https://x.example/a"}),
        ("blocked", {"reason": "captcha_wall"}),
    ):
        resp = await client.post(f"/api/v1/citation-builder/queue/cit-1/{path}", json=body)
        assert resp.status_code == 404, f"{path}: {resp.text}"


async def test_a_lapsed_heartbeat_is_a_409_not_a_silent_success(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    queue.claim_valid = False
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/heartbeat", json={"workedSeconds": 60}
    )
    assert resp.status_code == 409
    assert "claim it again" in resp.json()["error"]["message"]


async def test_claiming_an_empty_queue_returns_null_not_an_error(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/queue/claim", json={})
    assert resp.status_code == 200
    assert resp.json() is None


# --------------------------------------------------------------------------- #
# Blocking is a first-class outcome.
# --------------------------------------------------------------------------- #
async def test_blocking_records_a_machine_readable_reason(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    """A queue whose only exit is success trains people to fake success."""
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/blocked",
        json={"reason": "paid_only", "workedSeconds": 90},
    )
    assert resp.status_code == 204, resp.text
    assert queue.blocked[0]["reason"] == "paid_only"
    assert queue.blocked[0]["detail"] == "listing requires payment"
    assert queue.blocked[0]["worked_seconds"] == 90


async def test_an_unknown_block_reason_is_rejected(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    """The vocabulary is closed so the board can answer 'which directories waste our
    time?'. Free text would make that unanswerable."""
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/blocked", json={"reason": "i_gave_up"}
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# The item an operator actually sees.
# --------------------------------------------------------------------------- #
async def test_the_item_carries_every_prefilled_field_and_drops_the_empty_ones(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    """Pre-computing the values IS the queue. Blank boxes are the friction it removes."""
    queue.held["cit-1"] = _held_row()
    wire("owner")
    resp = await client.get("/api/v1/citation-builder/queue/cit-1")
    assert resp.status_code == 200, resp.text
    fields = {f["key"]: f["value"] for f in resp.json()["fields"]}
    assert fields["business_name"] == _NAME
    assert fields["phone"] == _PHONE
    assert fields["categories"] == "dentist"
    # address_line2, email and description were empty on the profile.
    assert "address_line2" not in fields
    assert "email" not in fields


async def test_a_route_f_item_carries_a_do_not_submit_banner(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    """This should be unreachable - route F can never be queued - so if it is ever seen,
    say so loudly rather than letting an operator submit against terms that forbid it
    under the client's own identity."""
    queue.held["cit-1"] = _held_row(
        directory_route="F", directory_tos_source_url="https://terms.yelp.com/tos/en_us/"
    )
    wire("owner")
    resp = await client.get("/api/v1/citation-builder/queue/cit-1")
    assert "Do not submit" in resp.json()["prohibitedWarning"]


async def test_the_board_reports_an_unmeasured_median_as_null_not_zero(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    """Zero would make the loaded-cost model look free. An unmeasured number must read
    as unmeasured."""
    queue.stats = {"waiting": 12, "in_progress": 2, "median_seconds": None}
    wire("owner")
    body = (await client.get("/api/v1/citation-builder/queue")).json()
    assert body["waiting"] == 12 and body["inProgress"] == 2
    assert body["medianSeconds"] is None


async def test_the_board_reports_a_measured_median(
    client: httpx.AsyncClient, queue: FakeQueueRepo, wire: Callable[[str], None]
) -> None:
    queue.stats = {"waiting": 3, "in_progress": 1, "median_seconds": 268}
    wire("owner")
    assert (await client.get("/api/v1/citation-builder/queue")).json()["medianSeconds"] == 268


def test_the_queue_repo_never_uses_the_privileged_pool() -> None:
    """Every queue method runs on `rls_connection`. That is the tenant boundary: an
    operator must only ever claim or complete an item for a client they can already see,
    and the cheapest way to guarantee it is to let Postgres decide."""
    import inspect

    src = inspect.getsource(CitationQueueRepo)
    assert "privileged_connection" not in src
    assert src.count("rls_connection") >= 7


def test_every_queue_route_is_registered_on_the_real_app() -> None:
    """A route that does not mount is a feature that silently does not exist.

    The queue's own tests exercise these paths through the app, so they are covered - but
    this asserts the surface explicitly, so a future refactor that drops the router from
    MODULE_ROUTERS fails here with a clear message rather than as a puzzling 404 in nine
    unrelated tests."""
    from app.main import create_app

    # Enumerate via the OpenAPI spec, the same way tests/test_route_auth_guard.py does.
    # `app.routes` is NOT the route table here: this FastAPI version keeps included
    # routers as `_IncludedRouter` wrappers rather than flattening their APIRoutes onto
    # the app, so walking `app.routes` finds two entries and reports every mounted route
    # as missing.
    paths = set(create_app().openapi()["paths"])
    expected = {
        "/api/v1/citation-builder/queue",
        "/api/v1/citation-builder/queue/claim",
        "/api/v1/citation-builder/queue/{citation_id}",
        "/api/v1/citation-builder/queue/{citation_id}/heartbeat",
        "/api/v1/citation-builder/queue/{citation_id}/release",
        "/api/v1/citation-builder/queue/{citation_id}/complete",
        "/api/v1/citation-builder/queue/{citation_id}/blocked",
        "/api/v1/citation-builder/recheck",
    }
    assert expected <= paths, f"missing: {sorted(expected - paths)}"


async def test_a_non_lead_is_refused_the_queue_write_endpoints(
    app: Any, client: httpx.AsyncClient, queue: FakeQueueRepo
) -> None:
    """The role gate, exercised for REAL.

    The `wire` fixture stubs `require_operator_lead` so the happy-path tests do not have
    to model roles — which would leave the gate itself untested. Here only
    `resolve_operator` is overridden, so `require_operator_lead` runs its actual check.

    An operator token INHERITS its holder's role and grants nothing extra: a specialist
    who pairs an extension is refused the write endpoints for exactly the same reason
    their dashboard session would be."""
    app.dependency_overrides[resolve_operator] = lambda: _user("specialist")
    queue.held["cit-1"] = _held_row()

    for path, body in (
        ("claim", {}),
        ("cit-1/complete", {"liveUrl": "https://dir.example/a"}),
        ("cit-1/blocked", {"reason": "captcha_wall"}),
    ):
        resp = await client.post(f"/api/v1/citation-builder/queue/{path}", json=body)
        assert resp.status_code == 403, f"{path} allowed a specialist: {resp.text}"
    assert queue.completed == [] and queue.blocked == []


async def test_a_lead_may_use_the_same_write_endpoints(
    app: Any, client: httpx.AsyncClient, queue: FakeQueueRepo
) -> None:
    """The other half: the gate must not be refusing everyone."""
    app.dependency_overrides[resolve_operator] = lambda: _user("manager")
    queue.held["cit-1"] = _held_row()
    resp = await client.post(
        "/api/v1/citation-builder/queue/cit-1/blocked", json={"reason": "captcha_wall"}
    )
    assert resp.status_code == 204, resp.text
