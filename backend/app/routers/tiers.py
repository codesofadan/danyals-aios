"""Service-tier endpoints.

Delivery tiers (free/semi/fully) + the feature-area matrix are reference data;
per-client delivery-tier assignment is a manage_clients write. The subscription
tier (Starter/Growth/Scale) is a separate concept edited via the clients endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, CurrentUserDep, require_perm, require_staff
from app.core.pagination import PageDep
from app.db.tiers_repo import TiersRepoDep
from app.schemas.tiers import (
    FEATURE_AREAS,
    TIERS,
    DeliveryTierUpdate,
    FeatureAreaResponse,
    TierClientResponse,
    TierResponse,
)
from app.services.activity import record_activity

router = APIRouter(prefix="/tiers", tags=["tiers"])

ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]
# `list_tiers` and `list_feature_areas` are DELIBERATELY client-readable - decision
# D-19. The client portal sells upsells off this data and the delivered access matrix
# lists "Click Fiverr upsells" as a client capability, so locking them would be tidier
# and would break a product surface. They keep `CurrentUserDep` and are recorded in
# `_AUTH_ONLY_HANDLERS` as open-by-decision.
#
# `list_tier_clients` is different: it is per-client assignment data, classified
# RLS-bounded rather than open-by-decision, so it takes an explicit staff guard. An RLS
# policy refusing rows is a real guarantee, but it is not the app layer granting
# anything - which is the exact distinction PM-3 got wrong.
Staff = Annotated[CurrentUser, Depends(require_staff())]


@router.get("", response_model=list[TierResponse])
async def list_tiers(_user: CurrentUserDep) -> list[TierResponse]:
    """The 3 delivery-tier presets (frontend TIERS)."""
    return list(TIERS)


@router.get("/feature-areas", response_model=list[FeatureAreaResponse])
async def list_feature_areas(_user: CurrentUserDep) -> list[FeatureAreaResponse]:
    """The 7 gated feature areas x tier matrix (frontend featureAreas)."""
    return list(FEATURE_AREAS)


@router.get("/clients", response_model=list[TierClientResponse])
async def list_tier_clients(
    repo: TiersRepoDep, page: PageDep, _user: Staff
) -> list[TierClientResponse]:
    """Per-client delivery-tier assignments (frontend tierClients)."""
    rows = await asyncio.to_thread(repo.list_tier_clients, limit=page.limit, offset=page.offset)
    return [TierClientResponse.from_row(r) for r in rows]


@router.put("/clients/{client_id}", response_model=TierClientResponse)
async def set_delivery_tier(
    client_id: str, body: DeliveryTierUpdate, repo: TiersRepoDep, actor: ManageClients
) -> TierClientResponse:
    row = await asyncio.to_thread(repo.set_delivery_tier, client_id, body.tier)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    await record_activity(
        actor, kind="client", action="set delivery tier", target=row.get("name", client_id), meta=body.tier,
        entity_type="client", entity_id=client_id,
    )
    return TierClientResponse.from_row(row)
