"""Cost-control endpoints: budgets, the per-feature dial, the spend halt, cost log.

Reads = any staff. Budget writes = manage_clients (owner/admin/manager). The
org-wide dial + the global API-spend HALT toggle are higher-privilege = owner/admin.
The halt is a single agency-global kill-switch (there is no per-day dollar
threshold): while engaged, the cost gate blocks every metered feature.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, CurrentUserDep, require_perm, require_role
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.db.cost_repo import CostRepoDep
from app.schemas.cost import (
    DIAL_KEYS,
    BudgetUpdate,
    ClientBudgetResponse,
    CostEntryResponse,
    DialFeatureResponse,
    DialUpdate,
    ProviderPricingResponse,
    SpendStopResponse,
    SpendStopUpdate,
    merge_dial,
    provider_pricing,
)
from app.services.activity import record_activity

router = APIRouter(prefix="/cost", tags=["cost"])

ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]
OrgAdmin = Annotated[CurrentUser, Depends(require_role("admin"))]  # owner passes too


# --- budgets -----------------------------------------------------------------
@router.get("/budgets", response_model=list[ClientBudgetResponse])
async def list_budgets(
    repo: CostRepoDep, page: PageDep, _user: CurrentUserDep
) -> list[ClientBudgetResponse]:
    rows = await asyncio.to_thread(repo.list_budgets, limit=page.limit, offset=page.offset)
    return [ClientBudgetResponse(**r) for r in rows]


@router.put("/budgets/{client_id}", response_model=ClientBudgetResponse)
async def set_budget(
    client_id: str, body: BudgetUpdate, repo: CostRepoDep, actor: ManageClients
) -> ClientBudgetResponse:
    row = await asyncio.to_thread(repo.upsert_budget, client_id, body.cap)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    await record_activity(
        actor, kind="client", action="set budget cap", target=row["cn"], meta=f"${body.cap}",
        entity_type="client", entity_id=client_id,
    )
    return ClientBudgetResponse(**row)


# --- dial --------------------------------------------------------------------
@router.get("/dial", response_model=list[DialFeatureResponse])
async def get_dial(repo: CostRepoDep, _user: CurrentUserDep) -> list[DialFeatureResponse]:
    modes = await asyncio.to_thread(repo.dial_modes)
    return merge_dial(modes)


@router.put("/dial/{feature_key}", response_model=DialFeatureResponse)
async def set_dial(
    feature_key: str, body: DialUpdate, repo: CostRepoDep, actor: OrgAdmin
) -> DialFeatureResponse:
    if feature_key not in DIAL_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown dial feature")
    await asyncio.to_thread(repo.set_dial, feature_key, body.mode)
    modes = await asyncio.to_thread(repo.dial_modes)
    await record_activity(actor, kind="access", action="changed the cost dial", target=feature_key, meta=body.mode)
    return next(d for d in merge_dial(modes) if d.key == feature_key)


# --- cost log ----------------------------------------------------------------
# Newest-first, paginated via PageDep (?limit=&offset=, hard-capped 1..200). The
# frontend pages/loads-more over this: a returned page shorter than ``limit`` means
# there are no more rows. Response stays the contract-locked ``CostEntry`` list.
@router.get("/log", response_model=list[CostEntryResponse])
async def list_cost_log(
    repo: CostRepoDep,
    page: PageDep,
    _user: CurrentUserDep,
) -> list[CostEntryResponse]:
    rows = await asyncio.to_thread(repo.list_cost_log, page.limit, page.offset)
    return [CostEntryResponse.from_row(r) for r in rows]


# --- provider unit pricing ---------------------------------------------------
@router.get("/pricing", response_model=list[ProviderPricingResponse])
async def get_pricing(settings: SettingsDep, _user: CurrentUserDep) -> list[ProviderPricingResponse]:
    """The LIVE per-provider unit prices the cost gate bills at.

    Reads the same ``Settings`` fields ``app.services.pricing`` uses to compute
    committed spend, so what an operator sees on the Cost screen is what the
    platform actually charges itself - and it tracks an env change without a
    frontend deploy. Pure settings read: no DB, no provider call, any staff role.
    """
    return provider_pricing(settings)


# --- spend halt (the global API-spend kill-switch) ---------------------------
@router.get("/spend-stop", response_model=SpendStopResponse)
async def get_spend_stop(repo: CostRepoDep, _user: CurrentUserDep) -> SpendStopResponse:
    """Read the global API-spend HALT state (+ today's/this month's informational
    real paid spend, summed live from ``cost_log`` - never the all-time
    ``client_budgets.spent`` counter)."""
    settings = await asyncio.to_thread(repo.get_settings)
    today = await asyncio.to_thread(repo.today_spent)
    month = await asyncio.to_thread(repo.month_spent)
    return SpendStopResponse(
        halted=bool(settings.get("halted", False)),
        today_spent=today,
        month_spent=month,
    )


@router.put("/spend-stop", response_model=SpendStopResponse)
async def set_spend_stop(
    body: SpendStopUpdate, repo: CostRepoDep, actor: OrgAdmin
) -> SpendStopResponse:
    """Toggle the global API-spend halt on/off (owner/admin only, activity-logged).

    Turning it ON blocks every metered feature at the gate; turning it OFF restores
    normal dial-governed behavior.
    """
    settings = await asyncio.to_thread(repo.update_settings, {"halted": body.halted})
    today = await asyncio.to_thread(repo.today_spent)
    month = await asyncio.to_thread(repo.month_spent)
    await record_activity(
        actor,
        kind="access",
        action="halted all API spend" if body.halted else "resumed API spend",
        target="cost controls",
    )
    return SpendStopResponse(
        halted=bool(settings.get("halted", False)),
        today_spent=today,
        month_spent=month,
    )
