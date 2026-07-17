"""On-page endpoints: the access gates + the live-write confirmation contract.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``, the analysis enqueuer is a recorder, the apply/revert cores
are stubbed, and the feature-grant lookup (the one DB read inside ``require_feature``)
is monkeypatched.

FOUR gates stack here, and each is pinned INDEPENDENTLY - a happy-path-only suite
would not notice one of them quietly vanishing:

1. auth       - swept app-wide by ``tests/test_route_auth_guard.py``; re-pinned here.
2. the ``on_page`` FEATURE grant - every route.
3. ``view_reports`` (reads) / ``run_audits`` (queueing an analysis).
4. **LEAD-only on every route that touches the client's LIVE SITE** - apply,
   apply-bulk, revert, dismiss, and the re-analyze re-arm. This mirrors the 0038 RLS
   policies + the ``onpage_guard_update`` trigger: the DB refuses a recommendation
   write that is not lead-attributed, so the app gate MUST agree or a caller would
   pass one and hit an opaque database error at the other.

Plus the contract that only exists because this module rewrites live client pages:
**no ``{"confirm": true}``, no apply** - 422, every time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.on_page.repo import get_on_page_repo
from app.modules.on_page.router import (
    get_analysis_enqueuer,
    get_fix_applier,
    get_fix_reverter,
)
from app.modules.on_page.tasks import ApplyOutcome

pytestmark = pytest.mark.unit

_REC = "11111111-1111-1111-1111-111111111111"
_REC_KEYS = {
    "id", "analysis", "client", "page", "issue", "issueCode", "impact", "status",
    "fixKind", "current", "proposed", "priority", "quickWin", "autoApplicable",
}

_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/on-page/recommendations"),
    ("GET", "/api/v1/on-page/analyses"),
    ("GET", "/api/v1/on-page/stats"),
    ("GET", "/api/v1/on-page/workspace"),
    ("GET", f"/api/v1/on-page/recommendations/{_REC}"),
]
# (method, path, body) for every mutating route.
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/on-page/analyze",
     {"clientId": "cl-1", "pageUrl": "https://np.example/p"}),
    ("POST", "/api/v1/on-page/analyze/OP-0001/re-analyze", {}),
    ("POST", f"/api/v1/on-page/recommendations/{_REC}/apply", {"confirm": True}),
    ("POST", "/api/v1/on-page/recommendations/apply-bulk", {"ids": [_REC], "confirm": True}),
    ("POST", f"/api/v1/on-page/recommendations/{_REC}/revert", {"confirm": True}),
    ("POST", f"/api/v1/on-page/recommendations/{_REC}/dismiss", {}),
]
# The routes that touch the LIVE SITE (or re-arm the analysis lifecycle) - lead-only.
_LEAD_ROUTES = [(m, p, b) for m, p, b in _WRITE_ROUTES if p != "/api/v1/on-page/analyze"]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope (invariant #5)."""
    return str(resp.json()["error"]["message"])


def _rec_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _REC,
        "analysis_code": "OP-0001",
        "analysis_status": "done",
        "client_id": "cl-secret",           # must NEVER reach the wire
        "client_name": "NorthPeak Dental",
        "page_url": "/services/implants",
        "issue": "Missing meta description",
        "issue_code": "meta_missing",
        "impact": "High",
        "status": "open",
        "fix_kind": "meta",
        "fix_payload": {"proposed_value": "A better description."},
        "current_value": "Old description",
        "priority_score": 66.67,
        "quick_win": True,
        "detail": {"length": 0, "min": 120},
        "applied_at": None,
        "wp_post_id": 4471,
    }
    row.update(over)
    return row


