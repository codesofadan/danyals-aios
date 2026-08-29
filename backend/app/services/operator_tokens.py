"""Mint and verify the citation extension's device credential (0112).

Shaped after ``app/services/skill_tokens.py`` - sha256 of the full token, an indexed
prefix to locate the row, constant-time comparison, a mandatory expiry - but keyed to a
USER rather than a client, because every completion the extension records has to be
attributable to a named operator.

WHAT MAKES THIS SAFE IS NOT THIS FILE. It is that the scope vocabulary is CLOSED and
capped at mint: only ``citation_queue`` and ``citation_credential`` can ever be stored, so
there is no scope in existence that reaches the vault, the client roster or the cost
dials. Containment is structural, not a matter of which routes remember to check.

The token is also not a JWT, so ``get_current_user`` rejects it on every other route by
construction rather than by policy.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.database import privileged_connection, rls_connection
from app.logging_setup import get_logger

logger = get_logger("app.services.operator_tokens")

_TOKEN_SCHEME = "aop"  # AIOS OPerator
_PREFIX_BYTES = 6
_SECRET_BYTES = 32

# THE CLOSED VOCABULARY. Anything outside this set is dropped at mint, so a typo grants
# nothing rather than smuggling in a capability, and no future route can be reached by a
# scope that cannot be stored.
EXTENSION_SCOPES: frozenset[str] = frozenset({"citation_queue", "citation_credential"})

# One shift. Contrast `skill_token_ttl_seconds`' 30 days: a skill token runs in a
# developer's own terminal, this one sits in `chrome.storage.local` - plaintext on disk,
# on a machine signed into ~50 third-party directories all day.
DEFAULT_TTL_SECONDS = 12 * 60 * 60
MAX_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class OperatorPrincipal:
    """A verified extension caller: which person, and what they may reach."""

    token_id: str
    user_id: str
    scopes: frozenset[str]
    expires_at: datetime | None
    # When the token was minted, for the per-user revocation-epoch check the async
    # dependency performs. A password change or suspension moves that epoch, which
    # invalidates every token issued before it.
    issued_at: int | None = None

    def has(self, scope: str) -> bool:
        return scope in self.scopes


# --------------------------------------------------------------------------- #
# Pure helpers (no DB).
# --------------------------------------------------------------------------- #
def hash_token(raw: str) -> str:
    """sha256 hex of the FULL raw token - the stored, non-reversible fingerprint."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_raw_token() -> tuple[str, str]:
    """``(prefix, raw)`` for a fresh token, shaped ``aop_<prefix>_<secret>``."""
    prefix = secrets.token_hex(_PREFIX_BYTES)
    return prefix, f"{_TOKEN_SCHEME}_{prefix}_{secrets.token_urlsafe(_SECRET_BYTES)}"


def parse_prefix(raw: str) -> str | None:
    """The row-locator prefix from a presented token, or ``None`` if malformed."""
    if not isinstance(raw, str):
        return None
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != _TOKEN_SCHEME or not parts[1] or not parts[2]:
        return None
    return parts[1]


def cap_scopes(requested: Iterable[str]) -> list[str]:
    """Intersect requested scopes with the closed vocabulary, order-stable and deduped."""
    return [s for s in dict.fromkeys(requested) if s in EXTENSION_SCOPES]


