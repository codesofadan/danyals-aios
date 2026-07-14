"""Authentication: verify Supabase access tokens and resolve the current user.

Supabase signs access tokens with asymmetric keys (ES256/RS256). The API fetches
the project's JWKS once, caches the public keys by ``kid``, and verifies each
token locally (signature + ``aud`` + ``iss`` + ``exp``) - no per-request network
call to Supabase, and no shared secret on the server.

The verified ``sub`` claim (the Supabase auth uid) is used to load the caller's
row from ``public.users`` through an RLS-respecting user-JWT client, yielding a
:class:`CurrentUser`. There is no public signup: a user exists only if a
super-admin provisioned it (see ``app/services/provisioning.py``).

Verification is split so it is testable without a network or a database:

* :func:`decode_and_validate` is pure crypto given a key.
* :class:`JWKSCache` resolves ``kid`` -> key (the only networked part).
* :func:`get_current_user` composes them and adds the DB lookup.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, cast

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK, PyJWKSet
from pydantic import BaseModel

from app.config import Settings
from app.core.deps import HttpClientDep, SettingsDep
from app.db.supabase import SupabaseNotConfiguredError, client_for_user
from app.rbac import AccessLevel, AppRole, PermKey, UserRole, feature_allows, role_has_perm

# Supabase issues ES256 (default for new projects) or RS256 signing keys.
_ALLOWED_ALGS = ["ES256", "RS256"]

_bearer = HTTPBearer(auto_error=False, description="Supabase access token")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing, invalid, or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


class AuthError(Exception):
    """Internal signal that a token could not be verified (mapped to 401)."""


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


class JWKSCache:
    """Caches a project's JWKS public keys by ``kid``, refreshing on a miss.

    One instance lives on ``app.state`` for the app's lifetime. Refresh uses the
    shared async ``httpx`` client so it never blocks the event loop.
    """

    def __init__(self, jwks_url: str) -> None:
        self._url = jwks_url
        self._keys: dict[str, PyJWK] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> JWKSCache | None:
        """Build a cache from settings, or ``None`` when Supabase is unconfigured."""
        url = settings.jwks_url
        return cls(url) if url else None

    def load_keys(self, keys: dict[str, PyJWK]) -> None:
        """Test seam: preload keys so verification needs no network."""
        self._keys = dict(keys)

    async def signing_key(self, token: str, http_client: httpx.AsyncClient) -> PyJWK:
        """Return the key that signed ``token``, refreshing the JWKS on a miss."""
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise AuthError("malformed token header") from exc
        if not kid:
            raise AuthError("token header has no kid")
        if kid not in self._keys:
            await self._refresh(http_client)
        key = self._keys.get(kid)
        if key is None:
            raise AuthError("no matching signing key")
        return key

    async def _refresh(self, http_client: httpx.AsyncClient) -> None:
        async with self._lock:
            try:
                resp = await http_client.get(self._url, timeout=5.0)
                resp.raise_for_status()
                jwks = PyJWKSet.from_dict(resp.json())
            except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError) as exc:
                raise AuthError("could not fetch signing keys") from exc
            self._keys = {k.key_id: k for k in jwks.keys if k.key_id}


def decode_and_validate(
    token: str, signing_key: Any, *, audience: str, issuer: str | None
) -> dict[str, Any]:
    """Verify signature + registered claims and return the token payload.

    Raises ``jwt.PyJWTError`` on any failure (bad signature, wrong audience/
    issuer, expiry, or a missing required claim).
    """
    claims: dict[str, Any] = jwt.decode(
        token,
        signing_key,
        algorithms=_ALLOWED_ALGS,
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "sub", "aud"]},
    )
    return claims


def _load_user_row(user_id: str, access_token: str) -> dict[str, Any] | None:
    """Load the caller's ``public.users`` row via an RLS-respecting client.

    Blocking (supabase-py is sync); callers must offload with ``to_thread``.
    """
    client = client_for_user(access_token)
    resp = client.table("users").select("*").eq("id", user_id).limit(1).execute()
    rows = cast("list[dict[str, Any]]", resp.data or [])
    return rows[0] if rows else None


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    http_client: HttpClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """FastAPI dependency: the verified, provisioned caller (else 401/403)."""
    if credentials is None:
        raise _UNAUTHORIZED
    token = credentials.credentials

    cache: JWKSCache | None = getattr(request.app.state, "jwks_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )

    try:
        signing_key = await cache.signing_key(token, http_client)
        claims = decode_and_validate(
            token,
            signing_key.key,
            audience=settings.supabase_jwt_aud,
            issuer=settings.jwt_issuer,
        )
    except (AuthError, jwt.PyJWTError) as exc:
        raise _UNAUTHORIZED from exc

    user_id = str(claims["sub"])
    # Stash the token so downstream deps (require_feature) can reuse the same
    # RLS-scoped client without re-parsing the header.
    request.state.access_token = token

    try:
        row = await asyncio.to_thread(_load_user_row, user_id, token)
    except SupabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from exc

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


def _load_feature_grants(user_id: str, access_token: str) -> dict[str, AccessLevel]:
    """Load a user's per-feature grant overrides (blocking; offload with to_thread)."""
    client = client_for_user(access_token)
    resp = (
        client.table("user_feature_grants")
        .select("feature_key, level")
        .eq("user_id", user_id)
        .execute()
    )
    rows = cast("list[dict[str, Any]]", resp.data or [])
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
        token: str | None = getattr(request.state, "access_token", None)
        overrides: dict[str, AccessLevel] = {}
        if token is not None:
            overrides = await asyncio.to_thread(_load_feature_grants, user.id, token)
        if not feature_allows(user.role, overrides, feature_key, level):
            raise _forbid(f"Missing feature access: {feature_key}")
        return user

    return _dep