class FakeOnPageRepo:
    """In-memory stand-in for the RLS-scoped OnPageRepo."""

    def __init__(self) -> None:
        self.recs: list[dict[str, Any]] = []
        self.analyses: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.by_code: dict[str, dict[str, Any]] = {}
        self.stats_row: dict[str, Any] = {"analyzed": 0, "open": 0, "applied": 0}
        self.client_names: dict[str, str] = {}
        self.created: list[dict[str, Any]] = []
        self.rec_updates: list[tuple[str, dict[str, Any], str | None]] = []
        self.analysis_updates: list[tuple[str, dict[str, Any], str | None]] = []
        self.list_kwargs: dict[str, Any] | None = None

    def list_recommendations(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.recs)

    def list_analyses(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.analyses)

    def stats(self) -> dict[str, Any]:
        return dict(self.stats_row)

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        row = self.by_id.get(rec_id)
        return dict(row) if row else None

    def get_analysis_by_code(self, code: str) -> dict[str, Any] | None:
        row = self.by_code.get(code)
        return dict(row) if row else None

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def create_analysis(self, **kwargs: Any) -> dict[str, Any] | None:
        self.created.append(kwargs)
        return {"code": "OP-0009", **kwargs}

    def update_analysis(
        self, code: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        self.analysis_updates.append((code, dict(changes), expect_status))
        row = self.by_code.get(code)
        if row is None or (expect_status is not None and row.get("status") != expect_status):
            return None
        row.update(changes)
        return dict(row)

    def update_recommendation(
        self, rec_id: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        self.rec_updates.append((rec_id, dict(changes), expect_status))
        row = self.by_id.get(rec_id)
        if row is None or (expect_status is not None and row.get("status") != expect_status):
            return None
        row.update(changes)
        return dict(row)


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture
def repo() -> FakeOnPageRepo:
    r = FakeOnPageRepo()
    r.by_id[_REC] = _rec_row()
    r.by_code["OP-0001"] = {
        "id": "an-1", "code": "OP-0001", "status": "done",
        "client_id": "cl-1", "client_name": "NorthPeak Dental",
    }
    r.client_names["cl-1"] = "NorthPeak Dental"
    return r


@pytest.fixture
def enqueued(app: FastAPI) -> list[str]:
    """Recorder for the analysis enqueuer dep (never touches Celery's broker)."""
    calls: list[str] = []
    app.dependency_overrides[get_analysis_enqueuer] = lambda: calls.append
    return calls


@pytest.fixture
def applied(app: FastAPI) -> list[dict[str, Any]]:
    """Stub the apply/revert CORES (covered exhaustively in test_tasks) and record the
    arguments the router hands them - so the router's OWN job (gating, the confirm
    contract, the 409 mapping) is what is under test here.

    Installed through ``dependency_overrides``, which is also why those cores are
    injected rather than imported: no Celery, no WordPress, no broker.
    """
    calls: list[dict[str, Any]] = []

    def _apply(store: Any, rec_id: str, **kw: Any) -> ApplyOutcome:
        calls.append({"fn": "apply", "id": rec_id, **kw})
        return ApplyOutcome(rec_id, "applied", "applied to https://np.example")

    def _revert(store: Any, rec_id: str, **kw: Any) -> ApplyOutcome:
        calls.append({"fn": "revert", "id": rec_id, **kw})
        return ApplyOutcome(rec_id, "reverted", "reverted")

    app.dependency_overrides[get_fix_applier] = lambda: _apply
    app.dependency_overrides[get_fix_reverter] = lambda: _revert
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeOnPageRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an in-memory
    dict so the REAL ``feature_allows`` logic still runs, unstubbed.

    The SSRF guard is stubbed to a PASS by default: the real one calls
    ``socket.getaddrinfo``, so leaving it live would make this unit suite depend on DNS
    (it did, and it took two minutes). The test that pins the guard's behaviour
    re-patches it to deny.
    """
    app.dependency_overrides[get_on_page_repo] = lambda: repo
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))
    monkeypatch.setattr("app.core.security.validate_public_host", lambda value: value)

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["on_page"] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


# --------------------------------------------------------------------------- #
# 1. Gate 1 - authentication.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_rejects_an_unauthenticated_caller(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    assert (await client.request(method, path)).status_code == 401


# --------------------------------------------------------------------------- #
# 2. Gate 2 - the on_page FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_on_page_feature(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str],
    applied: list[Any], method: str, path: str
) -> None:
    # An owner holds every perm/role, so an ungranted feature is the ONLY thing that
    # can reject here - which is exactly what makes this a clean feature-gate test.
    wire("owner", feature=False)
    # Owner short-circuits require_feature, so use a manager (holds every perm these
    # routes need) to isolate the grant.
    wire("manager", feature=False)
    resp = await client.request(
        method, path, json={"clientId": "cl-1", "pageUrl": "https://np.example/p",
                            "confirm": True, "ids": [_REC]}
    )
    assert resp.status_code == 403, resp.text
    assert "on_page" in _message(resp)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str],
    applied: list[Any], method: str, path: str
) -> None:
    wire("owner", feature=False)  # owner short-circuits require_feature entirely
    resp = await client.request(
        method, path, json={"clientId": "cl-1", "pageUrl": "https://np.example/p",
                            "confirm": True, "ids": [_REC]}
    )
    assert resp.status_code != 403, resp.text


# --------------------------------------------------------------------------- #
# 3. Gate 3/4 - view_reports on reads, run_audits to analyze, LEAD to touch the site.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
@pytest.mark.parametrize("role", [*_LEADS, *_NON_LEAD_STAFF])
async def test_every_staff_role_may_read_the_board(
    client: httpx.AsyncClient, wire: Callable[..., None], role: str, method: str, path: str
) -> None:
    """Every staff role holds view_reports, so reading is open to all of them - the
    lead gate is about WRITING to a live site, not about seeing the work."""
    wire(role)
    assert (await client.request(method, path)).status_code == 200


@pytest.mark.parametrize(("method", "path", "body"), _LEAD_ROUTES)
@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_a_non_lead_may_never_touch_the_live_site(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str],
    applied: list[Any], role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    """The whole point of the lead gate. 0038's guard trigger refuses a
    non-lead-attributed recommendation write at the DATABASE, so the app must reject
    it cleanly here rather than let it hit an opaque Postgres error."""
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, resp.text
    assert "role" in _message(resp).lower()
    assert applied == []  # the core was never even reached


@pytest.mark.parametrize(("method", "path", "body"), _LEAD_ROUTES)
@pytest.mark.parametrize("role", _LEADS)
async def test_a_lead_may_touch_the_live_site(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str],
    applied: list[Any], role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    wire(role)
    assert (await client.request(method, path, json=body)).status_code != 403


async def test_analyze_requires_run_audits_not_lead(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str]
) -> None:
    """Queueing an analysis only READS the client's page - it changes nothing - so it
    is a run_audits action, which analysts and specialists hold."""
    for role in ("specialist", "analyst"):
        wire(role)
        resp = await client.post(
            "/api/v1/on-page/analyze",
            json={"clientId": "cl-1", "pageUrl": "https://np.example/p"},
        )
        assert resp.status_code == 202, resp.text

    wire("viewer")  # a viewer holds view_reports but NOT run_audits
    resp = await client.post(
        "/api/v1/on-page/analyze", json={"clientId": "cl-1", "pageUrl": "https://np.example/p"}
    )
    assert resp.status_code == 403
    assert "run_audits" in _message(resp)


# --------------------------------------------------------------------------- #
# 4. THE CONFIRMATION CONTRACT - no confirm, no live write.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "body", [{}, {"confirm": False}, {"force": True}, {"confirm": "yes"}, {"confirm": 1}]
)
async def test_apply_without_an_explicit_confirm_true_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any],
    body: dict[str, Any]
) -> None:
    """``confirm`` is ``Literal[True]``, so Pydantic rejects a missing/false/truthy-ish
    value BEFORE the route body runs. This endpoint REWRITES A LIVE CLIENT PAGE; it
    must never be reachable by an accidental POST with an empty body."""
    wire("owner")
    resp = await client.post(f"/api/v1/on-page/recommendations/{_REC}/apply", json=body)
    assert resp.status_code == 422, resp.text
    assert applied == []  # nothing reached the apply core


async def test_apply_bulk_without_confirm_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any]
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/on-page/recommendations/apply-bulk", json={"ids": [_REC]}
    )
    assert resp.status_code == 422
    assert applied == []


async def test_revert_without_confirm_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any]
) -> None:
    """A rollback is a live write too - it gets the same contract as the apply."""
    wire("owner")
    resp = await client.post(f"/api/v1/on-page/recommendations/{_REC}/revert", json={})
    assert resp.status_code == 422
    assert applied == []


async def test_apply_with_confirm_true_reaches_the_core(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any]
) -> None:
    wire("owner")
    resp = await client.post(
        f"/api/v1/on-page/recommendations/{_REC}/apply", json={"confirm": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "applied"
    assert applied[0]["id"] == _REC
    assert applied[0]["force"] is False
    assert applied[0]["actor_id"] == "00000000-0000-0000-0000-0000000000a1"


async def test_force_is_passed_through_only_when_asked_for(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any]
) -> None:
    wire("owner")
    await client.post(
        f"/api/v1/on-page/recommendations/{_REC}/apply", json={"confirm": True, "force": True}
    )
    assert applied[0]["force"] is True


# --------------------------------------------------------------------------- #
# 5. manual -> 422; drift -> 409.
# --------------------------------------------------------------------------- #
async def test_applying_a_manual_fix_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo,
    applied: list[Any]
) -> None:
    wire("owner")
    repo.by_id[_REC] = _rec_row(fix_kind="manual")
    resp = await client.post(
        f"/api/v1/on-page/recommendations/{_REC}/apply", json={"confirm": True}
    )
    assert resp.status_code == 422
    assert "manual" in _message(resp)
    assert applied == []  # never reached the core


def _outcome_is(app: FastAPI, dep: Any, state: str, reason: str) -> None:
    """Pin one apply/revert core to a fixed verdict, to test the router's mapping."""
    app.dependency_overrides[dep] = lambda: (
        lambda store, rec_id, **kw: ApplyOutcome(rec_id, state, reason)
    )


async def test_a_drifted_page_is_a_409_not_a_silent_overwrite(
    app: FastAPI, client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """The drift-guard's verdict must surface to the lead as a CONFLICT - the one
    outcome they have to see and decide about."""
    wire("owner")
    _outcome_is(app, get_fix_applier, "blocked", "would overwrite a manual edit")
    resp = await client.post(
        f"/api/v1/on-page/recommendations/{_REC}/apply", json={"confirm": True}
    )
    assert resp.status_code == 409
    assert "overwrite" in _message(resp)


async def test_a_drifted_revert_is_a_409_too(
    app: FastAPI, client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner")
    _outcome_is(app, get_fix_reverter, "blocked", "later manual edit")
    resp = await client.post(
        f"/api/v1/on-page/recommendations/{_REC}/revert", json={"confirm": True}
    )
    assert resp.status_code == 409


async def test_a_held_apply_is_reported_honestly_as_200_held(
    app: FastAPI, client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """A hold is not an error - the recommendation is still good, we just could not
    deliver it. The lead needs the reason, not a stack trace."""
    wire("owner")
    _outcome_is(app, get_fix_applier, "held", "SEO-plugin bridge missing")
    resp = await client.post(
        f"/api/v1/on-page/recommendations/{_REC}/apply", json={"confirm": True}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "held"
    assert "SEO-plugin bridge missing" in resp.json()["reason"]


async def test_applying_an_unknown_recommendation_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any]
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/on-page/recommendations/22222222-2222-2222-2222-222222222222/apply",
        json={"confirm": True},
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 6. Bulk: a manual/unknown id must not strand the rest of the batch.
# --------------------------------------------------------------------------- #
async def test_bulk_skips_manual_with_a_reason_and_still_applies_the_others(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo,
    applied: list[Any]
) -> None:
    wire("owner")
    manual, unknown = "33333333-3333-3333-3333-333333333333", "44444444-4444-4444-4444-444444444444"
    repo.by_id[manual] = _rec_row(id=manual, fix_kind="manual")

    resp = await client.post(
        "/api/v1/on-page/recommendations/apply-bulk",
        json={"ids": [_REC, manual, unknown], "confirm": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    states = {r["id"]: r["state"] for r in body["results"]}
    assert states[_REC] == "applied"
    assert states[manual] == "skipped"
    assert states[unknown] == "failed"   # one bad id does not 404 the whole request
    assert body["applied"] == 1
    assert body["skipped"] == 2
    # Only the appliable one ever reached the core.
    assert [c["id"] for c in applied] == [_REC]


async def test_bulk_rejects_an_empty_or_oversized_id_list(
    client: httpx.AsyncClient, wire: Callable[..., None], applied: list[Any]
) -> None:
    wire("owner")
    for ids in ([], [_REC] * 51):
        resp = await client.post(
            "/api/v1/on-page/recommendations/apply-bulk", json={"ids": ids, "confirm": True}
        )
        assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 7. The analyze route: SSRF pre-check + client validation.
# --------------------------------------------------------------------------- #
async def test_analyze_queues_the_worker_and_snapshots_the_client_name(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo,
    enqueued: list[str]
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/on-page/analyze",
        json={"clientId": "cl-1", "pageUrl": "https://np.example/p",
              "targetKeyword": "invisalign cost"},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"code": "OP-0009", "queued": True}
    assert enqueued == ["OP-0009"]
    assert repo.created[0]["client_name"] == "NorthPeak Dental"


async def test_analyze_refuses_an_internal_url_before_anything_is_queued(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo,
    enqueued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SSRF pre-check is a fail-fast for the operator (the worker re-validates
    every hop regardless). Nothing may be created or queued for a private target."""
    from app.core.security import PrivateAddressError

    def _deny(value: str) -> str:
        raise PrivateAddressError("private/local address not allowed: 169.254.169.254")

    wire("owner")  # installs the default pass-through guard...
    monkeypatch.setattr("app.core.security.validate_public_host", _deny)  # ...now deny
    resp = await client.post(
        "/api/v1/on-page/analyze",
        json={"clientId": "cl-1", "pageUrl": "http://169.254.169.254/latest/meta-data/"},
    )
    assert resp.status_code == 422
    assert enqueued == []
    assert repo.created == []


async def test_analyze_404s_an_unknown_client(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str]
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/on-page/analyze", json={"clientId": "nope", "pageUrl": "https://np.example/p"}
    )
    assert resp.status_code == 404
    assert enqueued == []


async def test_re_analyze_re_arms_a_settled_analysis_with_optimistic_concurrency(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo,
    enqueued: list[str]
) -> None:
    wire("owner")
    resp = await client.post("/api/v1/on-page/analyze/OP-0001/re-analyze")
    assert resp.status_code == 202, resp.text
    _code, changes, expect = repo.analysis_updates[0]
    assert changes["status"] == "queued"
    assert expect == "done"  # the optimistic guard: a racing re-run cannot double-arm
    assert enqueued == ["OP-0001"]


async def test_re_analyze_409s_while_an_analysis_is_still_running(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo,
    enqueued: list[str]
) -> None:
    wire("owner")
    repo.by_code["OP-0001"]["status"] = "analyzing"
    resp = await client.post("/api/v1/on-page/analyze/OP-0001/re-analyze")
    assert resp.status_code == 409
    assert enqueued == []


async def test_re_analyze_404s_an_unknown_code(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[str]
) -> None:
    wire("owner")
    assert (await client.post("/api/v1/on-page/analyze/OP-9999/re-analyze")).status_code == 404


# --------------------------------------------------------------------------- #
# 8. Dismiss.
# --------------------------------------------------------------------------- #
async def test_dismiss_uses_the_optimistic_guard_and_stamps_the_actor(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo
) -> None:
    wire("owner")
    resp = await client.post(f"/api/v1/on-page/recommendations/{_REC}/dismiss")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "dismissed"
    _id, changes, expect = repo.rec_updates[0]
    assert expect == "open"  # dismissing what a colleague just applied is a conflict
    assert changes["dismissed_by"] == "00000000-0000-0000-0000-0000000000a1"


async def test_dismissing_an_already_applied_recommendation_is_409(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo
) -> None:
    wire("owner")
    repo.by_id[_REC]["status"] = "applied"
    resp = await client.post(f"/api/v1/on-page/recommendations/{_REC}/dismiss")
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# 9. The wire contract: client_id NEVER leaks.
# --------------------------------------------------------------------------- #
async def test_the_recommendation_wire_shape_never_carries_client_id(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo
) -> None:
    wire("owner")
    repo.recs = [_rec_row()]
    body = (await client.get("/api/v1/on-page/recommendations")).json()
    assert set(body[0]) == _REC_KEYS
    assert "client_id" not in body[0]
    assert "cl-secret" not in str(body)      # not under ANY key
    assert body[0]["client"] == "NorthPeak Dental"  # the snapshot, not the id


async def test_the_detail_view_is_the_preview_diff(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """current vs proposed IS the diff a lead reads before authorising a live write."""
    wire("owner")
    body = (await client.get(f"/api/v1/on-page/recommendations/{_REC}")).json()
    assert body["current"] == "Old description"
    assert body["proposed"] == "A better description."
    assert body["detail"] == {"length": 0, "min": 120}
    assert body["analysisStatus"] == "done"
    assert "cl-secret" not in str(body)


async def test_the_analysis_wire_shape_never_carries_client_id(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo
) -> None:
    wire("owner")
    repo.analyses = [{
        "code": "OP-0001", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "page_url": "/p", "target_keyword": "kw", "status": "done",
        "score": {"total": 82.5}, "open_count": 3, "applied_count": 1, "error": None,
    }]
    body = (await client.get("/api/v1/on-page/analyses")).json()
    assert "cl-secret" not in str(body)
    assert body[0]["score"] == 82.5
    assert body[0]["openCount"] == 3


async def test_recommendation_filters_reach_the_repo(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeOnPageRepo
) -> None:
    wire("owner")
    await client.get(
        "/api/v1/on-page/recommendations"
        "?clientId=cl-1&analysis=OP-0001&status=open&impact=High&issueCode=meta_missing"
        "&quickWin=true&limit=5&offset=10"
    )
    assert repo.list_kwargs == {
        "client_id": "cl-1", "analysis_code": "OP-0001", "status": "open",
        "impact": "High", "issue_code": "meta_missing", "quick_win": True,
        "limit": 5, "offset": 10,
    }


async def test_an_unknown_status_or_impact_filter_is_422(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """The enums are server-authoritative: an unknown value must be rejected at the
    edge, not passed through to Postgres as an invalid enum cast."""
    wire("owner")
    assert (await client.get("/api/v1/on-page/recommendations?status=bogus")).status_code == 422
    assert (await client.get("/api/v1/on-page/recommendations?impact=Huge")).status_code == 422
