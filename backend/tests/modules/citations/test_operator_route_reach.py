"""Does the extension's credential actually REACH the queue?

Every other test in this module overrides `get_citation_queue_repo`, `resolve_operator`
and `require_operator_lead` — which is convenient and, it turned out, blinding. The queue
routes declare the repo dependency FIRST, and it used to resolve `get_current_user`; so
an operator token was rejected by bearer auth before `resolve_operator` was ever
consulted, `verify_operator_token` was called zero times, and the shipped extension could
not reach a single endpoint.

226 tests were green while that was true, because the fixtures replaced the exact
dependency that was blocking it.

So this file overrides NOTHING in the dependency graph. It drives the real app and asserts
on whether the credential is consulted at all.
"""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

import app.modules.citations.operator_auth as operator_auth
from app.main import create_app
from app.services.operator_tokens import OperatorPrincipal

pytestmark = pytest.mark.unit

QUEUE_ROUTES = [
    ("GET", "/api/v1/citation-builder/queue"),
    ("POST", "/api/v1/citation-builder/queue/claim"),
    ("GET", "/api/v1/citation-builder/queue/cit-1"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/heartbeat"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/release"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/complete"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/blocked"),
]


async def _hit(app: object, headers: dict[str, str]) -> list[int]:
    codes: list[int] = []
    async with LifespanManager(app):  # type: ignore[arg-type]
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            for method, path in QUEUE_ROUTES:
                r = await c.request(method, path, headers=headers, json={})
                codes.append(r.status_code)
    return codes


async def test_an_operator_token_is_actually_consulted_on_every_queue_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE regression. If the credential is never looked at, the extension is dead — and
    that is exactly the state this module shipped in until the queue repo stopped
    depending on `get_current_user`."""
    seen: list[str] = []

    def _verify(raw: str) -> OperatorPrincipal:
        seen.append(raw)
        return OperatorPrincipal(
            token_id="t1", user_id="u1",
            scopes=frozenset({"citation_queue"}), expires_at=None, issued_at=None,
        )

    monkeypatch.setattr(operator_auth, "verify_operator_token", _verify)
    await _hit(create_app(), {"X-Operator-Token": "aop_abc_secret"})

    assert len(seen) == len(QUEUE_ROUTES), (
        f"the operator token was consulted {len(seen)} times across "
        f"{len(QUEUE_ROUTES)} queue routes - the extension cannot reach the ones it missed"
    )


async def test_no_credential_at_all_is_still_401_on_every_queue_route() -> None:
    """Widening the routes to accept a second credential must not open them. This is the
    property `tests/test_route_auth_guard.py` sweeps for, asserted here directly because
    these routes no longer take the dependency that sweep understands."""
    codes = await _hit(create_app(), {})
    assert set(codes) == {401}, f"expected every queue route to 401 unauthenticated, got {codes}"


async def test_a_rejected_operator_token_does_not_fall_through_to_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad operator token must fail as a bad operator token. Falling through to bearer
    auth would turn a revoked extension into a confusing 401 about a header it never
    sent — and, worse, would mean the operator path could be bypassed by sending garbage."""
    monkeypatch.setattr(operator_auth, "verify_operator_token", lambda raw: None)
    codes = await _hit(create_app(), {"X-Operator-Token": "aop_bad_token"})
    assert set(codes) == {401}, codes


async def test_a_token_without_the_queue_scope_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope is what narrows this credential to the queue. A token that verifies but
    carries only `citation_credential` must not reach these routes."""
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: OperatorPrincipal(
            token_id="t1", user_id="u1",
            scopes=frozenset({"citation_credential"}), expires_at=None, issued_at=None,
        ),
    )
    codes = await _hit(create_app(), {"X-Operator-Token": "aop_abc_secret"})
    assert set(codes) == {401}, codes


_READ_ROUTES = [
    ("GET", "/api/v1/citation-builder/queue"),
    ("GET", "/api/v1/citation-builder/queue/cit-1"),
]
_WRITE_ROUTES = [
    ("POST", "/api/v1/citation-builder/queue/claim"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/heartbeat"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/release"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/complete"),
    ("POST", "/api/v1/citation-builder/queue/cit-1/blocked"),
]


def _principal_with(*scopes: str) -> OperatorPrincipal:
    return OperatorPrincipal(
        token_id="t1", user_id="u1",
        scopes=frozenset(scopes), expires_at=None, issued_at=None,
    )


async def _codes_for(routes: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch) -> list[int]:
    app = create_app()
    codes: list[int] = []
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            for method, path in routes:
                r = await c.request(method, path, headers={"X-Operator-Token": "aop_x_y"}, json={})
                codes.append(r.status_code)
    return codes


async def test_a_read_only_token_is_refused_every_queue_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3 applied the Phase-2 scope split: `citation_queue:read` opens the board
    and the item GET, and NOTHING else. The scope refusal is a deterministic 401 -
    it happens before any epoch/DB work."""
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read"),
    )
    codes = await _codes_for(_WRITE_ROUTES, monkeypatch)
    assert set(codes) == {401}, codes
    # The reads are NOT scope-refused (they may fail later on env, never on 401).
    read_codes = await _codes_for(_READ_ROUTES, monkeypatch)
    assert 401 not in read_codes, read_codes


