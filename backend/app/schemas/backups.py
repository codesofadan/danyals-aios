"""Backups module request/response models in the frontend shapes (``lib/backups.ts``).

Four surfaces, all agency-global infra (no client_id ever leaks - there is none):

* ``SnapshotResponse`` mirrors ``Snapshot`` (the ledger row): ``id`` is the row uuid,
  and ``ts``/``size``/``duration`` are DERIVED display strings (the row stores the
  timestamp + raw ``size_bytes``/``duration_seconds``, formatted here via the shared
  ``timefmt`` helpers so the wire matches the frontend exactly).
* ``ProtectedStoreResponse`` mirrors ``ProtectedStore`` - a STATIC catalogue of what
  a snapshot protects (Postgres / files / vault / redis). Like ``NOTIF_EVENTS`` /
  ``REPORT_TYPES`` the presentation lives in code, surfaced through the endpoint.
* ``StorageSegResponse`` mirrors ``StorageSeg`` - the VPS-volume storage breakdown
  (also a static catalogue; ``StorageSeg`` is a single-line TS type so it is pinned
  in ``tests/test_backups.py``, not the shared contract lock which only parses the
  multi-line ``export type`` bodies).
* ``BackupConfigResponse`` mirrors the ``backupConfig`` const object: the schedule +
  toggles + the DERIVED counters (``retained`` = live snapshot count; ``lastBackupAgoH``
  / ``nextBackupInH`` computed from the config timestamps; ``restoreTested`` formatted).
  ``backupConfig`` is a const (not an ``export type``), so it is pinned in the module
  test rather than the shared contract lock.

Python attributes are snake_case with a ``serialization_alias`` (ruff N815 forbids a
raw camelCase attribute); the emitted JSON keys therefore match the TS types
one-for-one (the two ``export type`` models are locked by ``tests/test_contract_lock.py``).
Input models accept BOTH the camelCase wire key (``alias``) and the snake name
(``populate_by_name``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import format_date, format_runtime, format_when

# Unions verbatim from backups.ts (note the capitalized SnapType labels). Same
# values front + back - no display remapping.
SnapStatus = Literal["success", "running", "failed"]
SnapType = Literal["Nightly", "Manual"]

_SNAP_STATUSES: frozenset[str] = frozenset({"success", "running", "failed"})
_SNAP_TYPES: frozenset[str] = frozenset({"Nightly", "Manual"})

# The two scope labels the frontend renders (``Snapshot.scope`` comment). A nightly
# run is the DB (+ KB + vault); a manual/weekly "Full" also captures file artifacts.
SCOPE_DATABASE = "Database"
SCOPE_FULL = "Full (DB + files)"


# --------------------------------------------------------------------------- #
# Byte + time helpers (display only; never contract-checked)
# --------------------------------------------------------------------------- #
def format_size(num_bytes: int | float | None) -> str:
    """Humanize a byte count as the frontend's "1.82 GB"; 0/absent -> the em-dash "—"
    (a failed run has no artifact). B/KB are integer, MB and up carry two decimals."""
    if not num_bytes or float(num_bytes) <= 0:
        return "—"  # em-dash
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"  # pragma: no cover - loop always returns


def _to_dt(value: datetime | str | None) -> datetime | None:
    """Coerce a stored timestamptz (psycopg -> aware datetime) or iso string to an
    aware UTC datetime; unparseable/absent -> ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _hours_since(value: datetime | str | None) -> int:
    """Whole hours since a past timestamp (clamped >= 0; absent -> 0)."""
    dt = _to_dt(value)
    if dt is None:
        return 0
    return max(0, int((datetime.now(UTC) - dt).total_seconds() // 3600))


def _hours_until(value: datetime | str | None) -> int:
    """Whole hours until a future timestamp (clamped >= 0; absent -> 0)."""
    dt = _to_dt(value)
    if dt is None:
        return 0
    return max(0, int((dt - datetime.now(UTC)).total_seconds() // 3600))


# --------------------------------------------------------------------------- #
# Snapshot ledger
# --------------------------------------------------------------------------- #
class SnapshotResponse(BaseModel):
    """One snapshot in the frontend ``Snapshot`` shape - and ONLY those 7 keys.
    ``ts``/``size``/``duration`` are derived from the stored timestamp + raw
    ``size_bytes``/``duration_seconds``."""

    id: str
    ts: str
    type: SnapType
    scope: str
    size: str
    duration: str
    status: SnapStatus

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SnapshotResponse:
        snap_type = row.get("type")
        status = row.get("status")
        return cls(
            id=str(row["id"]),
            ts=format_when(row.get("created_at")),
            type=snap_type if snap_type in _SNAP_TYPES else "Manual",
            scope=row.get("scope") or SCOPE_DATABASE,
            size=format_size(row.get("size_bytes")),
            duration=format_runtime(row.get("duration_seconds")),
            status=status if status in _SNAP_STATUSES else "success",
        )


# --------------------------------------------------------------------------- #
# Protected stores (static catalogue - verbatim from backups.ts)
# --------------------------------------------------------------------------- #
class ProtectedStoreResponse(BaseModel):
    """One protected store in the frontend ``ProtectedStore`` shape - and ONLY those
    7 keys (``note`` optional)."""

    key: str
    name: str
    desc: str
    icon: str
    size: str
    included: bool
    note: str | None = None


PROTECTED_STORES: tuple[ProtectedStoreResponse, ...] = (
    ProtectedStoreResponse(
        key="postgres",
        name="Postgres database",
        desc=(
            "App data + knowledge base - clients, sites, audits, content jobs, "
            "milestones, and the Policy Radar KB."
        ),
        icon="database",
        size="1.8 GB",
        included=True,
    ),
    ProtectedStoreResponse(
        key="files",
        name="File artifacts",
        desc="Audit PDFs, generated content packages and AI images on the VPS volume.",
        icon="folder_zip",
        size="38.0 GB",
        included=True,
    ),
    ProtectedStoreResponse(
        key="vault",
        name="Encrypted key vault",
        desc="API keys + WordPress credentials - encrypted, never in logs.",
        icon="lock",
        size="12 KB",
        included=True,
    ),
    ProtectedStoreResponse(
        key="redis",
        name="Redis · queue + cache",
        desc="Job queue and cached API responses - ephemeral, rebuilt on restart.",
        icon="bolt",
        size="—",
        included=False,
        note="Ephemeral · not backed up",
    ),
)


# --------------------------------------------------------------------------- #
# Storage breakdown (static catalogue - verbatim from backups.ts)
# --------------------------------------------------------------------------- #
class StorageSegResponse(BaseModel):
    """One storage segment in the frontend ``StorageSeg`` shape - and ONLY those 4
    keys."""

    key: str
    label: str
    gb: float
    color: str


STORAGE_SEGMENTS: tuple[StorageSegResponse, ...] = (
    StorageSegResponse(key="files", label="File artifacts", gb=38.0, color="var(--c4)"),
    StorageSegResponse(key="postgres", label="Database + KB", gb=1.8, color="var(--c1)"),
    StorageSegResponse(key="vault", label="Key vault", gb=0.02, color="var(--c2)"),
)


# --------------------------------------------------------------------------- #
# Config singleton (mirrors the backupConfig const object)
# --------------------------------------------------------------------------- #
# The frontend defaults (backups.ts backupConfig) - one source of truth for the GET
# fallback before the singleton has ever been saved.
CONFIG_DEFAULTS: dict[str, Any] = {
    "nightly_time": "02:00 UTC",
    "retention_days": 30,
    "nightly_enabled": True,
    "offsite_enabled": False,
}


class BackupConfigResponse(BaseModel):
    """The backup config in the frontend ``backupConfig`` shape - and ONLY those 8
    keys. ``retained`` / ``lastBackupAgoH`` / ``nextBackupInH`` / ``restoreTested``
    are DERIVED (the live snapshot count + the config timestamps)."""

    nightly_time: str = Field(serialization_alias="nightlyTime")
    retention_days: int = Field(serialization_alias="retentionDays")
    retained: int
    last_backup_ago_h: int = Field(serialization_alias="lastBackupAgoH")
    next_backup_in_h: int = Field(serialization_alias="nextBackupInH")
    restore_tested: str = Field(serialization_alias="restoreTested")
    nightly_on: bool = Field(serialization_alias="nightlyOn")
    offsite_on: bool = Field(serialization_alias="offsiteOn")

    @classmethod
    def from_row(cls, row: dict[str, Any] | None, *, retained: int) -> BackupConfigResponse:
        row = row or {}
        nightly = row.get("nightly_enabled")
        offsite = row.get("offsite_enabled")
        return cls(
            nightly_time=row.get("nightly_time") or CONFIG_DEFAULTS["nightly_time"],
            retention_days=int(row.get("retention_days") or CONFIG_DEFAULTS["retention_days"]),
            retained=int(retained),
            last_backup_ago_h=_hours_since(row.get("last_backup")),
            next_backup_in_h=_hours_until(row.get("next_backup")),
            restore_tested=format_date(row.get("restore_tested_at"), empty="Never"),
            nightly_on=bool(nightly) if nightly is not None else CONFIG_DEFAULTS["nightly_enabled"],
            offsite_on=bool(offsite) if offsite is not None else CONFIG_DEFAULTS["offsite_enabled"],
        )


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class SnapshotRunRequest(BaseModel):
    """POST /backups/run body: kick off a snapshot (owner/admin). ``type`` defaults to
    a Manual run; ``scope`` defaults to the Database-only snapshot."""

    model_config = ConfigDict(populate_by_name=True)

    type: SnapType = "Manual"
    scope: str = Field(default=SCOPE_DATABASE, min_length=1)


class RestoreRequest(BaseModel):
    """POST /backups/{id}/restore body: the guarded restore confirmation (owner-only).

    ``confirm`` MUST echo the snapshot id being restored - a deliberate friction gate
    on top of the owner-only role check, so a restore (which overwrites the live DB)
    can never fire on a stray click."""

    confirm: str = Field(min_length=1)


class BackupConfigUpdate(BaseModel):
    """PUT /backups/config body: edit the schedule + toggle nightly/offsite
    (owner/admin). Every field optional; only those provided change. Accepts camelCase
    or snake."""

    model_config = ConfigDict(populate_by_name=True)

    nightly_time: str | None = Field(default=None, alias="nightlyTime", min_length=1)
    retention_days: int | None = Field(default=None, alias="retentionDays", ge=1, le=3650)
    nightly_enabled: bool | None = Field(default=None, alias="nightlyOn")
    offsite_enabled: bool | None = Field(default=None, alias="offsiteOn")
