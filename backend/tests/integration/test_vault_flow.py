"""Integration: the Key Vault re-expressed as app-layer AES-256-GCM over the
privileged psycopg connection (P6A-6 acceptance).

Unit tests exercise the crypto core + service through fakes; this suite is the
SQL-correctness proof for the write/read path that moved off Supabase Vault onto
the privileged (service_role, BYPASSRLS) psycopg connection:

  * ``add_key`` seals a secret and lands a row whose ``secret_sealed`` is BYTEA
    (never the plaintext) with the correct masked preview,
  * the RLS ``VaultRepo.list_keys`` shows the masked row (owner/admin only) and
    the response model carries NO secret,
  * ``reveal_secret`` opens the row and returns the EXACT original plaintext,
  * ``rotate_key`` re-seals and ``reveal_secret`` then returns the NEW secret,
  * a DB-level assertion proves the stored column is sealed bytea: decrypting it
    OUTSIDE the app succeeds only WITH the master key (it is not plaintext).

Runs against the local Postgres named by DATABASE_URL (authenticated) +
DATABASE_ADMIN_URL (service_role) and auto-skips when either DSN or the master
key is unset. Everything seeded is torn down in a finally.
"""

from __future__ import annotations

import base64
import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.db.vault_repo import VaultRepo
from app.schemas.vault import VaultKeyResponse
from app.services.vault import add_key, reveal_secret, rotate_key

pytestmark = pytest.mark.integration

_ORIGINAL = "serper-live-9f2a4c7b8e1d3f0b"
_ROTATED = "serper-live-ROTATED-1a2b3c4d5e6f"


@pytest.fixture(scope="module")
def seed() -> Iterator[dict[str, Any]]:
    rls_dsn = os.environ.get("DATABASE_URL")
    admin_dsn = os.environ.get("DATABASE_ADMIN_URL")
    if not rls_dsn or not admin_dsn:
        pytest.skip("DATABASE_URL and DATABASE_ADMIN_URL required")
    if not os.environ.get("VAULT_MASTER_KEY"):
        pytest.skip("VAULT_MASTER_KEY required")

    rls_pool = build_rls_pool(rls_dsn)
    admin_pool = build_admin_pool(admin_dsn)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    tag = uuid.uuid4().hex[:8]
    admin_uid = str(uuid.uuid4())

    try:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                (admin_uid, f"vault-admin-{tag}@example.com"),
            )
            cur.execute(
                "insert into public.users (id, email, name, role) values (%s, %s, %s, 'admin')",
                (admin_uid, f"vault-admin-{tag}@example.com", f"Vault Admin {tag}"),
            )

        yield {"tag": tag, "admin_uid": admin_uid, "admin_pool": admin_pool}
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            cur.execute("delete from public.vault_keys where created_by = %s", (admin_uid,))
            cur.execute("delete from auth.users where id = %s", (admin_uid,))  # cascades public.users
        clear_pools()
        rls_pool.close()
        admin_pool.close()


def test_add_seals_row_as_bytea_not_plaintext(seed: dict[str, Any]) -> None:
    row = add_key(
        provider="serper", label=f"Prod {seed['tag']}", secret=_ORIGINAL, created_by=seed["admin_uid"]
    )
    assert row["masked"] == "serper••••••••3f0b"
    assert _ORIGINAL not in str(row)  # response is masked metadata only
    assert "secret_sealed" not in row  # never returns the sealed bytes

    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute(
            "select secret_sealed, key_version, masked from public.vault_keys where id = %s",
            (row["id"],),
        )
        stored = cur.fetchone()
    assert stored is not None
    sealed = bytes(stored["secret_sealed"])
    assert isinstance(stored["secret_sealed"], (bytes, memoryview))  # bytea column
    assert sealed != _ORIGINAL.encode()  # NOT plaintext at rest
    assert _ORIGINAL.encode() not in sealed
    assert stored["key_version"] == 1
    assert stored["masked"] == "serper••••••••3f0b"

    # Out-of-app proof: the sealed blob is nonce||ciphertext+tag and can only be
    # recovered WITH the master key. Nonce is 12 bytes; AESGCM authenticates the tag.
    key = base64.b64decode(os.environ["VAULT_MASTER_KEY"])
    nonce, ct = sealed[:12], sealed[12:]
    assert AESGCM(key).decrypt(nonce, ct, None).decode() == _ORIGINAL


def test_list_shows_masked_only(seed: dict[str, Any]) -> None:
    add_key(provider="google", label=f"List {seed['tag']}", secret=_ORIGINAL, created_by=seed["admin_uid"])
    repo = VaultRepo(seed["admin_uid"])  # RLS-scoped read as the admin (owner/admin can select)
    rows = repo.list_keys()
    mine = [r for r in rows if r.get("label") == f"List {seed['tag']}"]
    assert mine, "admin must see the masked row via RLS"
    resp = VaultKeyResponse.from_row(mine[0])
    assert resp.masked == "serper••••••••3f0b"
    assert resp.secret == ""  # the response model never carries a secret


def test_reveal_returns_exact_original_then_rotate_changes_it(seed: dict[str, Any]) -> None:
    row = add_key(
        provider="anthropic", label=f"Rot {seed['tag']}", secret=_ORIGINAL, created_by=seed["admin_uid"]
    )
    key_id = str(row["id"])

    # reveal returns the EXACT original plaintext (byte-for-byte).
    assert reveal_secret(key_id) == _ORIGINAL

    # rotate re-seals; reveal now returns the NEW secret and the mask is refreshed.
    updated = rotate_key(key_id, _ROTATED)
    assert updated is not None
    assert updated["masked"] == "serper••••••••5e6f"
    assert reveal_secret(key_id) == _ROTATED
    assert reveal_secret(key_id) != _ORIGINAL

    # the sealed bytes on disk actually changed (a fresh seal, not the old blob).
    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute("select secret_sealed from public.vault_keys where id = %s", (key_id,))
        sealed = bytes(cur.fetchone()["secret_sealed"])
    assert sealed != _ORIGINAL.encode() and _ROTATED.encode() not in sealed


def test_reveal_missing_returns_none(seed: dict[str, Any]) -> None:
    assert reveal_secret(str(uuid.uuid4())) is None  # unknown id -> None (router 404)
    assert reveal_secret("not-a-uuid") is None  # malformed id -> None, never a crash
