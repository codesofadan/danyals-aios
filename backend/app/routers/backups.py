"""Backups module endpoints (7G-1): nightly/manual Postgres snapshots, the config
panel, the guarded restore, and the (static) protected-store + storage catalogues.

Auth mirrors the 0026 RLS boundary:

* Reads (snapshots / config / stores / storage) require any provisioned staff
  (``view_reports``, which a portal client does NOT hold - so clients are 403'd out of
  the backups namespace, mirroring tasks/reports/settings).
* Running a snapshot and editing the config (toggle nightly/offsite, retention) are
  owner/admin only (``require_role``), matching the singleton manage policy.
* Restore is OWNER-ONLY and doubly guarded - the body must confirm the snapshot id -
  because it overwrites the live database.

Responses are the frontend ``Snapshot`` / ``ProtectedStore`` / ``StorageSeg`` /
``backupConfig`` shapes (``lib/backups.ts``). Every mutation records an ``access``
activity entry.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_owner, require_perm, require_role
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.db.backups_repo import BackupsRepoDep
from app.schemas.backups import (
    PROTECTED_STORES,
    STORAGE_SEGMENTS,
    BackupConfigResponse,
    BackupConfigUpdate,
    ProtectedStoreResponse,
    RestoreRequest,
    SnapshotResponse,
    SnapshotRunRequest,
    StorageSegResponse,
)
from app.services.activity import record_activity
from app.services.backups import BackupService, build_backup_service

router = APIRouter(tags=["backups"])

# All six staff roles hold view_reports; a portal client does NOT (confined out of
# the staff namespace, mirroring reports.py / settings.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Running a snapshot + editing config: owner/admin (the singleton manage set).
ManageBackups = Annotated[CurrentUser, Depends(require_role("owner", "admin"))]
# Restore is owner-only (it overwrites the live DB).
OwnerOnly = Annotated[CurrentUser, Depends(require_owner())]

_SNAPSHOT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found"
)


def get_backup_service(repo: BackupsRepoDep, settings: SettingsDep) -> BackupService:
    """Dependency: the backups service bound to the caller's RLS-scoped repo + the
    (key-gated) offsite store. Overridable in tests with a fake service."""
    return build_backup_service(repo, settings)


BackupServiceDep = Annotated[BackupService, Depends(get_backup_service)]


async def _config_response(repo: BackupsRepoDep) -> BackupConfigResponse:
    """Build the config response (the singleton row + the live snapshot count)."""
    row = await asyncio.to_thread(repo.get_config)
    retained = await asyncio.to_thread(repo.count_snapshots)
    return BackupConfigResponse.from_row(row, retained=retained)


# --- Reads (any staff) -------------------------------------------------------
@router.get("/backups/snapshots", response_model=list[SnapshotResponse])
async def list_snapshots(
    repo: BackupsRepoDep, page: PageDep, _user: ViewReports
) -> list[SnapshotResponse]:
    """The snapshot ledger (most recent first)."""
    rows = await asyncio.to_thread(repo.list_snapshots, limit=page.limit, offset=page.offset)
    return [SnapshotResponse.from_row(r) for r in rows]


@router.get("/backups/config", response_model=BackupConfigResponse)
async def get_config(repo: BackupsRepoDep, _user: ViewReports) -> BackupConfigResponse:
    """The backup config panel: the schedule + toggles + the derived counters. Falls
    back to the defaults if the singleton has never been saved."""
    return await _config_response(repo)


@router.get("/backups/stores", response_model=list[ProtectedStoreResponse])
async def list_stores(_user: ViewReports) -> list[ProtectedStoreResponse]:
    """What a snapshot protects (Postgres / files / vault / redis). A static catalogue."""
    return list(PROTECTED_STORES)


@router.get("/backups/storage", response_model=list[StorageSegResponse])
async def list_storage(_user: ViewReports) -> list[StorageSegResponse]:
    """The VPS-volume storage breakdown by segment. A static catalogue."""
    return list(STORAGE_SEGMENTS)


# --- Run a snapshot (owner/admin) --------------------------------------------
@router.post(
    "/backups/run", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED
)
async def run_backup(
    body: SnapshotRunRequest, service: BackupServiceDep, actor: ManageBackups
) -> SnapshotResponse:
    """Kick off a manual snapshot now (owner/admin). Records a ledger row either way -
    a degraded run (no dump root/binary) lands a ``failed`` row rather than erroring."""
    row = await asyncio.to_thread(service.run_snapshot, snap_type=body.type, scope=body.scope)
    await record_activity(
        actor, kind="access", action="ran a manual backup", target=body.scope
    )
    return SnapshotResponse.from_row(row)


# --- Restore (owner-only, guarded) -------------------------------------------
@router.post("/backups/{snapshot_id}/restore")
async def restore_backup(
    snapshot_id: str,
    body: RestoreRequest,
    repo: BackupsRepoDep,
    service: BackupServiceDep,
    actor: OwnerOnly,
) -> dict[str, Any]:
    """Restore a snapshot over the live database (OWNER-ONLY, doubly guarded). The
    body's ``confirm`` must echo the snapshot id. 404 if unknown; 400 on any guard
    failure (bad confirmation, non-successful snapshot, missing artifact)."""
    snap = await asyncio.to_thread(repo.get_snapshot, snapshot_id)
    if snap is None:
        raise _SNAPSHOT_NOT_FOUND
    result = await asyncio.to_thread(service.restore, snapshot_id, confirm=body.confirm)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.error or "restore failed"
        )
    await record_activity(
        actor, kind="access", action="restored a backup snapshot", target=snapshot_id
    )
    return {"restored": True, "id": snapshot_id}


# --- Config (owner/admin) ----------------------------------------------------
@router.put("/backups/config", response_model=BackupConfigResponse)
async def put_config(
    body: BackupConfigUpdate, repo: BackupsRepoDep, actor: ManageBackups
) -> BackupConfigResponse:
    """Edit the schedule + toggle nightly/offsite (owner/admin). Only the provided
    fields change."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return await _config_response(repo)
    await asyncio.to_thread(repo.update_config, changes)
    await record_activity(
        actor, kind="access", action="updated backup settings", target="Backups"
    )
    return await _config_response(repo)
