"""Mint, verify and ROTATE the citation extension's device credential (0112, 0131).

Shaped after ``app/services/skill_tokens.py`` - sha256 of the full token, an indexed
prefix to locate the row, constant-time comparison, a mandatory expiry - but keyed to a
USER rather than a client, because every completion the extension records has to be
attributable to a named operator.

WHAT MAKES THIS SAFE IS NOT THIS FILE. It is that the scope vocabulary is CLOSED and
capped at mint: only the seven citation/web2/profile values below can ever be stored, so
there is no scope in existence that reaches the vault, the client roster or the cost
dials. Containment is structural, not a matter of which routes remember to check.

The token is also not a JWT, so ``get_current_user`` rejects it on every other route by
construction rather than by policy.

0131 adds the INSTALLATION identity: every token chains under a 30-day
``extension_installs`` row, and instead of re-pairing every shift the extension exchanges
its live token for a successor (``rotate_operator_token``). A presented token whose
``rotated_at`` is set is by definition a replay or a theft - the legitimate holder
already holds the successor - and the response is to revoke every token on that install
and the install itself. Blast radius is the DEVICE: the per-user Redis epoch is
deliberately not bumped, so the operator's dashboard session survives.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import Cursor
from psycopg.rows import DictRow

from app.db.database import privileged_connection, rls_connection
from app.logging_setup import get_logger
from app.services.activity import log_activity

logger = get_logger("app.services.operator_tokens")

_TOKEN_SCHEME = "aop"  # AIOS OPerator
_PREFIX_BYTES = 6
_SECRET_BYTES = 32

# THE CLOSED VOCABULARY. Anything outside this set is dropped at mint, so a typo grants
# nothing rather than smuggling in a capability, and no future route can be reached by a
# scope that cannot be stored. 0131 widened it from two values to seven: the granular
# read/write splits the next stage's route guards consume, plus the legacy umbrella
# `citation_queue` so existing paired tokens keep working until natural 12h expiry.
EXTENSION_SCOPES: frozenset[str] = frozenset(
    {
        "citation_queue",
        "citation_credential",
        "citation_queue:read",
        "citation_queue:write",
        "client_profile:read",
        "web2_queue:read",
        "web2_queue:write",
    }
)

# What a fresh pairing gets when it asks for nothing in particular: the working set for
# a citation shift, granular from day one. `citation_credential` and the web2 scopes are
# NOT here - revealing a directory password or touching the web2 queue are different
# acts and have to be asked for.
DEFAULT_MINT_SCOPES: tuple[str, ...] = (
    "citation_queue:read",
    "citation_queue:write",
    "client_profile:read",
)

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
    # The 30-day installation this token chains under (0131). None only for a legacy
    # token minted before installs existed; those age out within 12 hours.
    install_id: str | None = None

    def has(self, scope: str) -> bool:
        """Scope check, with ONE-WAY legacy mapping (0131).

        The legacy umbrella `citation_queue` satisfies both granular halves, so a token
        paired before the split keeps working until its natural 12h expiry - no forced
        re-pair. The mapping never runs the other way: a granular `:read` does not
        satisfy `:write`, and no granular value satisfies a different granular value.
        """
        if scope in self.scopes:
            return True
        if scope in ("citation_queue:read", "citation_queue:write"):
            return "citation_queue" in self.scopes
        return False


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
def _resolve_install(
    cur: Cursor[DictRow], *, user_id: str, install_id: str | None, device_label: str
) -> dict[str, Any]:
    """The install this mint binds to: the caller's existing one, verified, or a fresh row.

    A supplied ``install_id`` must exist, BELONG TO THE TOKEN'S USER, be unrevoked and
    inside its pairing window - anything else raises ``LookupError`` rather than quietly
    minting under a stranger's (or a dead) identity."""
    if install_id:
        try:
            canonical = str(uuid.UUID(install_id))
        except ValueError:
            raise LookupError("no such extension install") from None
        cur.execute(
            "select id, user_id, device_label, pairing_expires_at, revoked "
            "from public.extension_installs where id = %s limit 1",
            (canonical,),
        )
        row = cur.fetchone()
        if (
            row is None
            or str(row["user_id"]) != str(user_id)
            or bool(row["revoked"])
            or is_expired(row["pairing_expires_at"])
        ):
            raise LookupError("that extension install is unknown, revoked, or past its pairing window")
        return dict(row)
    cur.execute(
        "insert into public.extension_installs (user_id, device_label) "
        "values (%s, %s) "
        "returning id, user_id, device_label, pairing_expires_at, revoked",
        (user_id, device_label[:120]),
    )
    created = cur.fetchone()
    if created is None:  # pragma: no cover - an RLS refusal returns no row
        raise PermissionError("not permitted to register an extension install for that user")
    return dict(created)


