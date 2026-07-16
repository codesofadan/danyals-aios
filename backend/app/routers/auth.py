"""Local login - username/password -> our own EdDSA access token (P6A-7 cutover).

This is the ONLY unauthenticated write in the API and the single entry point for
all three portals (admin, team, client). It looks a user up by ``username``
(case-insensitively), verifies the argon2 password hash held in ``auth.users``,
and - on success - signs a short-lived EdDSA access token. There is NO public
signup: a login exists only because a super-admin provisioned it.

Security posture:
* A wrong password AND an unknown username both return ONE generic 401 (no user
  enumeration), and the unknown-user path still runs an argon2 verify against a
  dummy hash so the two paths take comparable time (no timing oracle).
* The returned ``portal`` is SERVER-AUTHORITATIVE, derived from the trusted
  ``users.role`` - the client cannot ask to be routed to a portal it is not in.
* The credential lookup uses ``privileged_connection`` (service_role) because
  ``auth.users`` is readable only by the server; the password hash never leaves
  this function and is never logged.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from app.core.deps import SettingsDep
from app.core.ratelimit import rate_limit_ip
from app.db.database import DatabaseNotConfiguredError, privileged_connection
from app.rbac import UserRole
from app.services.passwords import hash_password, verify_password
from app.services.tokens import TokenSigningNotConfiguredError, issue_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

Portal = Literal["admin", "team", "client"]

# Server-authoritative role -> portal routing. Owner/admin land in the admin
# console; the four staff roles share the team workspace; a client goes to the
# tenant portal. Derived from the trusted users row, NEVER from the request.
_PORTAL_BY_ROLE: dict[str, Portal] = {
    "owner": "admin",
    "admin": "admin",
    "manager": "team",
    "specialist": "team",
    "analyst": "team",
    "viewer": "team",
    "client": "client",
}

# A throwaway argon2 hash used ONLY to equalize timing when the username is
# unknown: verifying a real password against it always fails, but it costs the
# same ~argon2 work as a genuine check, so the "no such user" and "wrong password"
# paths are indistinguishable by latency. Computed once at import.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


class LoginRequest(BaseModel):
    """Login payload. ``password`` is a ``SecretStr`` so it never lands in a log/repr."""

    username: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1)


class LoginResponse(BaseModel):
    """Issued token + the server-decided routing for the client to redirect on."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: UserRole
    portal: Portal


def _lookup_credentials(username: str) -> dict[str, Any] | None:
    """Return ``{id, role, password_hash}`` for ``username`` (case-insensitive) or None.

    Joins the identity row to its credential in ``auth.users`` on the privileged
    (service_role) connection - ``auth.users`` is not readable by any other role.
    Blocking (psycopg is sync); the caller offloads with ``to_thread``.
    """
    with privileged_connection() as cur:
        cur.execute(
            """
            select u.id, u.role, a.password_hash
            from public.users u
            join auth.users a on a.id = u.id
            where lower(u.username) = lower(%s)
            limit 1
            """,
            (username,),
        )
        return cur.fetchone()


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit_ip("auth_login", 10))],
)
async def login(body: LoginRequest, settings: SettingsDep) -> LoginResponse:
    """Verify username/password and mint an EdDSA access token (else generic 401)."""
    try:
        row = await asyncio.to_thread(_lookup_credentials, body.username)
    except DatabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth backend not configured"
        ) from exc

    password = body.password.get_secret_value()
    # Constant-ish time: always run one argon2 verify. Unknown user -> verify
    # against the dummy hash (always False) so timing does not reveal existence.
    stored_hash = row["password_hash"] if row is not None else _DUMMY_HASH
    if not verify_password(stored_hash, password) or row is None:
        raise _INVALID_CREDENTIALS

    role: UserRole = row["role"]
    try:
        token = issue_access_token(str(row["id"]), role, settings=settings)
    except TokenSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth backend not configured"
        ) from exc

    return LoginResponse(access_token=token, role=role, portal=_PORTAL_BY_ROLE[role])
