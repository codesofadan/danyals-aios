"""Key Vault operations backed by APP-LAYER AES-256-GCM over local PostgreSQL.

Secrets are sealed IN THE APPLICATION with ``cryptography``'s AESGCM using
``VAULT_MASTER_KEY`` -- a base64-encoded 32-byte key held ONLY in the process
environment, NEVER in Postgres. The database stores ``nonce || ciphertext+tag``
(the ``secret_sealed`` bytea column) plus masked metadata, so a database dump
yields nothing usable and there is NO decrypt path in SQL. This replaces the
former Supabase-Vault design (the ``vault`` schema wrappers + the ``secret_id``
column are gone).

Security guardrails (read before touching this file):

* The raw secret is handled just long enough to seal it on write or to open it
  on an owner-only reveal; it is NEVER written to a plaintext column, NEVER
  returned in a list/metadata response, and NEVER logged (not the plaintext, not
  the sealed bytes, not the master key).
* A tampered, truncated, or wrong-key blob fails GCM authentication
  (``InvalidTag``) and is surfaced as :class:`VaultSecretError` -- the reveal
  path can never leak a partial or unauthenticated plaintext.
* Reveal is owner-only, enforced in the router (``require_owner``); the
  ciphertext never leaves the server and is never decrypted in SQL.

Writes/reads run on ``privileged_connection`` (role ``service_role``, BYPASSRLS):
the raw secret lives only behind this server-only seam. All calls are blocking
(psycopg is sync); the router offloads with ``asyncio.to_thread``.

``kind`` (0041) classifies WHAT SPECIES of secret a row holds -- ``api_key`` (an
agency integration credential; the default every pre-0041 row carries) or
``client_access`` (a client's own login, collected by the client_onboarding
module). It is orthogonal metadata: it classifies, it GRANTS NOTHING. Every
guardrail above applies identically to both kinds -- same master key, same
sealing, same masked list, same single owner-only reveal path.
"""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.db.database import privileged_connection

# AES-GCM is used with a 12-byte (96-bit) random nonce -- the size NIST SP 800-38D
# recommends for GCM, and the value AESGCM is optimized for. The sealed blob is
# ``nonce(12) || ciphertext || tag(16)``; the tag is appended by AESGCM.encrypt.
_NONCE_BYTES = 12
_KEY_BYTES = 32  # AES-256

# The vault_kind enum (0041) verbatim. ``api_key`` is the DEFAULT in both Python
# and Postgres, so every existing caller and every existing row keeps its exact
# current meaning without passing or storing anything new.
VaultKind = Literal["api_key", "client_access"]


class VaultNotConfiguredError(RuntimeError):
    """Raised when ``VAULT_MASTER_KEY`` is unset/malformed (router maps to 503)."""


class VaultSecretError(RuntimeError):
    """Raised when a sealed blob fails to open (tampered, truncated, wrong key).

    Deliberately carries NO plaintext and NO ciphertext -- opening a bad blob
    must never leak an unauthenticated or partial secret.
    """


def mask_secret(value: str) -> str:
    """Masked preview of a secret (ported from the frontend ``maskSecret``)."""
    s = value.strip()
    if not s:
        return ""
    last4 = s[-4:]
    head = s[:6] if len(s) > 10 else s[:2]
    return f"{head}••••••••{last4}"


def _master_key() -> bytes:
    """Return the 32-byte AES-256 key from ``VAULT_MASTER_KEY`` or raise.

    The key is sourced from process env only (``settings.vault_master_key``),
    base64-decoded here. A missing or wrong-length key is a clean
    ``VaultNotConfiguredError`` -- never a partial or silent fallback.
    """
    raw = get_settings().vault_master_key
    if raw is None:
        raise VaultNotConfiguredError("VAULT_MASTER_KEY is not configured")
    try:
        key = base64.b64decode(raw.get_secret_value(), validate=True)
    except (ValueError, TypeError) as exc:
        raise VaultNotConfiguredError("VAULT_MASTER_KEY must be valid base64") from exc
    if len(key) != _KEY_BYTES:
        raise VaultNotConfiguredError("VAULT_MASTER_KEY must decode to 32 bytes")
    return key


def _seal(plaintext: str) -> bytes:
    """Seal a plaintext secret -> ``nonce || ciphertext+tag`` (fresh random nonce)."""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_master_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def _open(sealed: bytes) -> str:
    """Open a sealed blob -> the original plaintext, or raise ``VaultSecretError``.

    Any authentication failure (tamper, truncation, wrong key) raises and yields
    NO plaintext; a blob shorter than a nonce+tag can never be a valid secret.
    """
    blob = bytes(sealed)
    if len(blob) <= _NONCE_BYTES:
        raise VaultSecretError("sealed secret is too short to be valid")
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        plaintext = AESGCM(_master_key()).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise VaultSecretError("sealed secret failed authentication") from exc
    return plaintext.decode("utf-8")