def _insert_token_row(
    cur: Cursor[DictRow],
    *,
    user_id: str,
    prefix: str,
    token_hash: str,
    scopes: list[str],
    label: str,
    device_label: str,
    expires_at: datetime,
    created_by: str,
    install_id: str | None,
) -> DictRow | None:
    """THE one mint statement, shared by pairing (RLS cursor) and rotation (privileged
    cursor inside the rotation transaction) so the two paths cannot drift."""
    cur.execute(
        "insert into public.operator_tokens "
        "  (user_id, token_prefix, token_hash, scopes, label, device_label, "
        "   expires_at, created_by, install_id) "
        "values (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) "
        "returning id, user_id, token_prefix, scopes, label, device_label, "
        "          expires_at, revoked, created_at, install_id",
        (
            user_id, prefix, token_hash, json.dumps(scopes),
            label[:120], device_label[:120], expires_at, created_by, install_id,
        ),
    )
    return cur.fetchone()


def mint_operator_token(
    *,
    user_id: str,
    actor_id: str,
    scopes: Iterable[str] = DEFAULT_MINT_SCOPES,
    device_label: str = "",
    label: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    install_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Create a token bound to an installation. Returns ``(masked_row, raw_token)``.

    THE RAW TOKEN IS RETURNED ONCE and never stored - only its sha256 is. That is the
    GitHub-PAT model 0030 already committed this codebase to, and it is why pairing is a
    copy-paste rather than a device flow: a device flow needs an UNAUTHENTICATED
    pair-start endpoint, which would mean punching an entry into `_PUBLIC_PREFIXES` in
    `tests/test_route_auth_guard.py` - deliberately weakening the sweep that asserts every
    route 401s unauthenticated, for the convenience of a handful of internal operators.

    Every mint binds an ``extension_installs`` row: a fresh one by default, or - when the
    request carries an ``install_id`` the caller owns - the existing identity, so
    re-pairing mid-window does not multiply installs. `citation_credential` is NOT
    granted by default: revealing a directory password is a different act from working
    the queue.
    """
    ttl = max(60, min(int(ttl_seconds), MAX_TTL_SECONDS))
    prefix, raw = new_raw_token()
    capped = cap_scopes(scopes)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

    with rls_connection(actor_id) as cur:
        install = _resolve_install(
            cur, user_id=user_id, install_id=install_id, device_label=device_label
        )
        row = _insert_token_row(
            cur,
            user_id=user_id,
            prefix=prefix,
            token_hash=hash_token(raw),
            scopes=capped,
            label=label,
            device_label=device_label,
            expires_at=expires_at,
            created_by=actor_id,
            install_id=str(install["id"]),
        )
    if row is None:  # pragma: no cover - an RLS refusal returns no row
        raise PermissionError("not permitted to mint an operator token for that user")
    out = dict(row)
    out["pairing_expires_at"] = install["pairing_expires_at"]
    logger.info(
        "operator_token_minted",
        token_id=str(out["id"]), install_id=str(install["id"]), scopes=capped,
    )
    return out, raw


def verify_operator_token(raw: str) -> OperatorPrincipal | None:
    """Verify a presented token, or ``None``. NEVER raises, never logs the token.

    Runs on the privileged connection because the caller has no identity yet - that is
    what this call establishes. Every rejection returns the same ``None`` so a caller
    cannot distinguish "no such prefix" from "wrong secret" from "expired".

    FOUR POSTGRES CHECKS happen here:
      1. the row exists and the full-token hash matches, compared in constant time;
      2. the token has NOT BEEN ROTATED. A rotated token's rightful holder already holds
         the successor, so presenting the predecessor is a replay or a theft - the
         handler revokes every token on that install plus the install itself, records
         the event, and returns the same ``None`` as any other rejection (the thief
         learns nothing). The per-user Redis epoch is deliberately left alone: the blast
         radius is the DEVICE, not the operator's dashboard session;
      3. it is neither revoked nor expired, and its install (if any) is not revoked;
      4. the user is still active. Redis fails OPEN by contract, so a suspension has to
         be enforced somewhere that does not.

    The fifth - the per-user revocation epoch in `token_denylist` - is deliberately NOT
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
                "       t.created_at, t.rotated_at, t.install_id, t.device_label, "
                "       u.status, u.name, u.avatar_color, "
                "       i.revoked as install_revoked "
                "from public.operator_tokens t "
                "join public.users u on u.id = t.user_id "
                "left join public.extension_installs i on i.id = t.install_id "
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
    if row.get("rotated_at") is not None:
        _handle_rotated_token_reuse(dict(row))
        return None
    if bool(row["revoked"]) or is_expired(row["expires_at"]) or bool(row.get("install_revoked")):
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
        install_id=str(row["install_id"]) if row.get("install_id") else None,
    )
    _touch(principal.token_id)
    return principal


