"""Reversible login-credential storage for the owner/admin "resend credentials" tool.

The Team Management screen lets an owner/admin VIEW and COPY a member's login
password at any time (a deliberate product decision - see the module docstring in
:mod:`app.routers.admin_users`). A one-way argon2id hash cannot be shown, so
alongside it we keep the password sealed with AES-256-GCM under ``VAULT_MASTER_KEY``
(env-only, never in Postgres) and open it on demand for an authenticated owner/admin.

Storage reuses the existing ``public.vault_keys`` table (the same sealed-secret store
the API-key vault uses) under a reserved sentinel ``provider`` so NO new migration /
DDL privilege is needed: one row per user, ``label`` = the user id, refreshed on every
password change. These rows are hidden from the Key Vault list (:mod:`app.db.vault_repo`
filters the sentinel out).

Guardrails:

* Authentication NEVER reads the sealed copy. ``verify_password`` consults ONLY the
  argon2id ``password_hash`` in ``auth.users``; the sealed copy is a convenience for
  the reveal tool and nothing else.
* Sealing is BEST-EFFORT: if ``VAULT_MASTER_KEY`` is unset, storage is skipped rather
  than raising, so a missing key never blocks provisioning or a password change - the
  account is simply not revealable until the key is set and the password is next set.
* All writes/reads run on ``privileged_connection`` (service_role) and are blocking;
  the router offloads with ``asyncio.to_thread``. The plaintext is never logged.
"""

from __future__ import annotations

import uuid

from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.services.passwords import hash_password
from app.services.vault import (
    VaultNotConfiguredError,
    mask_secret,
    open_sealed,
    seal_value,
)

logger = get_logger("app.login_credentials")

# Reserved provider for a member's own login password. The double-underscore keeps
# it out of the real integration-provider namespace; vault_repo hides it from the list.
LOGIN_PROVIDER = "__login__"


def _as_uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, AttributeError, TypeError):
        return None


def store_login_password(user_id: str, plaintext: str) -> None:
    """Seal and persist a member's login password (one row per user; refreshed).

    Best-effort on the vault key: a missing ``VAULT_MASTER_KEY`` skips storage (the
    account just won't be revealable) instead of raising. Delete-then-insert keeps a
    single current row per user under the sentinel provider.
    """
    try:
        sealed = seal_value(plaintext)
    except VaultNotConfiguredError:
        logger.warning("login_password_seal_skipped_no_vault_key")
        return
    with privileged_connection() as cur:
        cur.execute(
            "delete from public.vault_keys where provider = %s and label = %s",
            (LOGIN_PROVIDER, str(user_id)),
        )
        cur.execute(
            "insert into public.vault_keys (provider, label, masked, secret_sealed, key_version, kind) "
            "values (%s, %s, %s, %s, %s, %s)",
            (LOGIN_PROVIDER, str(user_id), mask_secret(plaintext), sealed, 1, "client_access"),
        )


def set_password(user_id: str, plaintext: str) -> bool:
    """Set a member's login password: update the argon2id hash AND the sealed copy.

    Also clears ``must_reset`` so an admin-issued password logs in directly. Returns
    ``False`` for an unknown/malformed id.
    """
    parsed = _as_uuid(user_id)
    if parsed is None:
        return False
    password_hash = hash_password(plaintext)
    with privileged_connection() as cur:
        cur.execute(
            "update auth.users set password_hash = %s where id = %s", (password_hash, parsed)
        )
        if cur.rowcount == 0:
            return False
        cur.execute("update public.users set must_reset = false where id = %s", (parsed,))
    store_login_password(str(user_id), plaintext)
    return True


def reveal_password(user_id: str) -> str | None:
    """Open the sealed login password, or ``None`` if none stored / unknown id.

    ``None`` covers a malformed id, no stored row (never captured, or the vault key
    was unset when the password was set), all rendered identically as "not captured".
    A stored blob that fails authentication raises ``VaultSecretError`` - never a leak.
    """
    parsed = _as_uuid(user_id)
    if parsed is None:
        return None
    with privileged_connection() as cur:
        cur.execute(
            "select secret_sealed from public.vault_keys where provider = %s and label = %s "
            "order by created_at desc limit 1",
            (LOGIN_PROVIDER, str(user_id)),
        )
        row = cur.fetchone()
    if row is None or row["secret_sealed"] is None:
        return None
    return open_sealed(row["secret_sealed"])
