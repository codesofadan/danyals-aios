"""API-Management (integrations) status endpoint.

``GET /integrations`` reports EVERY supported integration with a REAL connected /
missing verdict, computed from the live config (env-backed ``Settings``) and the
vault - not a hard-coded checkmark list. It backs the vault screen's providers
overview. Gated on ``manage_vault`` (owner/admin), the same audience that manages
the keys these integrations use.

The vault presence check is a single distinct-provider query on the privileged pool
(vault metadata lives on service_role, like the rest of the vault layer); it is
best-effort, so a not-configured DB still renders the env-backed statuses.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm
from app.core.deps import SettingsDep
from app.db.database import DatabaseNotConfiguredError, privileged_connection
from app.services.integrations_status import IntegrationStatus, integration_statuses

router = APIRouter(prefix="/integrations", tags=["integrations"])

ManageVault = Annotated[CurrentUser, Depends(require_perm("manage_vault"))]


def _vault_providers() -> set[str]:
    """The distinct provider slugs that have at least one sealed vault key. Blocking.

    Best-effort: a not-configured pool yields an empty set so the env-backed
    integration statuses still render (a keyless deploy is a normal state here)."""
    try:
        with privileged_connection() as cur:
            cur.execute("select distinct provider from public.vault_keys")
            return {str(r["provider"]) for r in cur.fetchall()}
    except DatabaseNotConfiguredError:
        return set()


@router.get("", response_model=list[IntegrationStatus])
async def list_integrations(
    settings: SettingsDep, _user: ManageVault
) -> list[IntegrationStatus]:
    """Every supported integration with a live connected/missing status."""
    vault_providers = await asyncio.to_thread(_vault_providers)
    return integration_statuses(settings, vault_providers)