def _handle_rotated_token_reuse(row: dict[str, Any]) -> None:
    """A rotated token came back: revoke the whole install chain. Best-effort, silent.

    Called from the verifier, so it must swallow every failure - a broken revocation
    write must degrade to a plain rejection, never to a 500 on the request path."""
    install_id = str(row["install_id"]) if row.get("install_id") else None
    try:
        with privileged_connection() as cur:
            if install_id:
                cur.execute(
                    "update public.operator_tokens set revoked = true "
                    "where install_id = %s and not revoked",
                    (install_id,),
                )
                cur.execute(
                    "update public.extension_installs set revoked = true where id = %s",
                    (install_id,),
                )
            else:  # pragma: no cover - a rotated token always has an install
                cur.execute(
                    "update public.operator_tokens set revoked = true where id = %s",
                    (str(row["id"]),),
                )
    except Exception:
        logger.warning("operator_token_reuse_revocation_failed", token_id=str(row["id"]))
        return
    logger.warning(
        "operator_token_reuse_detected",
        token_id=str(row["id"]), install_id=install_id or "",
    )
    _record_reuse_activity(row, install_id)


def _record_reuse_activity(row: dict[str, Any], install_id: str | None) -> None:
    """One audit row, attributed to the token's user. Never fails the caller."""
    try:
        log_activity(
            actor_id=str(row["user_id"]),
            actor_name=str(row.get("name") or "Unknown operator"),
            actor_color=str(row.get("avatar_color") or "#7B69EE"),
            kind="access",
            action="extension token replay detected; the whole install was revoked",
            target=str(row.get("device_label") or "unnamed device"),
            meta=f"install={install_id or 'none'} token={row['id']}",
        )
    except Exception:
        logger.warning("operator_token_reuse_activity_failed")


