"""Upsells module endpoints: the agency-global Fiverr upsell catalogue.

Listing requires any provisioned staff (``view_reports``); creating / editing /
toggling / reordering requires an owner or admin (``require_role``) - matching the
``upsells`` RLS (staff select; owner/admin manage) so the app-layer 403 and the DB
boundary agree. Responses are the frontend ``Upsell`` shape (``lib/upsells.ts``).
Every mutation appends an activity entry (agency-level, so no linked entity).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.upsells_repo import UpsellsRepoDep
from app.schemas.upsells import (
    UpsellCreate,
    UpsellReorder,
    UpsellResponse,
    UpsellUpdate,
)
from app.services.activity import record_activity

router = APIRouter(tags=["upsells"])

# Any staff may READ the catalogue; only owner/admin MANAGE it (mirrors the RLS).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
ManageUpsells = Annotated[CurrentUser, Depends(require_role("owner", "admin"))]

_UPSELL_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Upsell not found"
)


@router.get("/upsells", response_model=list[UpsellResponse])
async def list_upsells(
    repo: UpsellsRepoDep,
    page: PageDep,
    _user: ViewReports,
    active_only: Annotated[bool, Query()] = False,
) -> list[UpsellResponse]:
    """List upsells in curated order (``sort_order``). ``active_only=true`` limits
    to the active cards (the portal-render surface); otherwise the whole catalogue
    (the admin curation screen)."""
    rows = await asyncio.to_thread(
        repo.list_upsells, active_only=active_only, limit=page.limit, offset=page.offset
    )
    return [UpsellResponse.from_row(r) for r in rows]


@router.post("/upsells", response_model=UpsellResponse, status_code=status.HTTP_201_CREATED)
async def create_upsell(
    body: UpsellCreate, repo: UpsellsRepoDep, actor: ManageUpsells
) -> UpsellResponse:
    """Add a Fiverr upsell card (owner/admin). ``clicks30d`` starts at 0."""
    row = await asyncio.to_thread(
        repo.insert_upsell,
        {
            "title": body.title,
            "description": body.description,
            "fiverr_url": body.fiverr_url,
            "active": body.active,
            "price": body.price,
            "rating": body.rating,
            "reviews": body.reviews,
            "icon": body.icon,
            "color": body.color,
            "sort_order": body.sort_order,
        },
    )
    await record_activity(actor, kind="content", action="added an upsell", target=body.title)
    return UpsellResponse.from_row(row)


@router.post("/upsells/reorder", response_model=list[UpsellResponse])
async def reorder_upsells(
    body: UpsellReorder, repo: UpsellsRepoDep, actor: ManageUpsells
) -> list[UpsellResponse]:
    """Set each upsell's ``sort_order`` to its index in ``ids`` (owner/admin).
    Unknown ids are skipped; returns the full catalogue in the new order."""
    for i, upsell_id in enumerate(body.ids):
        await asyncio.to_thread(repo.update_upsell, upsell_id, {"sort_order": i})
    await record_activity(actor, kind="content", action="reordered upsells", target="")
    rows = await asyncio.to_thread(repo.list_upsells)
    return [UpsellResponse.from_row(r) for r in rows]


@router.patch("/upsells/{upsell_id}", response_model=UpsellResponse)
async def update_upsell(
    upsell_id: str, body: UpsellUpdate, repo: UpsellsRepoDep, actor: ManageUpsells
) -> UpsellResponse:
    """Edit an upsell (owner/admin). Only the provided fields are changed; the
    request field names are the DB columns (``fiverrUrl`` maps to ``fiverr_url``)."""
    existing = await asyncio.to_thread(repo.get_upsell, upsell_id)
    if existing is None:
        raise _UPSELL_NOT_FOUND
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    if not changes:
        return UpsellResponse.from_row(existing)
    updated = await asyncio.to_thread(repo.update_upsell, upsell_id, changes)
    if updated is None:
        raise _UPSELL_NOT_FOUND
    await record_activity(
        actor, kind="content", action="updated an upsell", target=existing.get("title", "")
    )
    return UpsellResponse.from_row(updated)


@router.post("/upsells/{upsell_id}/toggle", response_model=UpsellResponse)
async def toggle_upsell(
    upsell_id: str, repo: UpsellsRepoDep, actor: ManageUpsells
) -> UpsellResponse:
    """Flip an upsell's ``active`` flag (owner/admin)."""
    existing = await asyncio.to_thread(repo.get_upsell, upsell_id)
    if existing is None:
        raise _UPSELL_NOT_FOUND
    new_active = not bool(existing.get("active", False))
    updated = await asyncio.to_thread(repo.update_upsell, upsell_id, {"active": new_active})
    if updated is None:
        raise _UPSELL_NOT_FOUND
    action = "activated an upsell" if new_active else "deactivated an upsell"
    await record_activity(
        actor, kind="content", action=action, target=existing.get("title", "")
    )
    return UpsellResponse.from_row(updated)