async def test_a_write_only_token_is_refused_the_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One-way granularity (Phase 2's mapping): `:write` never implies `:read`."""
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:write"),
    )
    codes = await _codes_for(_READ_ROUTES, monkeypatch)
    assert set(codes) == {401}, codes
    write_codes = await _codes_for(_WRITE_ROUTES, monkeypatch)
    assert 401 not in write_codes, write_codes


async def test_the_legacy_umbrella_scope_still_satisfies_both_halves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-split `citation_queue` token keeps working until it ages out - no forced
    re-pair (Phase 2's one-way mapping, exercised through the real routes)."""
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue"),
    )
    codes = await _codes_for(_READ_ROUTES + _WRITE_ROUTES, monkeypatch)
    assert 401 not in codes, codes


async def test_business_profiles_requires_the_client_profile_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint that serves canonical NAP values to the extension is gated on
    `client_profile:read` - a queue-only token must not read client identity data."""
    route = [("GET", "/api/v1/citation-builder/business-profiles")]
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("citation_queue:read", "citation_queue:write"),
    )
    assert (await _codes_for(route, monkeypatch)) == [401]
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("client_profile:read"),
    )
    assert 401 not in (await _codes_for(route, monkeypatch))


# --------------------------------------------------------------------------- #
# Phase-7 evidence door + session routes: the same regression class, re-checked.
# The placement complete route once bound its repo to bearer-only
# `get_current_user`, which 401'd the extension before the route's own hybrid
# guard was consulted — dead on arrival, with unit tests green because they
# overrode the exact dependency that was blocking it.
# --------------------------------------------------------------------------- #
_PLACEMENT_ROUTE = ("POST", "/api/v1/offpage/web2/placements/w2-1/complete")
_SESSION_ROUTES = [
    ("GET", "/api/v1/citation-builder/sessions"),
    ("POST", "/api/v1/citation-builder/sessions"),
]


async def _hit_one(
    method: str, path: str, headers: dict[str, str], body: dict[str, object]
) -> int:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            r = await c.request(method, path, headers=headers, json=body)
            return r.status_code


async def test_the_placement_complete_door_actually_consults_the_operator_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `web2_queue:write` extension token must REACH the Phase-7 evidence door —
    the credential is consulted and the refusal (if any) is not bearer auth's 401."""
    seen: list[str] = []

    def _verify(raw: str) -> OperatorPrincipal:
        seen.append(raw)
        return _principal_with("web2_queue:write")

    monkeypatch.setattr(operator_auth, "verify_operator_token", _verify)
    method, path = _PLACEMENT_ROUTE
    code = await _hit_one(
        method, path, {"X-Operator-Token": "aop_abc_secret"},
        {"url": "https://medium.com/@op/post"},
    )
    assert seen, "the operator token was never consulted - the placement door is unreachable"
    assert code != 401, f"the extension credential was refused as unauthenticated: {code}"


async def test_the_placement_complete_door_is_401_without_any_credential() -> None:
    method, path = _PLACEMENT_ROUTE
    assert await _hit_one(method, path, {}, {"url": "https://medium.com/x"}) == 401


async def test_a_web2_read_scope_cannot_reach_the_placement_complete_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The door is a mutation of a client's ledger: `web2_queue:read` must be refused
    deterministically, before any epoch/DB work."""
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: _principal_with("web2_queue:read"),
    )
    method, path = _PLACEMENT_ROUTE
    assert await _hit_one(method, path, {"X-Operator-Token": "aop_x_y"}, {"url": "https://m.com/x"}) == 401


async def test_the_session_routes_consult_the_operator_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kind-generalized session surface (0136) must be reachable with a pure
    web2 token — its repos are bound to the floor objects, never to bearer auth."""
    seen: list[str] = []

    def _verify(raw: str) -> OperatorPrincipal:
        seen.append(raw)
        return _principal_with("web2_queue:read", "web2_queue:write")

    monkeypatch.setattr(operator_auth, "verify_operator_token", _verify)
    codes: list[int] = []
    for method, path in _SESSION_ROUTES:
        codes.append(
            await _hit_one(method, path, {"X-Operator-Token": "aop_abc_secret"}, {})
        )
    assert len(seen) >= len(_SESSION_ROUTES), (
        f"the operator token was consulted {len(seen)} times across "
        f"{len(_SESSION_ROUTES)} session routes: {codes}"
    )
    assert 401 not in codes, codes


async def test_an_operator_token_is_rejected_on_a_non_queue_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The containment. The token is not a JWT, so `get_current_user` rejects it
    everywhere else by construction — but that is worth asserting rather than assuming,
    because it is the whole reason a closed-scope credential is safe to put on a machine
    running next to hostile page JavaScript."""
    monkeypatch.setattr(
        operator_auth, "verify_operator_token",
        lambda raw: OperatorPrincipal(
            token_id="t1", user_id="u1",
            scopes=frozenset({"citation_queue"}), expires_at=None, issued_at=None,
        ),
    )
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            for path in ("/api/v1/clients", "/api/v1/cost/dial", "/api/v1/activity", "/api/v1/cost/budgets"):
                r = await c.get(path, headers={"X-Operator-Token": "aop_abc_secret"})
                # 401 specifically — not merely "not 200". A 404 would mean the path
                # does not exist and the assertion proved nothing, which is how the
                # first version of this test passed vacuously.
                assert r.status_code == 401, f"{path} accepted an operator token: {r.status_code}"
