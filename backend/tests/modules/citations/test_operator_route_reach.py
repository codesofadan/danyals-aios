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
