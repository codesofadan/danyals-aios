"""Cost-control endpoints: budgets, the per-feature dial, spend-stop, cost log.

Reads = any staff. Budget writes = manage_clients (owner/admin/manager). The
org-wide dial + spend-stop are higher-privilege = owner/admin.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, CurrentUserDep, require_perm, require_role
from app.core.pagination import PageDep
from app.db.cost_repo import CostRepoDep
from app.schemas.cost import (
    DIAL_KEYS,
    BudgetUpdate,
    ClientBudgetResponse,
    CostEntryResponse,
    DialFeatureResponse,
    DialUpdate,
    SpendStopResponse,
    SpendStopUpdate,
    merge_dial,
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
    await record_activity(actor, kind="client", action="set budget cap", target=row["cn"], meta=f"${body.cap}")
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
@router.get("/log", response_model=list[CostEntryResponse])
async def list_cost_log(
    repo: CostRepoDep,
    page: PageDep,
    _user: CurrentUserDep,
) -> list[CostEntryResponse]:
    rows = await asyncio.to_thread(repo.list_cost_log, page.limit, page.offset)
    return [CostEntryResponse.from_row(r) for r in rows]


# --- spend-stop --------------------------------------------------------------
@router.get("/spend-stop", response_model=SpendStopResponse)
async def get_spend_stop(repo: CostRepoDep, _user: CurrentUserDep) -> SpendStopResponse:
    settings = await asyncio.to_thread(repo.get_settings)
    today = await asyncio.to_thread(repo.today_spent)
    return SpendStopResponse(
        daily_stop=float(settings.get("daily_stop", 75)),
        halted=bool(settings.get("halted", False)),
        today_spent=today,
    )


@router.put("/spend-stop", response_model=SpendStopResponse)
async def set_spend_stop(
    body: SpendStopUpdate, repo: CostRepoDep, actor: OrgAdmin
) -> SpendStopResponse:
    changes: dict[str, object] = {}
    if body.daily_stop is not None:
        changes["daily_stop"] = body.daily_stop
    if body.halted is not None:
        changes["halted"] = body.halted
    settings = await asyncio.to_thread(repo.update_settings, changes)
    today = await asyncio.to_thread(repo.today_spent)
    await record_activity(actor, kind="access", action="updated the daily spend-stop", target="cost controls")
    return SpendStopResponse(
        daily_stop=float(settings.get("daily_stop", 75)),
        halted=bool(settings.get("halted", False)),
        today_spent=today,
    )
