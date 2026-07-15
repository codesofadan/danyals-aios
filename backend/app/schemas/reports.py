"""Reports module request/response models in the frontend shapes (``lib/reports.ts``).

Three response models mirror their TS types EXACTLY (order-independent, but the
emitted keys must equal the TS field set - the contract-lock test enforces it):

* ``WorkbookResponse``  <-> ``Workbook``   ({id, client, sheet, tabs, rows,
  lastSync, status}).
* ``ReportTypeResponse`` <-> ``ReportType`` ({key, title, desc, columns}).
* ``SyncEventResponse``  <-> ``SyncEvent``  ({id, client, dataset, rows, ago}).

Python attributes stay snake_case and re-alias to the camelCase wire key via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). ``id`` is the
row uuid (a string) used purely as a React key; the internal ``client_id`` never
leaks (``client`` is the snapshotted display name). ``lastSync`` / ``ago`` are
relative ("2m ago"); ``rows`` is the rows-synced-today count.

§3 ENUM FIDELITY: ``SyncStatus`` and ``Dataset`` are pinned verbatim to
``reports.ts``. The 3 ``REPORT_TYPES`` (audit / content / milestones + the exact
column strings) are surfaced as constants so ``GET /reports/types`` is pre-populated.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.util.timefmt import relative_ago

# Unions verbatim from reports.ts. Same values front + back - no display remapping.
Dataset = Literal["audit", "content", "milestones"]
SyncStatus = Literal["synced", "syncing", "error"]

_DATASETS: frozenset[str] = frozenset({"audit", "content", "milestones"})
_SYNC_STATUSES: frozenset[str] = frozenset({"synced", "syncing", "error"})


def _clean_tabs(value: Any) -> list[Dataset]:
    """Coerce a stored ``tabs`` jsonb array into a list of valid ``Dataset`` values
    (dropping anything unrecognised), order-preserving + deduped."""
    if not isinstance(value, list):
        return []
    out: list[Dataset] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str) and item in _DATASETS and item not in seen:
            seen.add(item)
            out.append(item)  # type: ignore[arg-type]  # narrowed to a Dataset literal above
    return out


class WorkbookResponse(BaseModel):
    """One client (or master) workbook in the frontend ``Workbook`` shape - and ONLY
    those 7 keys. ``id`` is the row uuid; ``client`` is the snapshotted display name so
    the internal ``client_id`` never leaks; ``sheet`` is the spreadsheet id fragment."""

    id: str
    client: str
    sheet: str
    tabs: list[Dataset]
    rows: int
    last_sync: str = Field(serialization_alias="lastSync")
    status: SyncStatus

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> WorkbookResponse:
        status = row.get("status")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            sheet=row.get("sheet_id", ""),
            tabs=_clean_tabs(row.get("tabs")),
            rows=int(row.get("rows_synced_today", 0) or 0),
            last_sync=relative_ago(row.get("last_sync"), empty="never"),
            status=status if status in _SYNC_STATUSES else "synced",
        )


class ReportTypeResponse(BaseModel):
    """One report type in the frontend ``ReportType`` shape - and ONLY those 4 keys.
    ``key`` is the ``Dataset`` the report writes; ``columns`` is the human-readable
    column list written to that tab."""

    key: Dataset
    title: str
    desc: str
    columns: str


class SyncEventResponse(BaseModel):
    """One sync push in the frontend ``SyncEvent`` shape - and ONLY those 5 keys.
    ``id`` is the event uuid; ``client`` is the snapshot; ``ago`` is relative."""

    id: str
    client: str
    dataset: Dataset
    rows: int
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SyncEventResponse:
        dataset = row.get("dataset")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            dataset=dataset if dataset in _DATASETS else "audit",
            rows=int(row.get("rows", 0) or 0),
            ago=relative_ago(row.get("synced_at"), empty="just now"),
        )


# The 3 report types + their exact column strings, verbatim from reports.ts
# ``reportTypes``. Surfaced by ``GET /reports/types`` so the panel is pre-populated.
REPORT_TYPES: list[ReportTypeResponse] = [
    ReportTypeResponse(
        key="audit",
        title="Audit scores",
        desc="Every free & paid audit run, rolled up per site.",
        columns="Site · Category · Score · Δ vs last · Issues · Fixed · Run date",
    ),
    ReportTypeResponse(
        key="content",
        title="Content status",
        desc="Content-job pipeline state as drafts move to live.",
        columns="Job · Type · Stage · Assignee · Words · Published URL · Updated",
    ),
    ReportTypeResponse(
        key="milestones",
        title="Milestone state",
        desc="Onboarding & delivery milestones per engagement.",
        columns="Milestone · Owner · Due · Status · Completed · Progress %",
    ),
]


# --- Request models -----------------------------------------------------------


class SyncRequest(BaseModel):
    """POST /reports/sync body: push one workbook's datasets to its sheet.

    ``workbook_id`` is the workbook row uuid. The push flushes the Redis write-buffer
    for that workbook through the (key-gated) SheetStore and optimistically transitions
    the workbook to ``synced``.
    """

    workbook_id: str = Field(alias="workbookId", min_length=1)


# --- Connection / buffer status (the Sheets connection panel) -----------------
# reports.ts ``sheetsConnection`` is a plain const, not an ``export type``, so this
# is NOT contract-locked; the keys mirror it so the panel lights up unchanged.


class MasterRollupResponse(BaseModel):
    """The master-rollup workbook summary (frontend ``sheetsConnection.master``)."""

    name: str
    sheet: str
    tabs: int


class BufferStatsResponse(BaseModel):
    """The Redis write-buffer stats (frontend ``sheetsConnection.buffer``)."""

    label: str = "Redis write-buffer"
    ok: bool
    queued: int  # rows waiting to flush
    flushed_today: int = Field(serialization_alias="flushedToday")


class ConnectionResponse(BaseModel):
    """The Sheets connection panel (frontend ``sheetsConnection``). ``connected`` is
    true only when a real service-account credential is configured; otherwise the
    module degrades cleanly (empty account, ``connected=false``) with no key."""

    account: str
    account_short: str = Field(serialization_alias="accountShort")
    project: str
    scope: str
    connected: bool
    master: MasterRollupResponse
    buffer: BufferStatsResponse