def seal_value(plaintext: str) -> bytes:
    """Public seal: ``plaintext`` -> ``nonce || ciphertext+tag`` under the master key.

    A thin wrapper over the internal :func:`_seal` so callers OUTSIDE the API-key
    vault (e.g. the login-credential store) reuse the exact same AES-256-GCM
    construction and master key without touching ``vault_keys``. Raises
    :class:`VaultNotConfiguredError` when ``VAULT_MASTER_KEY`` is unset/malformed.
    """
    return _seal(plaintext)


def open_sealed(sealed: bytes) -> str:
    """Public open: a blob produced by :func:`seal_value` -> its plaintext.

    Raises :class:`VaultSecretError` on any authentication failure (tamper,
    truncation, wrong key) and yields NO plaintext in that case.
    """
    return _open(sealed)


def _as_uuid(key_id: str) -> uuid.UUID | None:
    """Parse ``key_id`` as a UUID or return ``None`` (a malformed id -> 404)."""
    try:
        return uuid.UUID(str(key_id))
    except (ValueError, AttributeError, TypeError):
        return None


def add_key(
    *,
    provider: str,
    label: str,
    secret: str,
    created_by: str | None = None,
    kind: VaultKind = "api_key",
) -> dict[str, Any]:
    """Seal a secret and insert its masked metadata row; returns masked metadata.

    The response carries ONLY masked metadata -- never the plaintext or the
    sealed bytes. Column names are static; every value is a bound parameter.

    ``kind`` classifies the secret (``api_key`` -- an agency integration
    credential, the default -- or ``client_access``, a client login collected by
    the onboarding module). It changes NOTHING about how the secret is handled:
    both kinds are sealed with the same master key and the same AES-256-GCM
    construction, land in the same ``secret_sealed`` bytea, are listed equally
    masked, and are openable only through the one owner-only ``reveal_secret``
    path. It is returned in the masked metadata so a caller can tell the two
    populations apart WITHOUT any new access to the sealed bytes.
    """
    sealed = _seal(secret)
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.vault_keys "
            "(provider, label, masked, secret_sealed, key_version, created_by, kind) "
            "values (%s, %s, %s, %s, %s, %s, %s) "
            "returning id, provider, label, masked, kind, created_at",
            (provider, label, mask_secret(secret), sealed, 1, created_by, kind),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - ``returning`` always yields the row
        raise RuntimeError("vault key could not be read back after insert")
    return row


def rotate_key(key_id: str, new_secret: str) -> dict[str, Any] | None:
    """Re-seal a key's secret and refresh its masked preview; returns metadata.

    ``key_version`` (the master-key version) is unchanged: rotating the SECRET
    does not rotate the master key. ``kind`` is likewise unchanged and for the
    same reason: replacing a secret's VALUE does not change its SPECIES -- a
    rotated client login is still a client login. It is only read back into the
    returned metadata. Returns ``None`` for a missing/malformed id.
    """
    parsed = _as_uuid(key_id)
    if parsed is None:
        return None
    sealed = _seal(new_secret)
    with privileged_connection() as cur:
        cur.execute(
            "update public.vault_keys "
            "set secret_sealed = %s, masked = %s, updated_at = now() "
            "where id = %s "
            "returning id, provider, label, masked, kind, created_at",
            (sealed, mask_secret(new_secret), parsed),
        )
        row = cur.fetchone()
    return row


def find_secret(*, provider: str, label: str) -> str | None:
    """Reveal a secret by ``(provider, label)`` rather than by row id.

    This is the SERVER-SIDE lookup a worker uses to build a per-client, per-platform
    credential (e.g. ``provider="web2:WordPress.com"``, ``label=client_id``) without
    a user-facing id round-trip -- there is no dashboard "reveal" click in this path,
    it is the publish pipeline building its own client. Same guardrails as
    ``reveal_secret``: never logs, raises :class:`VaultSecretError` on a tampered
    blob, and returns ``None`` (not an exception) for "no such row" -- an unconfigured
    credential is the ordinary, expected degraded case every off-page seam already
    handles, not a fault.

    The most-recently-added matching row wins (mirrors how a rotated key naturally
    supersedes an older one without a separate "current" flag).
    """
    with privileged_connection() as cur:
        cur.execute(
            "select secret_sealed from public.vault_keys "
            "where provider = %s and label = %s order by created_at desc limit 1",
            (provider, label),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _open(row["secret_sealed"])


def reveal_secret(key_id: str) -> str | None:
    """Open and return a secret (super-admin only; enforced in the router).

    Returns ``None`` when the id is unknown/malformed (router -> 404). A stored
    blob that fails authentication raises ``VaultSecretError`` -- never a leak.
    """
    parsed = _as_uuid(key_id)
    if parsed is None:
        return None
    with privileged_connection() as cur:
        cur.execute(
            "select secret_sealed from public.vault_keys where id = %s limit 1",
            (parsed,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _open(row["secret_sealed"])
