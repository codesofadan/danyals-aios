"""Skill-token mint / verify / revoke / list + the SCOPED PRINCIPAL (Part 9).

A skill token lets a client's LOCAL Claude Code skills call this backend through
the MCP gateway. It is a SEPARATE credential from the EdDSA user access token
(``app/services/tokens.py``): a user token authenticates a human and is re-derived
to a full ``CurrentUser``; a skill token authenticates an automated skill and
resolves to a :class:`ScopedPrincipal` - ONE client tenant plus a CAPPED
RBAC/tier subset.

BLAST-RADIUS LIMIT (N7 threat model). The raw token is a 256-bit random string
shown to the minting owner/admin exactly ONCE; only its sha256 hash is stored. A
leaked token can reach ONLY:

* that ONE client's tenant - ``client_id`` is pinned on the row and copied into the
  principal; a caller never supplies it, so a token for client A can never name
  client B;
* ONLY the perms/features in its capped ``scopes`` - the principal holds exactly
  those, never the minter's full authority;
* ONLY within budget - every paid call the token drives still runs the cost-gate
  (the gateway keys it on the principal's ``client_id``).

It can NEVER reach the vault, NEVER another tenant, NEVER an RLS bypass: verify
returns the scope and never the secret/hash; the gateway pins ``client_id`` from
the token; and the reveal path simply does not exist for this credential.

DB seams: mint / list / revoke are owner/admin operations, so they run on the
RLS-scoped ``rls_connection`` (the ``skill_tokens`` policies enforce owner/admin as
defence in depth beneath the router guard). VERIFY runs on ``privileged_connection``
because the caller (the MCP gateway) presents ONLY a token - it has no user
identity to bind - so it is a trusted, server-only system op (like the vault
reveal), and it returns a capped principal, never the row's hash. All calls are
blocking (psycopg is sync); the router/gateway offload with ``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db.database import privileged_connection, rls_connection
from app.rbac import FEATURE_KEYS, PERM_KEYS

# Raw token shape: ``skt_<prefix>_<secret>``. The prefix is a short PUBLIC row
# locator; the secret is the high-entropy tail. The FULL string is what we hash.
_TOKEN_SCHEME = "skt"
_PREFIX_BYTES = 6  # -> 12 hex chars
_SECRET_BYTES = 32  # 256-bit random tail

_VALID_PERMS: frozenset[str] = frozenset(PERM_KEYS)
_VALID_FEATURES: frozenset[str] = frozenset(FEATURE_KEYS)
_VALID_TIERS: frozenset[str] = frozenset({"free", "semi", "fully"})
# Delivery-tier ranking so a token's cap can be compared to a required tier.
_TIER_RANK: dict[str, int] = {"free": 0, "semi": 1, "fully": 2}

# Columns a masked read/return may expose - deliberately EXCLUDES token_hash.
_MASKED_COLS = (
    "id, client_id, token_prefix, scopes, tier, revoked, "
    "expires_at, last_used_at, created_at"
)


class SkillTokenError(RuntimeError):
    """Raised when a skill-token operation cannot complete (never carries a secret)."""


@dataclass(frozen=True)
class ScopedPrincipal:
    """A verified skill token resolved to a capped, single-tenant identity.

    The whole blast-radius boundary in one immutable object: ``client_id`` is the
    ONLY tenant it can touch, ``perms``/``features`` the ONLY capabilities it holds,
    ``tier`` the delivery-tier cap. It carries NO secret and NO hash - it is safe to
    log its ``token_id``/``client_id`` but it never holds the credential.
    """

    token_id: str
    client_id: str
    perms: frozenset[str]
    features: frozenset[str]
    tier: str
    expires_at: datetime | None = None

    def has_perm(self, perm: str) -> bool:
        """Whether this token was granted RBAC permission ``perm``."""
        return perm in self.perms

    def has_feature(self, feature: str) -> bool:
        """Whether this token was granted access to feature ``feature``."""
        return feature in self.features

    def allows_tier(self, required: str) -> bool:
        """Whether the token's tier cap satisfies a ``required`` delivery tier."""
        return _TIER_RANK.get(self.tier, 0) >= _TIER_RANK.get(required, 0)


