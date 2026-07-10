"""Clients + sites CRUD. Reads require any provisioned staff; writes require
``manage_clients`` (owner/admin/manager). Responses match the frontend shapes.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, CurrentUserDep, require_perm
from app.db.clients_repo import ClientsRepoDep
from app.schemas.clients import (
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    SiteCreate,
    SiteResponse,
)

router = APIRouter(tags=["clients"])

ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]

_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")


@router.get("/clients", response_model=list[ClientResponse])
async def list_clients(repo: ClientsRepoDep, _user: CurrentUserDep) -> list[ClientResponse]:
    rows = await asyncio.to_thread(repo.list_clients)
    counts = await asyncio.to_thread(repo.site_counts)
    return [ClientResponse.from_row(r, site_count=counts.get(str(r["id"]), 0)) for r in rows]


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(body: ClientCreate, repo: ClientsRepoDep, _user: ManageClients) -> ClientResponse:
    row = await asyncio.to_thread(repo.insert_client, body.to_row())
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
    client_id: str, body: ClientUpdate, repo: ClientsRepoDep, _user: ManageClients
) -> ClientResponse:
    changes = body.to_row()
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    row = await asyncio.to_thread(repo.update_client, client_id, changes)
    if row is None:
        raise _CLIENT_NOT_FOUND
    counts = await asyncio.to_thread(repo.site_counts)
    return ClientResponse.from_row(row, site_count=counts.get(client_id, 0))


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: str, repo: ClientsRepoDep, _user: ManageClients) -> None:
    deleted = await asyncio.to_thread(repo.delete_client, client_id)
    if not deleted:
        raise _CLIENT_NOT_FOUND


@router.get("/clients/{client_id}/sites", response_model=list[SiteResponse])
async def list_sites(client_id: str, repo: ClientsRepoDep, _user: CurrentUserDep) -> list[SiteResponse]:
    rows = await asyncio.to_thread(repo.list_sites, client_id)
    return [SiteResponse.from_row(r) for r in rows]


@router.post(
    "/clients/{client_id}/sites", response_model=SiteResponse, status_code=status.HTTP_201_CREATED
)
async def create_site(
    client_id: str, body: SiteCreate, repo: ClientsRepoDep, _user: ManageClients
) -> SiteResponse:
    row = await asyncio.to_thread(
        repo.insert_site, {"client_id": client_id, "domain": body.domain, "cms_type": body.cms_type}
    )
    return SiteResponse.from_row(row)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: str, repo: ClientsRepoDep, _user: ManageClients) -> None:
    deleted = await asyncio.to_thread(repo.delete_site, site_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
