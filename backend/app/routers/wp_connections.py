"""Multi-client WordPress Connections registry endpoints.

Lets the admin connect EVERY client's WordPress site once, so the content publish
path can resolve the RIGHT client's connection at push time. Reads are staff-wide
(``view_reports`` - every staff role holds it, matching the ``is_staff()`` RLS
select policy); create / edit / remove / test require ``manage_clients``
(owner/admin/manager, matching the ``wp_connections_modify`` write policy).

The sealed credential NEVER crosses the wire: the PUT body carries the raw secret
inbound only (sealed server-side by ``app/services/wp_connections.py``), and every
response is masked metadata + a ``configured`` flag. The test endpoint resolves +
opens the credential server-side, probes the real site with a browser User-Agent,
records the verdict, and returns only ``{ok, detail}``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.core.auth import CurrentUser, require_perm
from app.db.wp_connections_repo import WpConnectionsRepoDep
from app.schemas.wp_connections import (
    WpConnectionResponse,
    WpConnectionUpsert,
    WpTestResponse,
)
from app.services import wp_connections as svc
from app.services.activity import record_activity
from app.services.vault import VaultNotConfiguredError

router = APIRouter(prefix="/wp-connections", tags=["wp-connections"])

# Reads: any provisioned staff member (mirrors the is_staff() RLS select policy).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Writes + test: manage_clients holders (owner/admin/manager) - the same set that
# manages the client account itself and the wp_connections_modify write policy.
ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]

_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
_VAULT_UNCONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="The secret vault is not configured (VAULT_MASTER_KEY missing)",
)


@router.get("", response_model=list[WpConnectionResponse])
async def list_connections(
    repo: WpConnectionsRepoDep, _user: ViewReports
) -> list[WpConnectionResponse]:
    """Every client with its WordPress connection state (unconfigured -> placeholder)."""
    rows = await asyncio.to_thread(repo.list_with_clients)
    return [WpConnectionResponse.from_row(r) for r in rows]


@router.get("/{client_id}", response_model=WpConnectionResponse)
async def get_connection(
    client_id: str, repo: WpConnectionsRepoDep, _user: ViewReports
) -> WpConnectionResponse:
    """One client's WordPress connection state (404 if the client is not visible)."""
    row = await asyncio.to_thread(repo.get_for_client, client_id)
    if row is None:
        raise _CLIENT_NOT_FOUND
    return WpConnectionResponse.from_row(row)


@router.put("/{client_id}", response_model=WpConnectionResponse)
async def upsert_connection(
    client_id: str,
    body: WpConnectionUpsert,
    repo: WpConnectionsRepoDep,
    actor: ManageClients,
) -> WpConnectionResponse:
    """Set or replace a client's WordPress connection; seals the secret server-side.

    The client must be visible (else 404). The relevant secret (api_key for the
    plugin method; password for xmlrpc / app_password) is sealed app-layer; an
    omitted secret is a metadata-only edit that keeps the stored credential. The
    response is masked metadata - never the secret.
    """
    existing = await asyncio.to_thread(repo.get_for_client, client_id)
    if existing is None:
        raise _CLIENT_NOT_FOUND
    try:
        await asyncio.to_thread(
            svc.upsert_connection,
            client_id=client_id,
            site_url=body.site_url.strip(),
            auth_method=body.auth_method,
            username=(body.username or "").strip(),
            secret=body.secret(),
        )
    except VaultNotConfiguredError as exc:
        raise _VAULT_UNCONFIGURED from exc
    # Re-read through the RLS join so the response carries the client name + fresh state.
    row = await asyncio.to_thread(repo.get_for_client, client_id)
    if row is None:  # pragma: no cover - the client existed a line ago
        raise _CLIENT_NOT_FOUND
    await record_activity(
        actor,
        kind="client",
        action="updated the WordPress connection",
        target=str(existing.get("client_name") or ""),
        entity_type="client",
        entity_id=str(client_id),
    )
    return WpConnectionResponse.from_row(row)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    client_id: str, repo: WpConnectionsRepoDep, actor: ManageClients
) -> None:
    """Remove a client's WordPress connection (204). No-op if none was configured."""
    existing = await asyncio.to_thread(repo.get_for_client, client_id)
    if existing is None:
        raise _CLIENT_NOT_FOUND
    await asyncio.to_thread(svc.delete_connection, client_id)
    await record_activity(
        actor,
        kind="client",
        action="removed the WordPress connection",
        target=str(existing.get("client_name") or ""),
        entity_type="client",
        entity_id=str(client_id),
    )


@router.post("/{client_id}/test", response_model=WpTestResponse)
async def test_connection(
    client_id: str, repo: WpConnectionsRepoDep, actor: ManageClients
) -> WpTestResponse:
    """Probe the client's connection against the REAL site and record the verdict.

    Resolves + opens the credential server-side, calls the adapter's ping/verify with
    a browser User-Agent, and updates ``status`` + ``last_tested_at``. Returns only
    ``{ok, detail}`` - never the credential. A non-existent client is 404; an
    unconfigured one returns ``ok=false`` with a clear reason (never a 500).
    """
    existing = await asyncio.to_thread(repo.get_for_client, client_id)
    if existing is None:
        raise _CLIENT_NOT_FOUND
    settings = get_settings()
    ok, detail, updated = await asyncio.to_thread(svc.test_connection, client_id, settings)
    await record_activity(
        actor,
        kind="client",
        action="tested the WordPress connection",
        target=str(existing.get("client_name") or ""),
        entity_type="client",
        entity_id=str(client_id),
    )
    return WpTestResponse(
        ok=ok,
        detail=detail,
        status=str((updated or {}).get("status") or ("connected" if ok else "failed")),
        last_tested_at=None,
    )
