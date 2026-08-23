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
* A SUSPENDED account is refused with a 403 that names the reason - but ONLY
  after the password verifies, so this endpoint never becomes an oracle for
  which accounts exist or which have been closed.
* The returned ``portal`` is SERVER-AUTHORITATIVE, derived from the trusted
  ``users.role`` - the client cannot ask to be routed to a portal it is not in.
* The credential lookup uses ``privileged_connection`` (service_role) because
  ``auth.users`` is readable only by the server; the password hash never leaves
  this function and is never logged.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, SecretStr

from app.core.auth import SUSPENDED_STATUS, CurrentUserDep
from app.core.deps import RedisDep, SettingsDep
from app.core.ratelimit import rate_limit_ip
from app.db.database import DatabaseNotConfiguredError, privileged_connection
from app.logging_setup import get_logger
from app.rbac import UserRole
from app.services.passwords import hash_password, verify_password
from app.services.token_denylist import revoke_token
from app.services.tokens import TokenSigningNotConfiguredError, issue_access_token

logger = get_logger("app.auth.routes")

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

# Raised only AFTER a successful password verify - see the comment at the call
# site for why the ordering is a security property, not an implementation detail.
_ACCOUNT_SUSPENDED = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="This account has been suspended. Contact your administrator.",
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
    """Return ``{id, role, status, password_hash}`` for ``username`` OR email.

    People routinely type their email into a "username" box (and a portal login
    like ``admin@client.com`` IS email-shaped), so the lookup matches either
    column — both are case-insensitively unique, and ties prefer the username
    match so an email that collides with someone else's username cannot shadow it.

    Joins the identity row to its credential in ``auth.users`` on the privileged
    (service_role) connection - ``auth.users`` is not readable by any other role.
    Blocking (psycopg is sync); the caller offloads with ``to_thread``.
    """
    with privileged_connection() as cur:
        cur.execute(
            """
            select u.id, u.role, u.status, a.password_hash
            from public.users u
            join auth.users a on a.id = u.id
            where lower(u.username) = lower(%(login)s) or lower(u.email) = lower(%(login)s)
            order by (lower(u.username) = lower(%(login)s)) desc
            limit 1
            """,
            {"login": username},
        )
        return cur.fetchone()


def _activate_if_invited(user_id: str) -> None:
    """First successful sign-in flips ``status`` invited -> active (best-effort).

    Provisioning stamps every new account ``invited``; without this the roster
    shows members as "Invited" forever and metric views (which exclude invited
    rows) stay empty even for people who log in daily. Never raises - a failed
    flip must not fail a correct login.
    """
    try:
        with privileged_connection() as cur:
            cur.execute(
                "update public.users set status = 'active' "
                "where id = %s and status = 'invited'",
                (user_id,),
            )
    except Exception:  # pragma: no cover - best-effort by contract
        pass


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

    # A SUSPENDED account may not obtain a new token. Checked AFTER the password
    # verify on purpose: doing it before would turn this endpoint into an
    # enumeration oracle, letting anyone probe which accounts exist and which are
    # closed without knowing a password. After a successful verify the caller has
    # already proved they hold that account's credential, so naming the reason
    # tells them nothing they could not otherwise learn - and an offboarded
    # person deserves a clear answer rather than a confusing "invalid password".
    #
    # This is the SECOND of two enforcement points. The one that actually matters
    # is in `app.core.auth.get_current_user`, which runs on every authenticated
    # request and therefore also stops a token issued BEFORE the suspension.
    if str(row.get("status") or "") == SUSPENDED_STATUS:
        raise _ACCOUNT_SUSPENDED

    role: UserRole = row["role"]
    await asyncio.to_thread(_activate_if_invited, str(row["id"]))
    try:
        token = issue_access_token(str(row["id"]), role, settings=settings)
    except TokenSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth backend not configured"
        ) from exc

    return LoginResponse(access_token=token, role=role, portal=_PORTAL_BY_ROLE[role])


class LogoutResponse(BaseModel):
    """The honest outcome of a sign-out.

    ``revoked`` is False when the revocation could not be recorded (Redis
    unreachable). The endpoint still returns 200 — the caller SHOULD discard the
    token either way — but it does not claim a revocation that did not happen.
    A UI that shows "signed out everywhere" on a False here would be inventing
    a security guarantee, which is precisely the failure mode this recovery is
    removing from the product.
    """

    revoked: bool


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    user: CurrentUserDep,
    redis: RedisDep,
) -> LogoutResponse:
    """Revoke THE TOKEN THIS REQUEST CARRIES.

    Signing out used to be a purely client-side act: the browser cleared
    `localStorage` and the token itself stayed valid for its full multi-day life,
    so anyone who had copied it kept working access. This makes sign-out mean
    something server-side.

    Scoped to this ONE token by its `jti`, deliberately — a person signing out of
    a shared machine should not be signed out of their phone. Ending EVERY session
    is a different act, performed by a password change or a suspension, and it
    uses the per-user epoch instead (see `app.services.token_denylist`).

    The claims come from `request.state`, stashed by `get_current_user` after full
    verification — so this cannot be used to revoke a token that was not itself
    valid on this request.
    """
    claims: dict[str, Any] = getattr(request.state, "token_claims", {}) or {}
    jti = str(claims.get("jti") or "")
    if not jti:
        # A legacy token minted before `jti` existed. There is nothing to revoke
        # by id, and it will simply expire. Say so rather than reporting success.
        logger.info("logout_without_jti", user_id=user.id)
        return LogoutResponse(revoked=False)

    revoked = await revoke_token(redis, jti=jti, exp=claims.get("exp"))
    logger.info("logout", user_id=user.id, revoked=revoked)
    return LogoutResponse(revoked=revoked)
