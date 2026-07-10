"""Key Vault operations backed by Supabase Vault.

Add/rotate/reveal are privileged: they use the service_role admin client to call
the ``vault_*`` wrapper RPCs (whose EXECUTE is service_role-only). The raw secret
is handled just long enough to store it or return it from a reveal; it is never
written to a public column and never logged. Only a masked preview is persisted.

All calls are blocking (supabase-py is sync); the router offloads with
``asyncio.to_thread``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from supabase import Client


def mask_secret(value: str) -> str:
    """Masked preview of a secret (ported from the frontend ``maskSecret``)."""
    s = value.strip()
    if not s:
        return ""
    last4 = s[-4:]
    head = s[:6] if len(s) > 10 else s[:2]
    return f"{head}••••••••{last4}"


def add_key(
    admin: Client,
    *,
    provider: str,
    label: str,
    secret: str,
    scope: str = "Agency-global",
    site: str | None = None,
) -> dict[str, Any]:
    """Store a secret in the vault and insert its masked metadata row."""
    name = f"aios:{provider}:{uuid.uuid4().hex}"
    created = admin.rpc("vault_create_secret", {"p_secret": secret, "p_name": name}).execute()
    secret_id = str(created.data)
    resp = (
        admin.table("vault_keys")
        .insert(
            {
                "provider": provider,
                "label": label,
                "masked": mask_secret(secret),
                "scope": scope,
                "site": site,
                "secret_id": secret_id,
            }
        )
        .execute()
    )
    rows = cast("list[dict[str, Any]]", resp.data or [])
    return rows[0]


def rotate_key(admin: Client, key_id: str, new_secret: str) -> dict[str, Any] | None:
    """Replace the underlying vault secret and refresh the masked preview + rotated_at."""
    found = admin.table("vault_keys").select("secret_id").eq("id", key_id).limit(1).execute()
    rows = cast("list[dict[str, Any]]", found.data or [])
    if not rows:
        return None
    secret_id = str(rows[0]["secret_id"])
    admin.rpc("vault_update_secret", {"p_id": secret_id, "p_secret": new_secret}).execute()
    updated = (
        admin.table("vault_keys")
        .update({"masked": mask_secret(new_secret), "rotated_at": datetime.now(UTC).isoformat()})
        .eq("id", key_id)
        .execute()
    )
    out = cast("list[dict[str, Any]]", updated.data or [])
    return out[0] if out else None


def reveal_secret(admin: Client, key_id: str) -> str | None:
    """Decrypt and return a secret (super-admin only; enforced in the router)."""
    found = admin.table("vault_keys").select("secret_id").eq("id", key_id).limit(1).execute()
    rows = cast("list[dict[str, Any]]", found.data or [])
    if not rows:
        return None
    secret_id = str(rows[0]["secret_id"])
    revealed = admin.rpc("vault_reveal_secret", {"p_id": secret_id}).execute()
    return None if revealed.data is None else str(revealed.data)
