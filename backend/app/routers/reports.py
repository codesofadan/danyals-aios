"""Reports module endpoints (7D): the Google-Sheets operational store.

Reads require any provisioned staff (``view_reports``, which a portal client does
NOT hold - so clients are 403'd out of this namespace, mirroring tasks/offpage/
milestones). Syncing (the push to Sheets) requires a LEAD (owner/admin/manager) - the
same set the RLS insert/update policies gate to; the app-layer 403 here is clean UX on
top of that DB boundary.

A sync is OPTIMISTIC: it flushes the workbook's Redis write-buffer through the
(key-gated) SheetStore - ONE batched ``batchUpdate`` per workbook - records a per-
dataset sync event, and transitions the workbook to ``synced``. With no Sheets key the
push DEGRADES (buffer retained) but the status still flips optimistically and events
record 0 rows pushed. Responses are the frontend ``Workbook`` / ``SyncEvent`` /
``ReportType`` shapes (``lib/reports.ts``); the internal ``client_id`` never leaks.
Every sync records an activity entry (kind=content, entity=client) so the reporting
work keeps each client's context fresh.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import RedisDep, SettingsDep
from app.core.pagination import PageDep
from app.db.reports_repo import ReportsRepoDep, workbook_tabs
from app.schemas.reports import (
    REPORT_TYPES,
    BufferStatsResponse,
    ConnectionResponse,
    MasterRollupResponse,
    ReportTypeResponse,
    SyncEventResponse,
    SyncRequest,
    WorkbookResponse,
)
from app.services.activity import record_activity
from app.services.deliverables import emit_deliverable
from app.services.scheduled_jobs import ScheduledJob, scheduled_jobs
from app.services.sheetstore import DATASET_TAB, FlushResult, SheetStore
from integrations.sheets import connection_info_from_settings, sheets_client_from_settings

router = APIRouter(tags=["reports"])

# All six staff roles hold view_reports; a portal client does NOT (clients are
# confined out of the staff namespace, mirroring tasks.py / offpage.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Syncing is lead-only (owner/admin/manager) - the RLS insert/update set. Owner
# auto-passes require_role.
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# How many client workbooks one /reports/sync-all pass touches (a safety bound).
_SYNC_ALL_LIMIT = 500

_WORKBOOK_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Workbook not found"
)


def get_sheetstore(redis: RedisDep, settings: SettingsDep) -> SheetStore:
    """Dependency: the Redis-buffered SheetStore fronting the (key-gated) client.

    ``sheets_client_from_settings`` degrades to ``None`` without a credential, so the
    store runs in HELD/degraded mode until the key lands.
    """
    return SheetStore(redis, sheets_client_from_settings(settings))


SheetStoreDep = Annotated[SheetStore, Depends(get_sheetstore)]


def _short_account(email: str) -> str:
    """Shorten a service-account email for the panel: keep the local part + the last
    three domain labels (``aios-sheets@…iam.gserviceaccount.com``)."""
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    labels = domain.split(".")
    if len(labels) <= 3:
        return email
    return f"{local}@…{'.'.join(labels[-3:])}"


async def _sync_one(
    repo: ReportsRepoDep, store: SheetStore, actor: CurrentUser, wb: dict[str, Any]
) -> dict[str, Any]:
    """Flush one workbook's buffer, record per-dataset events, flip it to synced.

    Only rows a REAL batched push actually wrote are counted (a degraded/keyless flush
    records 0 and retains the buffer); the status transition is optimistic either way.
    """
    workbook_id = str(wb["id"])
    sheet_id = str(wb.get("sheet_id") or "")
    client_name = wb.get("client_name", "")

    flush = (
        await store.flush(sheet_id)
        if sheet_id
        else FlushResult(spreadsheet_id="", per_tab={}, total=0, batched=False)
    )
    # Count only rows a real batched call wrote; a degraded flush pushed nothing.
    pushed = flush.per_tab if flush.batched else {}

    total_added = 0
    for dataset in workbook_tabs(wb):
        if dataset not in DATASET_TAB:  # tolerate a stray stored value
            continue
        rows = int(pushed.get(DATASET_TAB[dataset], 0))
        total_added += rows
        await asyncio.to_thread(
            repo.insert_sync_event,
            workbook_id=workbook_id,
            client_name=client_name,
            dataset=dataset,
            rows=rows,
        )

    updated = await asyncio.to_thread(repo.mark_synced, workbook_id, rows_added=total_added)

    # Publish a Monthly-report deliverable for the client whose workbook just synced
    # (best-effort; the emit never raises). An unlinked/master workbook is skipped.
    client_id = wb.get("client_id")
    if client_id:
        await asyncio.to_thread(
            emit_deliverable,
            client_id=str(client_id),
            client_name=client_name,
            title="Monthly SEO Report",
            kind="Monthly",
            requires="monthly_report",
            source_kind="report",
            source_id=workbook_id,
            icon="summarize",
        )
    return updated if updated is not None else wb


@router.get("/reports/workbooks", response_model=list[WorkbookResponse])
async def list_workbooks(
    repo: ReportsRepoDep, page: PageDep, _user: ViewReports
) -> list[WorkbookResponse]:
    """The per-client workbooks (freshest sync first). The master rollup is surfaced
    separately by ``GET /reports/connection``."""
    rows = await asyncio.to_thread(repo.list_workbooks, limit=page.limit, offset=page.offset)
    return [WorkbookResponse.from_row(r) for r in rows]


@router.get("/reports/sync-events", response_model=list[SyncEventResponse])
async def list_sync_events(
    repo: ReportsRepoDep, page: PageDep, _user: ViewReports
) -> list[SyncEventResponse]:
    """Recent sync pushes (newest first) - the sync-activity feed."""
    rows = await asyncio.to_thread(repo.list_sync_events, limit=page.limit, offset=page.offset)
    return [SyncEventResponse.from_row(r) for r in rows]


@router.get("/reports/types", response_model=list[ReportTypeResponse])
async def list_report_types(_user: ViewReports) -> list[ReportTypeResponse]:
    """What each report type writes to its tab (audit / content / milestones + the
    exact columns). A static, key-free catalogue."""
    return REPORT_TYPES


@router.get("/reports/scheduled-jobs", response_model=list[ScheduledJob])
async def list_scheduled_jobs(_user: ViewReports) -> list[ScheduledJob]:
    """The LIVE Celery beat schedule: each background job, what it does, and its
    human-readable cadence. Read from the SAME ``beat_schedule`` the beat process
    runs, so the panel never drifts from what is actually scheduled."""
    return await asyncio.to_thread(scheduled_jobs)


@router.get("/reports/connection", response_model=ConnectionResponse)
async def connection(
    repo: ReportsRepoDep, store: SheetStoreDep, settings: SettingsDep, _user: ViewReports
) -> ConnectionResponse:
    """The Sheets connection panel: the service account (non-secret identity), the
    master rollup workbook, and the Redis write-buffer stats. ``connected`` is true
    only when a real credential is configured; the panel renders either way."""
    info = connection_info_from_settings(settings)
    master = await asyncio.to_thread(repo.get_master)
    stats = await store.buffer_stats()

    if master is not None:
        master_resp = MasterRollupResponse(
            name=master.get("client_name") or "Master Rollup",
            sheet=str(master.get("sheet_id") or ""),
            tabs=len(workbook_tabs(master)),
        )
    else:
        master_resp = MasterRollupResponse(name="Master Rollup", sheet="", tabs=0)

    return ConnectionResponse(
        account=info.service_account_email,
        account_short=_short_account(info.service_account_email),
        project=info.project_id,
        scope=info.scope,
        connected=info.connected,
        master=master_resp,
        buffer=BufferStatsResponse(
            ok=stats.ok, queued=stats.queued, flushed_today=stats.flushed_today
        ),
    )


@router.post("/reports/sync", response_model=WorkbookResponse)
async def sync_workbook(
    body: SyncRequest, repo: ReportsRepoDep, store: SheetStoreDep, actor: Lead
) -> WorkbookResponse:
    """Push ONE workbook's datasets to its sheet (optimistic ``->synced``). Lead-only;
    404 if the workbook is unknown / not visible."""
    wb = await asyncio.to_thread(repo.get_workbook, body.workbook_id)
    if wb is None:
        raise _WORKBOOK_NOT_FOUND
    updated = await _sync_one(repo, store, actor, wb)

    client_id = wb.get("client_id")
    await record_activity(
        actor,
        kind="content",
        action="synced a report workbook",
        target=wb.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return WorkbookResponse.from_row(updated)


@router.post("/reports/sync-all", response_model=list[WorkbookResponse])
async def sync_all_workbooks(
    repo: ReportsRepoDep, store: SheetStoreDep, actor: Lead
) -> list[WorkbookResponse]:
    """Push EVERY client workbook (optimistic ``->synced``). Lead-only. Records one
    aggregate activity entry rather than spamming the feed per workbook."""
    workbooks = await asyncio.to_thread(repo.list_workbooks, limit=_SYNC_ALL_LIMIT, offset=0)
    updated = [await _sync_one(repo, store, actor, wb) for wb in workbooks]
    await record_activity(
        actor,
        kind="content",
        action="synced all report workbooks",
        target="All clients",
    )
    return [WorkbookResponse.from_row(r) for r in updated]
