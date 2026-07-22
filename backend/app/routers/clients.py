"""Clients + sites CRUD. Reads require any provisioned staff; writes require
``manage_clients`` (owner/admin/manager). Responses match the frontend shapes.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, CurrentUserDep, require_perm
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.db.database import DatabaseNotConfiguredError
from app.db.report_grants_repo import ReportGrantsRepoDep
from app.logging_setup import get_logger
from app.modules.client_onboarding.service import seed_onboarding_for_client
from app.schemas.clients import (
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    ReportGrantsUpdate,
    SiteCreate,
    SiteResponse,
)
from app.schemas.identity import MemberResponse, PortalUserRequest
from app.services.activity import record_activity
from app.services.provisioning import provision_user

router = APIRouter(tags=["clients"])
logger = get_logger("app.clients")

ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]

_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")


@router.get("/clients", response_model=list[ClientResponse])
async def list_clients(
    repo: ClientsRepoDep, page: PageDep, _user: CurrentUserDep
) -> list[ClientResponse]:
    rows = await asyncio.to_thread(repo.list_clients, limit=page.limit, offset=page.offset)
    counts = await asyncio.to_thread(repo.site_counts)
    return [ClientResponse.from_row(r, site_count=counts.get(str(r["id"]), 0)) for r in rows]


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(body: ClientCreate, repo: ClientsRepoDep, actor: ManageClients) -> ClientResponse:
    """Create a client and immediately give it an onboarding run.

    The onboarding seed is BEST-EFFORT and never raises (it is written to that
    contract, like ``record_activity``): a new client must not be able to exist
    without an activation checklist - that is how onboarding gets forgotten and how a
    client goes missing from the onboarding KPI - but a seeding hiccup must never
    fail, or roll back, a client creation that has otherwise succeeded.
    """
    row = await asyncio.to_thread(repo.insert_client, body.to_row())
    await record_activity(
        actor, kind="client", action="created client", target=body.cn,
        entity_type="client", entity_id=str(row["id"]),
    )
    await asyncio.to_thread(
        seed_onboarding_for_client, actor.id, str(row["id"]), body.cn, actor.id, actor.name
    )
    return ClientResponse.from_row(row, site_count=0)


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: str, repo: ClientsRepoDep, _user: CurrentUserDep) -> ClientResponse:
    row = await asyncio.to_thread(repo.get_client, client_id)
    if row is None:
        raise _CLIENT_NOT_FOUND
    count = await asyncio.to_thread(repo.site_counts)
    return ClientResponse.from_row(row, site_count=count.get(client_id, 0))


@router.patch("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str, body: ClientUpdate, repo: ClientsRepoDep, actor: ManageClients
) -> ClientResponse:
    changes = body.to_row()
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    row = await asyncio.to_thread(repo.update_client, client_id, changes)
    if row is None:
        raise _CLIENT_NOT_FOUND
    await record_activity(
        actor, kind="client", action="updated client", target=row.get("name", client_id),
        entity_type="client", entity_id=client_id,
    )
    counts = await asyncio.to_thread(repo.site_counts)
    return ClientResponse.from_row(row, site_count=counts.get(client_id, 0))


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: str, repo: ClientsRepoDep, actor: ManageClients) -> None:
    deleted = await asyncio.to_thread(repo.delete_client, client_id)
    if not deleted:
        raise _CLIENT_NOT_FOUND
    await record_activity(
        actor, kind="client", action="deleted client", target=client_id,
        entity_type="client", entity_id=client_id,
    )


@router.get("/clients/{client_id}/report-grants", response_model=list[str])
async def get_report_grants(
    client_id: str, repo: ClientsRepoDep, grants: ReportGrantsRepoDep, _user: CurrentUserDep
) -> list[str]:
    """The report keys a client is granted to see in its portal (sorted)."""
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    return await asyncio.to_thread(grants.list_keys, client_id)


@router.put("/clients/{client_id}/report-grants", response_model=list[str])
async def put_report_grants(
    client_id: str,
    body: ReportGrantsUpdate,
    repo: ClientsRepoDep,
    grants: ReportGrantsRepoDep,
    actor: ManageClients,
) -> list[str]:
    """Replace a client's report-access set (the full grant list). Lead-only; the
    replace runs atomically. Records an ``access`` activity entry."""
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    keys = await asyncio.to_thread(grants.replace_keys, client_id, body.reports)
    await record_activity(
        actor, kind="access", action="updated report access",
        target=client.get("name", client_id),
        entity_type="client", entity_id=client_id,
    )
    return keys


@router.get("/clients/{client_id}/sites", response_model=list[SiteResponse])
async def list_sites(
    client_id: str, repo: ClientsRepoDep, page: PageDep, _user: CurrentUserDep
) -> list[SiteResponse]:
    rows = await asyncio.to_thread(repo.list_sites, client_id, limit=page.limit, offset=page.offset)
    return [SiteResponse.from_row(r) for r in rows]


@router.post(
    "/clients/{client_id}/sites", response_model=SiteResponse, status_code=status.HTTP_201_CREATED
)
async def create_site(
    client_id: str, body: SiteCreate, repo: ClientsRepoDep, actor: ManageClients
) -> SiteResponse:
    row = await asyncio.to_thread(
        repo.insert_site, {"client_id": client_id, "domain": body.domain, "cms_type": body.cms_type}
    )
    await record_activity(
        actor, kind="client", action="added a site", target=body.domain,
        entity_type="site", entity_id=str(row["id"]),
    )
    return SiteResponse.from_row(row)


@router.post(
    "/clients/{client_id}/portal-users",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_portal_user(
    client_id: str, body: PortalUserRequest, repo: ClientsRepoDep, actor: ManageClients
) -> MemberResponse:
    """Provision a client PORTAL login scoped to ``client_id`` (lead-only).

    Guarded by ``manage_clients`` — the SAME gate as creating the client itself,
    so the Add-Client wizard's final step (this call) can never silently 403 for
    an admin/manager who was just allowed to create the client. Not an
    escalation: the role is fixed to ``client`` and the tenant is pinned from
    the path, so this endpoint can neither mint a staff account nor point a
    login at another client's data. Provisioning uses the service_role admin
    client (server-only).
    """
    client = await asyncio.to_thread(repo.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    try:
        row = await asyncio.to_thread(
            provision_user,
            email=str(body.email),
            password=body.password.get_secret_value(),
            name=body.name,
            role="client",
            username=body.username,
            client_id=client_id,
        )
    except DatabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
        ) from exc
    except Exception as exc:
        # Duplicate email / auth rejection / write failure. Log server-side (no
        # secret in the payload) and return a generic client error, never a 500.
        logger.warning(
            "provision_portal_user_failed", actor=actor.id, error_type=type(exc).__name__
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create portal login (email may already exist)",
        ) from exc
    await record_activity(
        actor,
        kind="client",
        action="provisioned a portal login",
        target=body.name,
        meta=client.get("name", client_id),
        # A portal login is a change to THIS client's world (its team gained a
        # login), so track the client entity, not the freshly-minted user.
        entity_type="client",
        entity_id=client_id,
    )
    return MemberResponse.from_row(row)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: str, repo: ClientsRepoDep, actor: ManageClients) -> None:
    deleted = await asyncio.to_thread(repo.delete_site, site_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    await record_activity(
        actor, kind="client", action="deleted a site", target=site_id,
        entity_type="site", entity_id=site_id,
    )
