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
requires the `citation_queue` scope, which is one of exactly two values the schema will
store.

Unauthenticated is still 401, so `tests/test_route_auth_guard.py`'s sweep is unaffected.
"""

from __future__ import annotations

import asyncio
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
from app.services.operator_tokens import OperatorPrincipal, verify_operator_token
from app.services.token_denylist import is_revoked

logger = get_logger("app.modules.citations.operator_auth")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def resolve_operator(
    request: Request,
    settings: SettingsDep,
    redis: RedisDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> CurrentUser:
    """Resolve either credential to a `CurrentUser`.

    The operator header is tried FIRST. If it is present it must be valid - a bad
    operator token is never allowed to fall through to bearer auth, because that would
    turn a rejected extension into a confusing 401 about a header it never sent.
    """
    if not x_operator_token:
        # No extension credential: behave EXACTLY as every other route does, by calling
        # the same dependency rather than reimplementing it. Its dependencies are
        # declared above and passed straight through, so bearer auth here is not a
        # lookalike of the real path - it IS the real path.
        return await get_current_user(request, settings, redis, credentials)

    principal = await asyncio.to_thread(verify_operator_token, x_operator_token)
    if principal is None or not principal.has("citation_queue"):
        raise _UNAUTHENTICATED

    # The per-user revocation epoch: a password change or a suspension already calls
    # `revoke_all_for_user`, so offboarding kills every paired extension with no new code
    # on that path. Fails OPEN by contract - the Postgres checks inside
    # `verify_operator_token` are what actually hold the line.
    try:
        if await is_revoked(
            redis, jti=None, user_id=principal.user_id, issued_at=principal.issued_at
        ):
            raise _UNAUTHENTICATED
    except HTTPException:
        raise
    except Exception:
        logger.info("operator_token_denylist_unavailable")

    # Reuse auth.py's own loader so the row shape and the RLS bootstrap-self-read stay
    # in one place. A divergent second loader here would be a second thing to keep right.
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


OperatorOrUserDep = Annotated[CurrentUser, Depends(resolve_operator)]


def operator_principal_of(x_operator_token: str | None) -> OperatorPrincipal | None:
    """The raw principal, for routes that need to know a call came from the extension
    (and with which scopes) rather than merely who is behind it."""
    return verify_operator_token(x_operator_token) if x_operator_token else None


_LEAD_ROLES = frozenset({"owner", "admin", "manager"})

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="This action requires an owner, admin or manager.",
)


async def require_operator_lead(user: OperatorOrUserDep) -> CurrentUser:
    """A lead, however they authenticated.

    An operator token INHERITS its holder's role and grants nothing extra - so a
    non-lead who pairs an extension is refused the write endpoints for exactly the same
    reason their dashboard session would be. The token narrows what is reachable; it
    never widens who someone is."""
    if user.role not in _LEAD_ROLES:
        raise _FORBIDDEN
    return user
