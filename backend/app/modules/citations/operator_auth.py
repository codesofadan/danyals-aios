"""Letting the extension reach the queue, without giving it a second implementation.

The queue endpoints (`/citation-builder/queue/*`) already exist, already run on the RLS
connection, and already contain the one piece of logic that must not be duplicated: a
completion is CHECKED by fetching the listing URL, not asserted. Building a parallel
`/citation-operator/*` surface for the extension would mean a second copy of that check,
and two copies of a rule are a rule that will eventually differ.

So the extension calls the SAME routes, and only the way it proves who it is changes.
`OperatorOrUserDep` accepts either credential and resolves both to the ordinary
`CurrentUser` the routes already expect.

WHY THIS DOES NOT WIDEN ANYTHING. An operator token is `aop_<prefix>_<secret>` - not a
JWT - and it is presented in its own `X-Operator-Token` header. `get_current_user` reads
`Authorization: Bearer` and validates an EdDSA signature, so it rejects this token on
every other route by construction rather than by remembering to. Only the handful of
routes that opt into this dependency are reachable with it, and reaching them still
requires a citation-queue scope, which is one of exactly seven values the schema will
store.

SCOPES SPLIT IN 0131 (`citation_queue:read` / `:write`, `client_profile:read`,
`web2_queue:read` / `:write`). `require_operator_scope(...)` builds a dependency that
enforces one granular scope on the extension path while leaving bearer callers governed
by their role, exactly as before - the legacy umbrella `citation_queue` satisfies both
queue halves until those tokens age out, so nothing re-pairs. `resolve_operator` is the
`:read` member of that family, which keeps every existing override and monkeypatch seam
pointing at one function object.

Unauthenticated is still 401, so `tests/test_route_auth_guard.py`'s sweep is unaffected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth import (
    CurrentUser,
    _bearer,
    _load_user_row,
    get_current_user,
)
from app.core.deps import RedisDep, SettingsDep
from app.logging_setup import get_logger
from app.rbac import PermKey, role_has_perm
from app.services.operator_tokens import OperatorPrincipal, verify_operator_token
from app.services.token_denylist import is_revoked

logger = get_logger("app.modules.citations.operator_auth")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _refuse_unless_epoch_clean(redis: object, principal: OperatorPrincipal) -> None:
    """The per-user revocation epoch: a password change or a suspension already calls
    `revoke_all_for_user`, so offboarding kills every paired extension with no new code
    on that path. Fails CLOSED: a paired extension is a long-lived plaintext-on-disk
    credential whose only FAST kill switch lives in Redis — this check ran silently
    skipped for days on this very box (the API had no REDIS_URL), which quietly
    downgraded revocation to "whenever the token expires". The Postgres checks inside
    `verify_operator_token` (expiry, per-token revoked flag, rotation replay) still ran
    first and are unaffected; what refuses here is only the epoch check being
    UNANSWERABLE.

    ``fail_closed=True`` is what makes the except-branch REACHABLE: plain
    ``is_revoked`` swallows every exception and returns False by contract (it fails
    open for JWT sessions, whose real line is the Postgres suspension check), so
    without it a Redis outage would silently skip this check on every operator
    path instead of refusing."""
    try:
        if await is_revoked(
            redis,
            jti=None,
            user_id=principal.user_id,
            issued_at=principal.issued_at,
            fail_closed=True,
        ):
            raise _UNAUTHENTICATED
    except HTTPException:
        raise
    except Exception:
        logger.warning("operator_token_denylist_unavailable_failing_closed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cannot verify token revocation right now (Redis is unreachable from the "
                "API). Start Redis / fix REDIS_URL on the server, then try again."
            ),
        ) from None


def require_operator_scope(scope: str) -> Callable[..., Awaitable[CurrentUser]]:
    """A dependency that resolves either credential, requiring ``scope`` of the extension.

    A bearer caller is untouched — their role already governs them, and an operator
    token must never become a SECOND way to gate staff. Only the extension path checks
    the scope, via `OperatorPrincipal.has`, whose one-way legacy mapping lets a
    pre-split `citation_queue` token satisfy both granular queue halves until it ages
    out. Built for the queue-route guard swap (`citation_queue:read` on reads,
    `:write` on mutations) — apply it there in that stage, not from here."""

    async def resolve_operator(
        request: Request,
        settings: SettingsDep,
        redis: RedisDep,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
    ) -> CurrentUser:
        """Resolve either credential to a `CurrentUser`.

        The operator header is tried FIRST. If it is present it must be valid - a bad
        operator token is never allowed to fall through to bearer auth, because that
        would turn a rejected extension into a confusing 401 about a header it never
        sent.
        """
        if not x_operator_token:
            # No extension credential: behave EXACTLY as every other route does, by
            # calling the same dependency rather than reimplementing it. Its
            # dependencies are declared above and passed straight through, so bearer
            # auth here is not a lookalike of the real path - it IS the real path.
            return await get_current_user(request, settings, redis, credentials)

        principal = await asyncio.to_thread(verify_operator_token, x_operator_token)
        if principal is None or not principal.has(scope):
            raise _UNAUTHENTICATED

        await _refuse_unless_epoch_clean(redis, principal)

        # Reuse auth.py's own loader so the row shape and the RLS bootstrap-self-read
        # stay in one place. A divergent second loader here would be a second thing to
        # keep right.
        row = await asyncio.to_thread(_load_user_row, principal.user_id)
        if row is None or str(row.get("status") or "") == "suspended":
            raise _UNAUTHENTICATED
        raw_client_id = row.get("client_id")
        return CurrentUser(
            id=str(row["id"]),
            email=row["email"],
            role=row["role"],
            status=row["status"],
            name=row["name"],
            title=row.get("title", ""),
            avatar_color=row.get("avatar_color", "#7B69EE"),
            phone=row.get("phone", ""),
            two_fa=bool(row.get("two_fa", False)),
            client_id=str(raw_client_id) if raw_client_id else None,
        )

    return resolve_operator


# The read/write pair every queue route points at (Phase 3 applied the split):
# `:read` is the floor for touching the queue at all - the board and the item GET;
# `:write` guards every mutation (claim / heartbeat / release / complete / blocked).
# The legacy umbrella `citation_queue` satisfies both until those tokens age out.
resolve_operator = require_operator_scope("citation_queue:read")
resolve_operator_write = require_operator_scope("citation_queue:write")

OperatorOrUserDep = Annotated[CurrentUser, Depends(resolve_operator)]
OperatorOrUserWriteDep = Annotated[CurrentUser, Depends(resolve_operator_write)]


def require_operator_scope_or_perm(
    scope: str, perm: PermKey
) -> Callable[..., Awaitable[CurrentUser]]:
    """A dependency for routes that were bearer+permission-gated BEFORE the extension
    could reach them: the extension path needs ``scope``, the bearer path still needs
    ``perm`` - so widening a route to the second credential never LOOSENS what a
    dashboard session must hold. Used for the reads that serve canonical
    business-profile values (`client_profile:read` / `view_reports`)."""

    resolver = require_operator_scope(scope)

    # NOTE ON THE SIGNATURE: the resolver is CALLED, not declared as `Depends(resolver)`.
    # Under `from __future__ import annotations` every annotation is a string, and
    # FastAPI/pydantic evaluate those strings against the function's MODULE globals -
    # a closure-local like `resolver` is unresolvable there, which breaks OpenAPI
    # generation (and with it the route-auth sweep that enumerates it). So the wrapper
    # declares the resolver's own dependencies and passes them through - the real
    # bearer path is still the real path, just invoked one frame down.
    async def _dep(
        request: Request,
        settings: SettingsDep,
        redis: RedisDep,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
    ) -> CurrentUser:
        user = await resolver(request, settings, redis, credentials, x_operator_token)
        if not x_operator_token and not role_has_perm(user.role, perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {perm}",
            )
        return user

    return _dep


def require_operator_scope_sets(
    *scope_sets: tuple[str, ...],
) -> Callable[..., Awaitable[CurrentUser]]:
    """A dependency where the EXTENSION path passes when it holds EVERY scope of ANY
    one listed set; bearer callers stay governed by their role, as everywhere else.

    Built for the kind-generalized SESSION machinery (0136): a session route serves
    both citation and web2_placement sessions, so its FLOOR is "the full scope set of
    SOME kind at the right verb" - e.g. the task-card reads take
    ``("citation_queue:read", "client_profile:read")`` (citation cards carry the
    canonical NAP) or ``("web2_queue:read",)``. The handler then enforces the SESSION
    KIND's exact scopes where the kind is known (create's body, the detail read's
    loaded row). The refusal is DETERMINISTIC and runs before any epoch/DB work, so a
    wrong-scope token is a clean 401 rather than a downstream failure. The floor is
    honest because every session/task query is already pinned to the caller's own
    operator_id: the widest thing an any-of token can do is orchestrate the caller's
    OWN session of the other kind, with zero evidence authority - the evidence doors
    (citation complete/blocked, placement complete) each keep their exact scope."""

    async def _dep(
        request: Request,
        settings: SettingsDep,
        redis: RedisDep,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
    ) -> CurrentUser:
        if not x_operator_token:
            return await get_current_user(request, settings, redis, credentials)
        principal = await asyncio.to_thread(verify_operator_token, x_operator_token)
        if principal is None:
            raise _UNAUTHENTICATED
        held = next(
            (group for group in scope_sets if all(principal.has(s) for s in group)),
            None,
        )
        if held is None:
            raise _UNAUTHENTICATED
        # Reuse the single-scope resolver for the epoch check + user load, presenting
        # a scope the principal provably holds - one verification path, not two.
        resolver = require_operator_scope(held[0])
        return await resolver(request, settings, redis, credentials, x_operator_token)

    return _dep


def require_operator_scope_any(*scopes: str) -> Callable[..., Awaitable[CurrentUser]]:
    """``require_operator_scope_sets`` with singleton sets: the EXTENSION path passes
    with ANY one of ``scopes``; bearer callers stay governed by their role."""
    return require_operator_scope_sets(*((s,) for s in scopes))


# The widest queue-verb floor: identity + "holds SOME queue scope" containment, for
# repo dependencies shared by session routes whose own per-route floors (declared
# FIRST in each route signature, so they run first) are strictly narrower. Never a
# route's only guard.
resolve_any_queue_scope = require_operator_scope_any(
    "citation_queue:read", "citation_queue:write", "web2_queue:read", "web2_queue:write"
)
AnyQueueScopeDep = Annotated[CurrentUser, Depends(resolve_any_queue_scope)]


def require_operator_lead_over(
    resolver: Callable[..., Awaitable[CurrentUser]],
) -> Callable[..., Awaitable[CurrentUser]]:
    """A LEAD, resolved through ``resolver`` (a module-level floor OBJECT, so tests
    can override the floor by identity and still exercise the REAL role gate here).

    Composed via ``Depends`` on purpose: the floor stays a first-class dependency -
    overridable, cached per-request alongside any repo dependency bound to the same
    object - while the role check itself cannot be skipped without stubbing THIS
    resolver. An operator token INHERITS its holder's role and grants nothing extra."""

    async def _dep(user: CurrentUser = Depends(resolver)) -> CurrentUser:  # noqa: B008
        if user.role not in _LEAD_ROLES:
            raise _FORBIDDEN
        return user

    return _dep


