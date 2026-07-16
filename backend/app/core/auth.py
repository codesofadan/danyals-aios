"""Authentication: verify our own EdDSA access tokens and resolve the current user.

Since the P6A-7 cutover the API signs and verifies its OWN tokens - Supabase
GoTrue/JWKS is gone. Login (``app/routers/auth.py``) signs a short-lived token
with the Ed25519 PRIVATE key; every request verifies it here with the STATIC
PUBLIC key. No network round-trip and, crucially, a HARD algorithm allow-list of
``["EdDSA"]`` - which defeats alg-confusion and the ``none`` attack, since a token
asking for HS256/RS256/none can never match the list.

The verified ``sub`` claim (the user uuid) loads the caller's row from
``public.users`` through the RLS-scoped ``rls_connection`` seam (the sub is bound
as the RLS identity), yielding a :class:`CurrentUser`. There is no public signup:
a user exists only if a super-admin provisioned it (see
``app/services/provisioning.py``).

Verification is split so it is testable without a network or a database:

* :func:`decode_and_validate` is pure crypto given the public key.
* :func:`get_current_user` composes it with the DB lookup.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.deps import SettingsDep
from app.db.database import DatabaseNotConfiguredError, rls_connection
from app.rbac import (
    AccessLevel,
    AppRole,
    ModulePermKey,
    PermKey,
    UserRole,
    feature_allows,
    role_has_module_perm,
    role_has_perm,
)

# The ONE algorithm we accept. A single-entry allow-list is the whole defense
# against alg-confusion and `none`: PyJWT rejects any token whose header `alg` is
# not in this list BEFORE selecting a verifier, so an attacker cannot downgrade to
# HS256 (and try the public key as an HMAC secret) or to `none` (no signature).
_ALLOWED_ALGS = ["EdDSA"]

_bearer = HTTPBearer(auto_error=False, description="Local EdDSA access token")

_AUTH_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Authentication is not configured",
)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing, invalid, or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


class CurrentUser(BaseModel):
    """The authenticated caller, resolved from a verified token + the users row."""

    id: str
    email: str
    role: UserRole
    status: str
    name: str
    title: str
    avatar_color: str
    phone: str
    two_fa: bool
    # Set only for a portal client (role='client'), from the trusted users row;
    # NULL for staff. NEVER accepted from a request body (see get_current_client).
    client_id: str | None = None

    @property
    def is_owner(self) -> bool:
        """Owner (agency super-admin) is all-on and locked."""
        return self.role == "owner"


class CurrentClient(BaseModel):
    """A verified PORTAL CLIENT caller: the user row + its guaranteed tenant id.

    Built only by :func:`get_current_client`, which 403s unless the caller is a
    ``client`` with a ``client_id``. So ``client_id`` here is always trustworthy
    and server-pinned - it is the tenant boundary, never taken from request input.
    """

    user: CurrentUser
    client_id: str


def decode_and_validate(
    token: str, public_key: Any, *, audience: str, issuer: str | None
) -> dict[str, Any]:
    """Verify signature + registered claims against ``public_key`` and return the payload.

    ``public_key`` is the Ed25519 PUBLIC key (a PEM string or key object). The
    algorithm allow-list is fixed to ``["EdDSA"]`` (alg-confusion/``none`` defense),
    and ``aud``/``iss``/``exp``/``sub`` are all verified - ``exp``/``sub``/``aud``
    are additionally REQUIRED to be present. Raises ``jwt.PyJWTError`` on any
    failure (bad signature, wrong alg, wrong audience/issuer, expiry, or a missing
    required claim).
    """
    claims: dict[str, Any] = jwt.decode(
        token,
        public_key,
        algorithms=_ALLOWED_ALGS,
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "sub", "aud"]},
    )
    return claims


def _load_user_row(user_id: str) -> dict[str, Any] | None:
    """Load the caller's ``public.users`` row via the RLS-scoped ``rls_connection``.

    A bootstrap self-read: ``user_id`` is the verified JWT ``sub``, bound as the
    RLS identity AND the row filter (users_select permits ``auth.uid() = id``).
    Blocking (psycopg is sync); callers must offload with ``to_thread``.
    """
    with rls_connection(user_id) as cur:
        cur.execute("select * from public.users where id = %s limit 1", (user_id,))
        return cur.fetchone()


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """FastAPI dependency: the verified, provisioned caller (else 401/403)."""
    if credentials is None:
        raise _UNAUTHORIZED
    token = credentials.credentials

    public_key = settings.jwt_public_key_pem
    if not public_key:
        # No verification key configured -> we cannot trust any token. 503, never
        # a silent accept.
        raise _AUTH_NOT_CONFIGURED

    try:
        claims = decode_and_validate(
            token,
            public_key,
            audience=settings.jwt_audience,
            issuer=settings.local_jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise _UNAUTHORIZED from exc

    user_id = str(claims["sub"])
    # Stash the token so downstream deps can reuse the verified bearer if needed
    # (RLS access itself now flows through rls_connection off the verified sub).
    request.state.access_token = token

    try:
        row = await asyncio.to_thread(_load_user_row, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _AUTH_NOT_CONFIGURED from exc

    if row is None:
        # Valid token, but no agency user exists for it (no public signup).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not provisioned",
        )

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


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def _forbid(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def get_current_client(user: CurrentUserDep) -> CurrentClient:
    """FastAPI dependency: the caller as a scoped portal client (else 403).

    Guards every ``/portal/*`` route. Any non-client role - or a client somehow
    missing its ``client_id`` - is rejected. The returned ``client_id`` comes from
    the trusted users row and is the tenant boundary for all portal reads/writes.
    """
    if user.role != "client" or not user.client_id:
        raise _forbid("Client portal access only")
    return CurrentClient(user=user, client_id=user.client_id)


CurrentClientDep = Annotated[CurrentClient, Depends(get_current_client)]


def require_perm(perm: PermKey) -> Any:
    """Dependency factory: require the caller's role to hold ``perm`` (else 403)."""

    async def _dep(user: CurrentUserDep) -> CurrentUser:
        if not role_has_perm(user.role, perm):
            raise _forbid(f"Missing permission: {perm}")
        return user

    return _dep


def require_module_perm(perm: ModulePermKey) -> Any:
    """Dependency factory: require the caller's role to hold the MODULE perm ``perm``.

    The Part-8 tool modules' finer-grained gate, kept SEPARATE from ``require_perm``:
    ``ModulePermKey`` is an additive, backend-only vocabulary that sits alongside the
    8 frontend-mirrored governance perms, so the Team-screen matrix stays byte-for-byte
    in sync with ``data.ts`` while a module can still gate a paid action. Holder roles
    live in ``MODULE_PERM_ROLES`` and MIRROR the owning migration's RLS write policies
    (owner is all-on and locked - see ``role_has_module_perm``).
    """

    async def _dep(user: CurrentUserDep) -> CurrentUser:
        if not role_has_module_perm(user.role, perm):
            raise _forbid(f"Missing permission: {perm}")
        return user

    return _dep


def require_role(*roles: AppRole) -> Any:
    """Dependency factory: require the caller's role to be one of ``roles``.

    Owner always passes (all-on and locked).
    """
    allowed = frozenset(roles)

    async def _dep(user: CurrentUserDep) -> CurrentUser:
        if user.role != "owner" and user.role not in allowed:
            raise _forbid("Insufficient role")
        return user

    return _dep


def require_owner() -> Any:
    """Dependency factory: super-admin (owner) only."""

    async def _dep(user: CurrentUserDep) -> CurrentUser:
        if not user.is_owner:
            raise _forbid("Super-admin only")
        return user

    return _dep


def _load_feature_grants(user_id: str) -> dict[str, AccessLevel]:
    """Load a user's per-feature grant overrides via the RLS-scoped ``rls_connection``.

    A bootstrap self-read (``user_id`` = the verified JWT ``sub``, bound as the
    RLS identity; user_feature_grants_select permits ``user_id = auth.uid()``).
    Blocking (psycopg is sync); offload with ``to_thread``.
    """
    with rls_connection(user_id) as cur:
        cur.execute(
            "select feature_key, level from public.user_feature_grants where user_id = %s",
            (user_id,),
        )
        rows = cur.fetchall()
    return {r["feature_key"]: r["level"] for r in rows}


def require_feature(feature_key: str, level: AccessLevel = "full") -> Any:
    """Dependency factory: require fine-grained access to ``feature_key``.

    Owner is all-on. Otherwise the check consults the caller's per-user grants
    (loaded via the RLS-scoped client), so it costs one extra query - use it only
    where feature-level (not role-level) granularity is needed.
    """

    async def _dep(request: Request, user: CurrentUserDep) -> CurrentUser:
        if user.is_owner:
            return user
        # RLS access flows off the verified sub (user.id), not the raw token; the
        # `request` param is retained so this dep still short-circuits on owner
        # without any DB/pool dependency.
        overrides = await asyncio.to_thread(_load_feature_grants, user.id)
        if not feature_allows(user.role, overrides, feature_key, level):
            raise _forbid(f"Missing feature access: {feature_key}")
        return user

    return _dep