def rotate_operator_token(raw: str) -> tuple[dict[str, Any], str] | None:
    """Exchange a live token for its 12h successor, in ONE privileged transaction.

    The presented token gets the FULL verification (constant-time hash compare, revoked,
    expiry, user suspended), then its install must be live: a revoked install or one past
    ``pairing_expires_at`` refuses, because rotation extends a pairing - it never
    resurrects or outlives one. On success the new row copies the old token's user,
    scopes, labels and install; the old row is marked ``revoked + rotated_to +
    rotated_at``; the install's ``last_seen_at`` is touched; and the raw successor is
    returned ONCE.

    Replaying an already-rotated token here trips the same theft response as the
    verifier: every token on the install and the install itself are revoked, inside this
    same transaction. The row is locked ``for update`` so two concurrent rotations of
    one token cannot both mint a successor.

    Returns ``(masked_row, raw_token)`` or ``None``; like the verifier it never raises
    and every refusal is indistinguishable.
    """
    prefix = parse_prefix(raw)
    if prefix is None:
        return None
    reuse_row: dict[str, Any] | None = None
    try:
        with privileged_connection() as cur:
            cur.execute(
                "select t.id, t.user_id, t.token_hash, t.scopes, t.expires_at, t.revoked, "
                "       t.rotated_at, t.install_id, t.label, t.device_label, "
                "       u.status, u.name, u.avatar_color, "
                "       i.revoked as install_revoked, i.pairing_expires_at "
                "from public.operator_tokens t "
                "join public.users u on u.id = t.user_id "
                "left join public.extension_installs i on i.id = t.install_id "
                "where t.token_prefix = %s "
                "limit 1 for update of t",
                (prefix,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if not hmac.compare_digest(str(row["token_hash"]), hash_token(raw)):
                return None
            install_id = str(row["install_id"]) if row.get("install_id") else None
            if row.get("rotated_at") is not None:
                # Theft signal - same response as the verifier, in this transaction.
                if install_id:
                    cur.execute(
                        "update public.operator_tokens set revoked = true "
                        "where install_id = %s and not revoked",
                        (install_id,),
                    )
                    cur.execute(
                        "update public.extension_installs set revoked = true where id = %s",
                        (install_id,),
                    )
                reuse_row = dict(row)
            else:
                if bool(row["revoked"]) or is_expired(row["expires_at"]):
                    return None
                if str(row.get("status") or "") == "suspended":
                    return None
                # A legacy token with no install cannot rotate - it ages out instead.
                if (
                    install_id is None
                    or bool(row.get("install_revoked"))
                    or is_expired(row.get("pairing_expires_at"))
                ):
                    return None
                new_prefix, new_raw = new_raw_token()
                scopes = [str(s) for s in (row.get("scopes") or [])]
                new_row = _insert_token_row(
                    cur,
                    user_id=str(row["user_id"]),
                    prefix=new_prefix,
                    token_hash=hash_token(new_raw),
                    scopes=scopes,
                    label=str(row.get("label") or ""),
                    device_label=str(row.get("device_label") or ""),
                    expires_at=datetime.now(UTC) + timedelta(seconds=DEFAULT_TTL_SECONDS),
                    created_by=str(row["user_id"]),
                    install_id=install_id,
                )
                if new_row is None:  # pragma: no cover - privileged insert returns a row
                    return None
                cur.execute(
                    "update public.operator_tokens "
                    "set revoked = true, rotated_to = %s, rotated_at = now() "
                    "where id = %s",
                    (str(new_row["id"]), str(row["id"])),
                )
                cur.execute(
                    "update public.extension_installs set last_seen_at = now() where id = %s",
                    (install_id,),
                )
                out = dict(new_row)
                out["pairing_expires_at"] = row.get("pairing_expires_at")
    except Exception:
        logger.warning("operator_token_rotate_failed")
        return None
    if reuse_row is not None:
        logger.warning(
            "operator_token_reuse_detected",
            token_id=str(reuse_row["id"]), install_id=str(reuse_row.get("install_id") or ""),
        )
        _record_reuse_activity(reuse_row, str(reuse_row["install_id"]) if reuse_row.get("install_id") else None)
        return None
    logger.info(
        "operator_token_rotated",
        old_token_id=str(row["id"]), new_token_id=str(out["id"]), install_id=install_id,
    )
    return out, new_raw


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
    """Masked metadata only - the hash never leaves the database. Each row carries its
    install's identity (id + pairing window) so the board can show WHICH device a token
    belongs to and when its 30-day pairing runs out."""
    with rls_connection(actor_id) as cur:
        cur.execute(
            "select t.id, t.user_id, t.token_prefix, t.scopes, t.label, t.device_label, "
            "       t.expires_at, t.revoked, t.last_used_at, t.created_at, t.install_id, "
            "       i.pairing_expires_at, i.last_seen_at as install_last_seen_at "
            "from public.operator_tokens t "
            "left join public.extension_installs i on i.id = t.install_id "
            "order by t.created_at desc limit 100"
        )
        return [dict(r) for r in cur.fetchall()]
