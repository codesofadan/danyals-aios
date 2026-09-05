"""The automations manager: create, re-time, pause and audit scheduled work.

AUTH mirrors ``routers/jobs.py``, which is the closest existing surface: reads need
``view_reports`` (every staff role holds it; a portal client does not), and every
mutation is lead-only. Scheduling recurring work - some of it paid, some of it
outward-facing - is an owner/admin/manager act.

The table has no write policy for ``authenticated`` at all, so these routes are the
only way in, and a route that forgot its guard would still be refused by Postgres.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.db.automations_repo import AutomationsRepoDep, automations_store
from app.jobs.automation_capabilities import CAPABILITIES, capability
from app.jobs.automation_schedule import InvalidScheduleError, parse_cron
from app.schemas.automations import (
    AutomationCreate,
    AutomationResponse,
    AutomationRunNowResponse,
    AutomationUpdate,
    CapabilityResponse,
)
from app.services.activity import record_activity

router = APIRouter(tags=["automations"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automation not found")


def _validate(kind: str, params: dict[str, Any], schedule_kind: str, cron_expr: str | None) -> None:
    """Refuse an automation that could never do anything.

    Each of these is a way to save a row that looks scheduled and fires into nothing -
    the exact failure mode this whole effort exists to remove, reintroduced through
    its own admin screen.
    """
    cap = capability(kind)
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{kind}' is not something this platform can automate.",
        )
    if cap.scope == "client" and not (params.get("clientIds") or params.get("client_ids")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{cap.label}' runs per client, so it needs at least one client.",
        )
    if schedule_kind == "cron":
        try:
            parse_cron(cron_expr or "")
        except InvalidScheduleError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc


@router.get("/automations/capabilities", response_model=list[CapabilityResponse])
async def list_capabilities(_user: ViewReports) -> list[CapabilityResponse]:
    """Everything an automation can be set to do.

    Declared before ``/automations/{id}`` so "capabilities" is never read as an id.
    """
    return [
        CapabilityResponse(
            kind=c.kind, label=c.label, description=c.description, scope=c.scope,
            paid=c.paid, default_interval_seconds=c.default_interval_seconds,
            needs=list(c.needs),
        )
        for c in CAPABILITIES.values()
    ]


@router.get("/automations", response_model=list[AutomationResponse])
async def list_automations(repo: AutomationsRepoDep, _user: ViewReports) -> list[AutomationResponse]:
    rows = await asyncio.to_thread(repo.list_all)
    return [AutomationResponse.from_row(r) for r in rows]


#: The standing automations are SEEDED (0128), not composed by an operator.
#:
#: Owner decision: an admin should not be building scheduled work. The platform ships
#: one automation per module it actually has - content/WordPress publishing, citation
#: liveness, audit refresh, the off-page sweep and monthly reports - and the admin's
#: job is to decide whether each runs, and how often, not to invent new ones.
#:
#: REFUSED HERE, not merely hidden in the UI. The builder form is gone from
#: Operations, but a removed form is not a removed capability: the route stayed
#: callable, and "the admin cannot add custom automations" has to be true of the API
#: or it is not true at all.
_CREATION_CLOSED = HTTPException(
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    detail=(
        "Automations are not created by hand. The platform ships one per module; "
        "enable, re-time or pause them on the Operations screen."
    ),
)


@router.post("/automations", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(
    body: AutomationCreate, repo: AutomationsRepoDep, actor: Lead
) -> AutomationResponse:
    """Closed. The standing automations are seeded; see `_CREATION_CLOSED`.

    The route is KEPT rather than deleted so a caller gets a 405 that explains itself,
    instead of a 404 that reads as "the automations API moved".
    """
    raise _CREATION_CLOSED


@router.patch("/automations/{automation_id}", response_model=AutomationResponse)
async def update_automation(
    automation_id: str, body: AutomationUpdate, repo: AutomationsRepoDep, actor: Lead
) -> AutomationResponse:
    """Edit, pause or resume. Pausing is the same call with ``enabled: false``."""
    current = await asyncio.to_thread(repo.get, automation_id)
    if current is None:
        raise _NOT_FOUND

    fields = body.model_dump(exclude_unset=True)
    schedule_kind = fields.get("schedule_kind", current["schedule_kind"])
    cron_expr = fields.get("cron_expr", current["cron_expr"])
    _validate(
        str(current["kind"]),
        fields.get("params", current["params"] or {}),
        str(schedule_kind),
        cron_expr,
    )

    try:
        row = await asyncio.to_thread(automations_store().update, automation_id, fields)
    except InvalidScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if row is None:
        raise _NOT_FOUND

    if "enabled" in fields:
        action = "enabled an automation" if fields["enabled"] else "paused an automation"
    else:
        action = "edited an automation"
    await record_activity(
        actor, kind="task", action=action, target=str(row["name"]),
        entity_type="automation", entity_id=automation_id,
    )
    fresh = await asyncio.to_thread(repo.get, automation_id)
    return AutomationResponse.from_row(fresh or row)


@router.delete("/automations/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    automation_id: str, repo: AutomationsRepoDep, actor: Lead
) -> None:
    """Remove an automation. Its run history survives in ``job_runs`` under the same
    correlation id - deleting the schedule does not erase what it did."""
    current = await asyncio.to_thread(repo.get, automation_id)
    if current is None:
        raise _NOT_FOUND
    await asyncio.to_thread(automations_store().delete, automation_id)
    await record_activity(
        actor, kind="task", action="deleted an automation", target=str(current["name"]),
        entity_type="automation", entity_id=automation_id,
    )


@router.post("/automations/{automation_id}/run", response_model=AutomationRunNowResponse)
async def run_automation_now(
    automation_id: str, repo: AutomationsRepoDep, actor: Lead
) -> AutomationRunNowResponse:
    """Fire it once, now, without changing its schedule.

    Deliberately separate from the schedule: it is how someone tests an automation
    before enabling it, and how they recover a window the dispatcher missed. It runs
    even when the automation is PAUSED - a manual run is an explicit act, not the
    schedule leaking - and it carries the automation's correlation id so the run
    appears in the same history.
    """
    row = await asyncio.to_thread(repo.get, automation_id)
    if row is None:
        raise _NOT_FOUND
    cap = capability(str(row["kind"]))
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{row['kind']}' is no longer something this platform can do, so this "
                "automation cannot run. Delete it or change what it does."
            ),
        )

    dispatched, run_id = await asyncio.to_thread(_run_now, automation_id, row, cap.scope, cap.task)
    await record_activity(
        actor, kind="task", action="ran an automation now", target=str(row["name"]),
        entity_type="automation", entity_id=automation_id,
    )
    return AutomationRunNowResponse(
        automation_id=automation_id, run_id=run_id, dispatched=dispatched
    )


def _run_now(
    automation_id: str, row: dict[str, Any], scope: str, task: str
) -> tuple[int, str | None]:
    """Enqueue one manual fire. Imported lazily so the API edge never pulls Celery in
    merely to import this router."""
    from app.db.job_runs_repo import job_runs_store
    from app.jobs.celery_task import enqueue

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    params = dict(row.get("params") or {})
    targets = [str(c) for c in (params.get("clientIds") or []) if c] if scope == "client" else [None]

    dispatched = 0
    last_key: str | None = None
    for client_id in targets:
        key = f"automation:{automation_id}:manual:{stamp}" + (f":{client_id}" if client_id else "")
        if client_id:
            enqueue(task, client_id, correlation_id=automation_id, idempotency_key=key)
        else:
            enqueue(task, correlation_id=automation_id, idempotency_key=key)
        dispatched += 1
        last_key = key

    run_id: str | None = None
    if last_key:
        try:
            run = job_runs_store().get_by_idempotency_key(last_key)
            run_id = str(run["id"]) if run else None
            if run_id:
                automations_store().record_run(automation_id, run_id)
        except Exception:
            # The work is queued; only the handle is missing.
            run_id = None
    return dispatched, run_id