def operator_principal_of(x_operator_token: str | None) -> OperatorPrincipal | None:
    """The raw principal, for routes that need to know a call came from the extension
    (and with which scopes) rather than merely who is behind it."""
    return verify_operator_token(x_operator_token) if x_operator_token else None


@dataclass(frozen=True)
class RotationGrant:
    """A verified rotation caller: the principal, plus the raw token it presented -
    which the rotation service needs, because rotation CONSUMES the presented token."""

    raw_token: str
    principal: OperatorPrincipal


async def resolve_rotation_grant(
    redis: RedisDep,
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> RotationGrant:
    """The rotation endpoint's ONLY credential: a live operator token.

    Deliberately narrower than `resolve_operator`: no bearer fallback (a dashboard
    session must never mint an extension token through the rotation door - pairing is
    the audited path for that), and NO scope check (every live token may fetch its own
    successor; rotation is how a token stays alive, not a capability it holds). The
    full verification still runs - hash compare, revoked, expiry, suspension, rotation
    replay inside `verify_operator_token`, then the fail-closed epoch check. Every
    refusal is the same 401, which is exactly the signal the extension turns into its
    re-pair state."""
    if not x_operator_token:
        raise _UNAUTHENTICATED
    principal = await asyncio.to_thread(verify_operator_token, x_operator_token)
    if principal is None:
        raise _UNAUTHENTICATED
    await _refuse_unless_epoch_clean(redis, principal)
    return RotationGrant(raw_token=x_operator_token, principal=principal)


RotationGrantDep = Annotated[RotationGrant, Depends(resolve_rotation_grant)]


_LEAD_ROLES = frozenset({"owner", "admin", "manager"})

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="This action requires an owner, admin or manager.",
)


async def require_operator_lead(user: OperatorOrUserWriteDep) -> CurrentUser:
    """A lead, however they authenticated - resolved through the WRITE scope, because
    every lead-gated queue route is a mutation (claim / complete / blocked).

    An operator token INHERITS its holder's role and grants nothing extra - so a
    non-lead who pairs an extension is refused the write endpoints for exactly the same
    reason their dashboard session would be. The token narrows what is reachable; it
    never widens who someone is."""
    if user.role not in _LEAD_ROLES:
        raise _FORBIDDEN
    return user
