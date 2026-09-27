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
import os
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm, require_staff
from app.core.deps import SettingsDep
from app.db.cost_repo import CostRepoDep
from app.db.database import DatabaseNotConfiguredError, privileged_connection
from app.services.integrations_status import IntegrationStatus, integration_statuses
from app.services.preflight import PreflightBoard, engine_env_keys, preflight
from app.services.provider_health import anthropic_health

router = APIRouter(prefix="/integrations", tags=["integrations"])

ManageVault = Annotated[CurrentUser, Depends(require_perm("manage_vault"))]
Staff = Annotated[CurrentUser, Depends(require_staff())]


def _spend_halted(repo: object) -> bool:
    """The agency-wide spend halt, best-effort.

    Unreadable settings are reported as NOT halted deliberately: a halt the operator
    cannot see is a dangerous claim in only one direction, and this board is read before
    spending, not instead of the gate - the gate itself still refuses every metered call
    while the halt is engaged.
    """
    getter = getattr(repo, "get_settings", None)
    if not callable(getter):
        return False
    try:
        return bool((getter() or {}).get("halted"))
    except DatabaseNotConfiguredError:
        return False


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


@router.get("/readiness", response_model=PreflightBoard)
async def readiness_board(
    settings: SettingsDep, repo: CostRepoDep, _user: Staff
) -> PreflightBoard:
    """What this deploy will really deliver if the operator launches work right now.

    ANY STAFF ROLE, unlike the key list above: this answers "will my deep audit measure
    off-page" - a question the person about to run the audit needs answered, and one
    that can be answered without naming a single credential. It reports only whether a
    key is PRESENT, never a value, so the vault-management privilege is not the right
    bar for it.

    Four live reads, all off the event loop, all best-effort so a half-configured
    deploy still renders a board: the vault provider set, the persisted cost dials +
    halt, the env var NAMES the audit engine itself will resolve, and a cached LIVE
    probe of the Anthropic key.

    The probe is the one that answers a question presence cannot. A key can be
    configured, valid, and attached to an account with no credit - which is exactly what
    happened on 2026-09-26, while this board reported the content pipeline READY and
    every page died at the writing stage. It is cached for ten minutes inside
    `provider_health`, so polling this endpoint costs nothing.
    """
    vault_providers, dials, halted, engine_keys, llm = await asyncio.gather(
        asyncio.to_thread(_vault_providers),
        asyncio.to_thread(repo.dial_modes),
        asyncio.to_thread(_spend_halted, repo),
        asyncio.to_thread(engine_env_keys, settings.audit_engine_dir, os.environ),
        asyncio.to_thread(anthropic_health, settings),
    )
    return preflight(
        settings,
        vault_providers=vault_providers,
        dial_modes=dials,
        spend_halted=halted,
        engine_keys=engine_keys,
        llm_health=(llm.verdict, llm.detail),
    )
