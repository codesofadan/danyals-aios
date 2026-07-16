"""Mint our own EdDSA (Ed25519) access tokens - the local login signing path.

At the P6A-7 cutover the API stops verifying Supabase GoTrue tokens and starts
issuing its own. :func:`issue_access_token` signs a short-lived token with the
Ed25519 PRIVATE key (API-only); :mod:`app.core.auth` verifies it with the PUBLIC
key under a strict ``["EdDSA"]`` allow-list. Claims are deliberately minimal and
mirror the Supabase shape enough that the downstream user-load + RBAC are
unchanged: ``sub`` (the user uuid), ``role``, plus the registered ``aud``/
``iss``/``iat``/``exp``. Nothing sensitive rides in the token - authorization is
re-derived server-side from the ``users`` row on every request.
"""

from __future__ import annotations

import time

import jwt

from app.config import Settings
from app.rbac import UserRole

# The ONLY algorithm we ever sign or verify with. A single-entry allow-list is the
# defense against alg-confusion / `none`: a token asking for HS256 or `none` can
# never match this list, so verification rejects it before touching the key.
JWT_ALGORITHM = "EdDSA"


class TokenSigningNotConfiguredError(RuntimeError):
    """Raised when a token is requested but no Ed25519 signing key is configured."""


def issue_access_token(
    user_id: str, role: UserRole, *, settings: Settings, ttl: int | None = None
) -> str:
    """Sign an access token for ``user_id``/``role`` with the Ed25519 private key.

    ``ttl`` (seconds) overrides ``settings.jwt_access_ttl_seconds``. Raises
    :class:`TokenSigningNotConfiguredError` when the private key is absent so the
    caller can surface a 503 rather than a 500.
    """
    private_pem = settings.jwt_private_key_pem
    if not private_pem:
        raise TokenSigningNotConfiguredError("JWT_PRIVATE_KEY is not configured")
    now = int(time.time())
    lifetime = settings.jwt_access_ttl_seconds if ttl is None else ttl
    payload = {
        "sub": str(user_id),
        "role": role,
        "aud": settings.jwt_audience,
        "iss": settings.local_jwt_issuer,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, private_pem, algorithm=JWT_ALGORITHM)