def is_expired(expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Whether the expiry has passed. A MISSING expiry counts as expired, so a row that
    somehow lost its timestamp fails closed rather than becoming permanent."""
    if expires_at is None:
        return True
    now = now or datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


# --------------------------------------------------------------------------- #
# Database operations.
# --------------------------------------------------------------------------- #
def mint_operator_token(
    *,
    user_id: str,
    actor_id: str,
    scopes: Iterable[str] = ("citation_queue",),
    device_label: str = "",
    label: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[dict[str, Any], str]:
    """Create a token. Returns ``(masked_row, raw_token)``.

    THE RAW TOKEN IS RETURNED ONCE and never stored - only its sha256 is. That is the
    GitHub-PAT model 0030 already committed this codebase to, and it is why pairing is a
    copy-paste rather than a device flow: a device flow needs an UNAUTHENTICATED
    pair-start endpoint, which would mean punching an entry into `_PUBLIC_PREFIXES` in
    `tests/test_route_auth_guard.py` - deliberately weakening the sweep that asserts every
    route 401s unauthenticated, for the convenience of a handful of internal operators.

    `citation_credential` is NOT granted by default. It has to be asked for, because
    revealing a directory password is a different act from working the queue.
    """
    ttl = max(60, min(int(ttl_seconds), MAX_TTL_SECONDS))
    prefix, raw = new_raw_token()
    capped = cap_scopes(scopes)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

    import json as _json

    with rls_connection(actor_id) as cur:
        cur.execute(
            "insert into public.operator_tokens "
            "  (user_id, token_prefix, token_hash, scopes, label, device_label, "
            "   expires_at, created_by) "
            "values (%s, %s, %s, %s::jsonb, %s, %s, %s, %s) "
            "returning id, user_id, token_prefix, scopes, label, device_label, "
            "          expires_at, revoked, created_at",
            (
                user_id, prefix, hash_token(raw), _json.dumps(capped),
                label[:120], device_label[:120], expires_at, actor_id,
            ),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - an RLS refusal returns no row
        raise PermissionError("not permitted to mint an operator token for that user")
    logger.info("operator_token_minted", token_id=str(row["id"]), scopes=capped)
    return dict(row), raw


def verify_operator_token(raw: str) -> OperatorPrincipal | None:
    """Verify a presented token, or ``None``. NEVER raises, never logs the token.

    Runs on the privileged connection because the caller has no identity yet - that is
    what this call establishes. Every rejection returns the same ``None`` so a caller
    cannot distinguish "no such prefix" from "wrong secret" from "expired".

    THREE POSTGRES CHECKS happen here:
      1. the row exists and the full-token hash matches, compared in constant time;
      2. it is neither revoked nor expired;
      3. the user is still active. Redis fails OPEN by contract, so a suspension has to
         be enforced somewhere that does not.

    The fourth - the per-user revocation epoch in `token_denylist` - is deliberately NOT
    done here. It is an async Redis read, and this function is sync because everything
    else it touches is psycopg; awaiting from here would either block the event loop or
    force every caller to be async. The dependency that wraps this runs it in a thread
    and then awaits the epoch check, which keeps both halves in their right world.
    `issued_at` is returned on the principal so the caller can make that check.
    """
    prefix = parse_prefix(raw)
    if prefix is None:
        return None
    try:
        with privileged_connection() as cur:
            cur.execute(
                "select t.id, t.user_id, t.token_hash, t.scopes, t.expires_at, t.revoked, "
                "       t.created_at, u.status "
                "from public.operator_tokens t "
                "join public.users u on u.id = t.user_id "
                "where t.token_prefix = %s limit 1",
                (prefix,),
            )
            row = cur.fetchone()
    except Exception:
        logger.warning("operator_token_lookup_failed")
        return None
    if row is None:
        return None
    if not hmac.compare_digest(str(row["token_hash"]), hash_token(raw)):
        return None
    if bool(row["revoked"]) or is_expired(row["expires_at"]):
        return None
    if str(row.get("status") or "") == "suspended":
        return None

    created = row.get("created_at")
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)

    scopes = row.get("scopes") or []
    principal = OperatorPrincipal(
        token_id=str(row["id"]),
        user_id=str(row["user_id"]),
        scopes=frozenset(str(s) for s in scopes),
        expires_at=row.get("expires_at"),
        issued_at=int(created.timestamp()) if created is not None else None,
    )
    _touch(principal.token_id)
    return principal


def _touch(token_id: str) -> None:
    """Best-effort last-used stamp. A failure here must never fail the request."""
    try:
        with privileged_connection() as cur:
            cur.execute(
                "update public.operator_tokens set last_used_at = now() where id = %s",
                (token_id,),
            )
    except Exception:
        logger.info("operator_token_touch_failed", token_id=token_id)


def revoke_operator_token(*, actor_id: str, token_id: str) -> bool:
    """Revoke one token. RLS decides who may: its owner, or an owner/admin."""
    with rls_connection(actor_id) as cur:
        cur.execute(
            "update public.operator_tokens set revoked = true where id = %s and not revoked",
            (token_id,),
        )
        return (cur.rowcount or 0) > 0


def list_operator_tokens(*, actor_id: str) -> list[dict[str, Any]]:
    """Masked metadata only - the hash never leaves the database."""
    with rls_connection(actor_id) as cur:
        cur.execute(
            "select id, user_id, token_prefix, scopes, label, device_label, expires_at, "
            "       revoked, last_used_at, created_at "
            "from public.operator_tokens order by created_at desc limit 100"
        )
        return [dict(r) for r in cur.fetchall()]
