"""Key Vault endpoints.

- list (masked) / add / rotate require ``manage_vault`` (owner/admin).
- reveal (the raw secret) is SUPER-ADMIN ONLY.

A bulk list never contains a secret; reveal is a deliberate, separate, owner-only
call. Secrets are never logged.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_owner, require_perm
from app.db.supabase import get_admin_client
from app.db.vault_repo import VaultRepoDep
from app.schemas.vault import (
    RevealResponse,
    RotateRequest,
    VaultKeyCreate,
    VaultKeyResponse,
)
from app.services.activity import record_activity
from app.services.vault import add_key, reveal_secret, rotate_key

router = APIRouter(prefix="/vault", tags=["vault"])

ManageVault = Annotated[CurrentUser, Depends(require_perm("manage_vault"))]
Owner = Annotated[CurrentUser, Depends(require_owner())]

_KEY_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vault key not found")


@router.get("/keys", response_model=list[VaultKeyResponse])
async def list_keys(repo: VaultRepoDep, _user: ManageVault) -> list[VaultKeyResponse]:
    """Masked list of vault keys (never includes a secret)."""
    rows = await asyncio.to_thread(repo.list_keys)
    return [VaultKeyResponse.from_row(r) for r in rows]


@router.post("/keys", response_model=VaultKeyResponse, status_code=status.HTTP_201_CREATED)
async def add_vault_key(body: VaultKeyCreate, actor: ManageVault) -> VaultKeyResponse:
    """Store a new secret in the vault; returns the masked metadata (no secret)."""
    admin = get_admin_client()
    row = await asyncio.to_thread(
        add_key,
        admin,
        provider=body.provider,
        label=body.label,
        secret=body.secret.get_secret_value(),
        scope=body.scope,
        site=body.site,
    )
    await record_activity(actor, kind="access", action="added a vault key", target=body.label)
    return VaultKeyResponse.from_row(row)


@router.post("/keys/{key_id}/rotate", response_model=VaultKeyResponse)
async def rotate_vault_key(key_id: str, body: RotateRequest, actor: ManageVault) -> VaultKeyResponse:
    """Replace a key's secret; returns the refreshed masked metadata."""
    admin = get_admin_client()
    row = await asyncio.to_thread(rotate_key, admin, key_id, body.secret.get_secret_value())
    if row is None:
        raise _KEY_NOT_FOUND
    await record_activity(actor, kind="access", action="rotated a vault key", target=row.get("label", key_id))
    return VaultKeyResponse.from_row(row)


@router.get("/keys/{key_id}/reveal", response_model=RevealResponse)
async def reveal_vault_key(key_id: str, actor: Owner) -> RevealResponse:
    """Decrypt and return a secret. SUPER-ADMIN ONLY."""
    admin = get_admin_client()
    secret = await asyncio.to_thread(reveal_secret, admin, key_id)
    if secret is None:
        raise _KEY_NOT_FOUND
    await record_activity(actor, kind="access", action="revealed a vault key", target=key_id)
    return RevealResponse(id=key_id, secret=secret)