# --------------------------------------------------------------------------- #
# Pure helpers (no DB - unit-testable in isolation)
# --------------------------------------------------------------------------- #
def _hash_token(raw: str) -> str:
    """sha256 hex of the FULL raw token (the stored, non-reversible fingerprint).

    A fast deterministic hash is correct here: the token is 256-bit random, so it
    has no brute-forceable structure. argon2's slow KDF defends LOW-entropy
    passwords and would also break the O(1) prefix lookup - it is the wrong tool.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_raw_token() -> tuple[str, str]:
    """Return ``(prefix, raw_token)`` for a fresh token (``skt_<prefix>_<secret>``)."""
    prefix = secrets.token_hex(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return prefix, f"{_TOKEN_SCHEME}_{prefix}_{secret}"


def parse_prefix(raw: str) -> str | None:
    """Extract the row-locator prefix from a presented token, or ``None`` if malformed."""
    if not isinstance(raw, str):
        return None
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != _TOKEN_SCHEME or not parts[1] or not parts[2]:
        return None
    return parts[1]


def cap_scopes(perms: Iterable[str], features: Iterable[str]) -> dict[str, list[str]]:
    """Intersect requested perms/features with the valid vocabularies (drop unknowns).

    A token can only ever CARRY known primitives; anything unknown is silently
    dropped so a typo cannot smuggle in a capability (it simply is not granted).
    Order-stable + deduped so the stored/echoed scope is clean.
    """
    capped_perms = [p for p in dict.fromkeys(perms) if p in _VALID_PERMS]
    capped_features = [f for f in dict.fromkeys(features) if f in _VALID_FEATURES]
    return {"perms": capped_perms, "features": capped_features}


def _principal_from_row(row: dict[str, Any]) -> ScopedPrincipal:
    """Build the capped :class:`ScopedPrincipal` from a token row (no hash reaches it)."""
    scopes = row.get("scopes") or {}
    return ScopedPrincipal(
        token_id=str(row["id"]),
        client_id=str(row["client_id"]),
        perms=frozenset(scopes.get("perms", [])),
        features=frozenset(scopes.get("features", [])),
        tier=str(row.get("tier", "free")),
        expires_at=row.get("expires_at"),
    )


def _is_expired(expires_at: datetime | None, *, now: datetime) -> bool:
    """Whether ``expires_at`` is in the past (a missing expiry counts as expired)."""
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


# --------------------------------------------------------------------------- #
# DB operations
# --------------------------------------------------------------------------- #
def mint_skill_token(
    *,
    client_id: str,
    perms: Iterable[str],
    features: Iterable[str],
    created_by: str,
    tier: str = "free",
    ttl_seconds: int | None = None,
    label: str = "",
) -> dict[str, Any]:
    """Mint a per-client skill token; return the masked row PLUS the raw token ONCE.

    The raw token is returned under the ``token`` key and is UNRECOVERABLE
    afterwards (only its sha256 hash is stored). Runs on ``rls_connection`` bound to
    ``created_by`` so the owner/admin RLS policy is enforced beneath the router
    guard. ``perms``/``features`` are capped to the known vocabularies; an out-of-set
    ``tier`` clamps to ``'free'``; ``ttl_seconds`` defaults from settings.
    """
    scopes = cap_scopes(perms, features)
    safe_tier = tier if tier in _VALID_TIERS else "free"
    ttl = ttl_seconds if ttl_seconds is not None else get_settings().skill_token_ttl_seconds
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    prefix, raw = _new_raw_token()
    token_hash = _hash_token(raw)

    with rls_connection(created_by) as cur:
        cur.execute(
            "insert into public.skill_tokens "
            "(client_id, token_prefix, token_hash, scopes, tier, expires_at, created_by) "
            "values (%s, %s, %s, %s, %s, %s, %s) "
            f"returning {_MASKED_COLS}",
            (client_id, prefix, token_hash, Jsonb(scopes), safe_tier, expires_at, created_by),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - RETURNING always yields the inserted row
        raise SkillTokenError("skill token could not be read back after insert")
    # ``label`` is accepted for API symmetry but not persisted (no column); it is
    # never needed to authenticate. Return the raw token exactly once.
    return {"token": raw, **row}


def verify_skill_token(raw_token: str) -> ScopedPrincipal | None:
    """Authenticate a presented token -> a capped :class:`ScopedPrincipal`, or ``None``.

    Rejects (returns ``None``) a malformed token, an unknown prefix, a wrong secret
    (constant-time compare), a revoked token, or an expired one. On success it bumps
    ``last_used_at`` and returns the scope - NEVER the secret and NEVER the hash.
    Runs on ``privileged_connection`` because the caller presents only a token (it has
    no user identity to bind); this is a trusted, server-only system op.
    """
    prefix = parse_prefix(raw_token)
    if prefix is None:
        return None
    presented_hash = _hash_token(raw_token)
    now = datetime.now(UTC)

    with privileged_connection() as cur:
        cur.execute(
            f"select {_MASKED_COLS}, token_hash from public.skill_tokens "
            "where token_prefix = %s limit 1",
            (prefix,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        # Constant-time compare defeats a timing side-channel on the stored hash.
        if not hmac.compare_digest(str(row["token_hash"]), presented_hash):
            return None
        if row.get("revoked"):
            return None
        if _is_expired(row.get("expires_at"), now=now):
            return None
        # Same txn: record the use. A failure here should not defeat auth, but the
        # single-statement update is trivial and stays inside the verify txn.
        cur.execute(
            "update public.skill_tokens set last_used_at = %s where id = %s",
            (now, row["id"]),
        )
    return _principal_from_row(row)


def revoke_skill_token(user_id: str, token_id: str) -> bool:
    """Revoke a token (owner/admin, RLS-scoped). Returns ``True`` if a row was revoked."""
    with rls_connection(user_id) as cur:
        cur.execute(
            "update public.skill_tokens set revoked = true where id = %s returning id",
            (token_id,),
        )
        return cur.fetchone() is not None


def list_skill_tokens(user_id: str, *, client_id: str | None = None) -> list[dict[str, Any]]:
    """Masked list of skill tokens (owner/admin, RLS-scoped) - never a secret/hash.

    Optionally filtered to one ``client_id``. Ordered newest-first.
    """
    with rls_connection(user_id) as cur:
        if client_id is not None:
            cur.execute(
                f"select {_MASKED_COLS} from public.skill_tokens "
                "where client_id = %s order by created_at desc",
                (client_id,),
            )
        else:
            cur.execute(
                f"select {_MASKED_COLS} from public.skill_tokens order by created_at desc"
            )
        return cur.fetchall()
