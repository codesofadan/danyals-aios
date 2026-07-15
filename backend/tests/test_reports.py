"""Unit tests for the Reports module (7D): the response/request models (contract
shapes + §3 enum fidelity), the Google Sheets seam (key-gating + fake), the SheetStore
Redis write-buffer (N writes -> 1 batched flush, quota behaviour, keyless degrade), and
the /reports endpoints with a faked repo + an in-memory SheetStore (no DB, no network).

The frontend contract (``lib/reports.ts``) is the source of truth: every union is
pinned verbatim and the internal ``client_id`` never leaks.
"""

from __future__ import annotations

import json
import typing
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.reports_repo import get_reports_repo, workbook_tabs
from app.routers.reports import get_sheetstore
from app.schemas.reports import (
    REPORT_TYPES,
    Dataset,
    ReportTypeResponse,
    SyncEventResponse,
    SyncStatus,
    WorkbookResponse,
)
from app.services.sheetstore import DATASET_TAB, SHEET_TABS, SheetStore
from integrations.errors import ProviderNotConfiguredError
from integrations.sheets import (
    FakeSheetsClient,
    GoogleSheetsClient,
    SheetRange,
    SheetsClient,
    connection_info_from_settings,
    sheets_client_from_settings,
)

pytestmark = pytest.mark.unit

_WORKBOOK_KEYS = {"id", "client", "sheet", "tabs", "rows", "lastSync", "status"}
_REPORTTYPE_KEYS = {"key", "title", "desc", "columns"}
_SYNCEVENT_KEYS = {"id", "client", "dataset", "rows", "ago"}


def _emitted(model: type[Any]) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --- schema shape / enum fidelity --------------------------------------------


def test_response_models_emit_exactly_the_contract_keys() -> None:
    assert _emitted(WorkbookResponse) == _WORKBOOK_KEYS
    assert _emitted(SyncEventResponse) == _SYNCEVENT_KEYS
    assert _emitted(ReportTypeResponse) == _REPORTTYPE_KEYS


def test_unions_are_pinned_verbatim() -> None:
    assert set(typing.get_args(Dataset)) == {"audit", "content", "milestones"}
    assert set(typing.get_args(SyncStatus)) == {"synced", "syncing", "error"}


def test_report_types_mirror_the_frontend_catalogue() -> None:
    assert [rt.key for rt in REPORT_TYPES] == ["audit", "content", "milestones"]
    audit = next(rt for rt in REPORT_TYPES if rt.key == "audit")
    assert audit.title == "Audit scores"
    assert "Run date" in audit.columns  # the exact column string round-trips


# --- from_row mapping ---------------------------------------------------------


def _workbook_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "wb-uuid",
        "client_id": "cl-secret",
        "client_name": "NorthPeak Dental",
        "sheet_id": "1a7Fq_D4x",
        "tabs": ["audit", "content", "milestones"],
        "rows_synced_today": 428,
        "last_sync": datetime(2026, 7, 16, tzinfo=UTC),
        "status": "synced",
    }
    row.update(over)
    return row


def test_workbook_from_row_aliases_and_hides_client_id() -> None:
    dumped = WorkbookResponse.from_row(_workbook_row()).model_dump(by_alias=True)
    assert set(dumped) == _WORKBOOK_KEYS
    assert "client_id" not in dumped
    assert dumped["client"] == "NorthPeak Dental"
    assert dumped["sheet"] == "1a7Fq_D4x"
    assert dumped["tabs"] == ["audit", "content", "milestones"]
    assert dumped["rows"] == 428


def test_workbook_from_row_filters_unknown_tabs_and_status() -> None:
    resp = WorkbookResponse.from_row(
        _workbook_row(tabs=["audit", "bogus", "content", "audit"], status="???", last_sync=None)
    )
    # unknown dropped + deduped, order preserved; bad status falls back; empty date.
    assert resp.tabs == ["audit", "content"]
    assert resp.status == "synced"
    assert resp.last_sync == "never"


def _event_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "ev-uuid",
        "client_id": "cl-secret",
        "client_name": "Meridian Wealth",
        "dataset": "audit",
        "rows": 128,
        "synced_at": datetime(2026, 7, 16, tzinfo=UTC),
    }
    row.update(over)
    return row


def test_sync_event_from_row_maps_and_hides_client_id() -> None:
    dumped = SyncEventResponse.from_row(_event_row()).model_dump(by_alias=True)
    assert set(dumped) == _SYNCEVENT_KEYS
    assert "client_id" not in dumped
    assert dumped["dataset"] == "audit"
    assert dumped["rows"] == 128


def test_sync_event_unknown_dataset_falls_back() -> None:
    assert SyncEventResponse.from_row(_event_row(dataset="???")).dataset == "audit"


def test_workbook_tabs_helper_tolerates_json_string() -> None:
    assert workbook_tabs({"tabs": ["audit", "content"]}) == ["audit", "content"]
    assert workbook_tabs({"tabs": json.dumps(["milestones"])}) == ["milestones"]
    assert workbook_tabs({"tabs": None}) == []


# --- the Google Sheets seam ---------------------------------------------------


def test_fake_sheets_client_satisfies_protocol_and_batches() -> None:
    fake = FakeSheetsClient()
    assert isinstance(fake, SheetsClient)
    written = fake.batch_update(
        "sheet-1",
        [SheetRange(tab="audits", rows=[[1, 2], [3, 4]]), SheetRange(tab="milestones", rows=[[5]])],
    )
    assert written == 3
    assert fake.calls == 1
    assert fake.store["sheet-1"]["audits"] == [[1, 2], [3, 4]]
    assert fake.batch_update("sheet-1", []) == 0  # empty is a no-op, no extra call
    assert fake.calls == 1


def test_google_sheets_client_requires_a_credential() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="Google Sheets"):
        GoogleSheetsClient(credentials_json="")
    with pytest.raises(ProviderNotConfiguredError, match="not valid JSON"):
        GoogleSheetsClient(credentials_json="not-json")


def test_sheets_factory_degrades_without_credentials() -> None:
    assert sheets_client_from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]
    info = connection_info_from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    assert info.connected is False
    assert info.service_account_email == ""


def test_sheets_factory_degrades_on_bad_credential_json() -> None:
    # A present-but-invalid credential must DEGRADE to None (never raise) so the
    # connection panel still renders.
    settings = Settings(_env_file=None, google_sheets_sa_json="not-json")  # type: ignore[call-arg]
    assert sheets_client_from_settings(settings) is None
    assert connection_info_from_settings(settings).connected is False


# --- the SheetStore Redis write-buffer ----------------------------------------


class FakeRedis:
    """A minimal async in-memory Redis supporting exactly the ops SheetStore uses."""

    def __init__(self) -> None:
        self.lists: dict[str, list[bytes]] = {}
        self.sets: dict[str, set[bytes]] = {}
        self.nums: dict[str, int] = {}

    @staticmethod
    def _b(value: Any) -> bytes:
        return value if isinstance(value, bytes) else str(value).encode()

    async def rpush(self, key: str, *values: Any) -> int:
        bucket = self.lists.setdefault(key, [])
        bucket.extend(self._b(v) for v in values)
        return len(bucket)

    async def sadd(self, key: str, *members: Any) -> int:
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(self._b(m) for m in members)
        return len(bucket) - before

    async def smembers(self, key: str) -> set[bytes]:
        return set(self.sets.get(key, set()))

    async def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        data = self.lists.get(key, [])
        return data[start:] if end == -1 else data[start : end + 1]

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def incrby(self, key: str, amount: int) -> int:
        self.nums[key] = self.nums.get(key, 0) + amount
        return self.nums[key]

    async def get(self, key: str) -> bytes | None:
        if key in self.nums:
            return str(self.nums[key]).encode()
        return None

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            for store in (self.lists, self.sets, self.nums):
                if key in store:
                    del store[key]
                    n += 1
        return n


def test_sheet_tabs_and_dataset_mapping() -> None:
    assert sorted(SHEET_TABS) == [
        "audits", "backlinks", "citations", "content_jobs", "milestones", "web2"
    ]
    assert DATASET_TAB == {"audit": "audits", "content": "content_jobs", "milestones": "milestones"}


async def test_write_rejects_an_unknown_tab() -> None:
    store = SheetStore(FakeRedis(), FakeSheetsClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown sheet tab"):
        await store.write("sheet-1", "not_a_tab", [[1]])


async def test_many_writes_coalesce_into_one_batched_flush() -> None:
    redis = FakeRedis()
    client = FakeSheetsClient()
    store = SheetStore(redis, client)  # type: ignore[arg-type]
    sid = "sheet-1"

    # 10 writes across three tabs -> 24 rows buffered, ZERO API calls so far.
    total = 0
    for _ in range(5):
        total += await store.write(sid, "audits", [["a"], ["b"]])
    for _ in range(3):
        total += await store.write(sid, "content_jobs", [["c"]])
    for _ in range(2):
        total += await store.write(sid, "milestones", [["m"], ["n"], ["o"]])
    assert total == 5 * 2 + 3 * 1 + 2 * 3
    assert client.calls == 0
    stats = await store.buffer_stats()
    assert stats.queued == total and stats.flushed_today == 0

    # ONE flush -> exactly ONE batchUpdate for the whole workbook (quota-safe).
    result = await store.flush(sid)
    assert client.calls == 1
    assert result.batched is True and result.degraded is False
    assert result.total == total
    assert result.per_tab == {"audits": 10, "content_jobs": 3, "milestones": 6}
    # The single batch carried one range per distinct tab.
    _, ranges = client.batches[0]
    assert {r.tab for r in ranges} == {"audits", "content_jobs", "milestones"}

    # Buffer drained; queued back to 0; flushed_today advanced.
    after = await store.buffer_stats()
    assert after.queued == 0 and after.flushed_today == total

    # A second flush is a no-op (nothing buffered) - no extra API call.
    again = await store.flush(sid)
    assert again.total == 0 and client.calls == 1


async def test_flush_degrades_cleanly_without_a_client() -> None:
    redis = FakeRedis()
    store = SheetStore(redis, None)  # no Sheets key configured
    sid = "sheet-x"
    await store.write(sid, "audits", [["a"], ["b"]])

    result = await store.flush(sid)
    assert result.degraded is True and result.batched is False
    assert result.total == 2  # reports what WOULD flush
    # The buffer is RETAINED (held until the key lands), not dropped.
    stats = await store.buffer_stats()
    assert stats.queued == 2 and stats.flushed_today == 0
    assert await store.pending(sid) == {"audits": 2}


# --- endpoints (faked repo + in-memory store) ---------------------------------


class FakeReportsRepo:
    def __init__(self) -> None:
        self.workbooks: list[dict[str, Any]] = []
        self.master: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        self.synced: list[str] = []

    def list_workbooks(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self.workbooks

    def get_workbook(self, workbook_id: str) -> dict[str, Any] | None:
        return next((w for w in self.workbooks if str(w["id"]) == workbook_id), None)

    def get_master(self) -> dict[str, Any] | None:
        return self.master

    def mark_synced(self, workbook_id: str, *, rows_added: int) -> dict[str, Any] | None:
        wb = self.get_workbook(workbook_id)
        if wb is None:
            return None
        wb["status"] = "synced"
        wb["rows_synced_today"] = wb.get("rows_synced_today", 0) + rows_added
        self.synced.append(workbook_id)
        return wb

    def insert_sync_event(
        self, *, workbook_id: str, client_name: str, dataset: str, rows: int
    ) -> dict[str, Any]:
        ev = {
            "id": f"ev-{len(self.events)}",
            "workbook_id": workbook_id,
            "client_name": client_name,
            "dataset": dataset,
            "rows": rows,
            "synced_at": datetime.now(UTC),
        }
        self.events.append(ev)
        return ev

    def list_sync_events(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return list(reversed(self.events))


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeReportsRepo:
    return FakeReportsRepo()


@pytest.fixture
def sheets() -> FakeSheetsClient:
    return FakeSheetsClient()


@pytest.fixture
def store(sheets: FakeSheetsClient) -> SheetStore:
    return SheetStore(FakeRedis(), sheets)  # type: ignore[arg-type]


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeReportsRepo, store: SheetStore
) -> Callable[..., None]:
    app.dependency_overrides[get_reports_repo] = lambda: repo
    app.dependency_overrides[get_sheetstore] = lambda: store

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_client_forbidden_from_all_reads(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/reports/workbooks")).status_code == 403
    assert (await client.get("/api/v1/reports/sync-events")).status_code == 403
    assert (await client.get("/api/v1/reports/types")).status_code == 403
    assert (await client.get("/api/v1/reports/connection")).status_code == 403


async def test_workbooks_shape_hides_client_id(
    client: httpx.AsyncClient, repo: FakeReportsRepo, wire: Callable[..., None]
) -> None:
    repo.workbooks = [_workbook_row(id="wb-1")]
    wire("viewer")
    resp = await client.get("/api/v1/reports/workbooks")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == _WORKBOOK_KEYS
    assert "client_id" not in body[0]
    assert body[0]["tabs"] == ["audit", "content", "milestones"]


async def test_types_endpoint_returns_the_three_reports(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/reports/types")
    assert resp.status_code == 200
    body = resp.json()
    assert {rt["key"] for rt in body} == {"audit", "content", "milestones"}


async def test_connection_assembles_master_and_buffer(
    client: httpx.AsyncClient, repo: FakeReportsRepo, wire: Callable[..., None]
) -> None:
    repo.master = {
        "id": "wb-master", "client_name": "Master Rollup", "sheet_id": "1M4st_RollupX",
        "tabs": ["audit", "content", "milestones"], "is_master": True,
    }
    wire("viewer")
    resp = await client.get("/api/v1/reports/connection")
    assert resp.status_code == 200
    body = resp.json()
    # No Google key in dev settings -> degraded/disconnected, but the panel renders.
    assert body["connected"] is False
    assert body["master"]["sheet"] == "1M4st_RollupX"
    assert body["master"]["tabs"] == 3
    assert set(body["buffer"]) == {"label", "ok", "queued", "flushedToday"}
    assert body["buffer"]["queued"] == 0


async def test_sync_is_lead_only(
    client: httpx.AsyncClient, repo: FakeReportsRepo, wire: Callable[..., None]
) -> None:
    repo.workbooks = [_workbook_row(id="wb-1")]
    wire("specialist")  # holds view_reports but is not a lead
    resp = await client.post("/api/v1/reports/sync", json={"workbookId": "wb-1"})
    assert resp.status_code == 403


async def test_sync_missing_workbook_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/reports/sync", json={"workbookId": "nope"})
    assert resp.status_code == 404


async def test_sync_optimistically_marks_synced_and_pushes_buffer(
    client: httpx.AsyncClient,
    repo: FakeReportsRepo,
    store: SheetStore,
    sheets: FakeSheetsClient,
    wire: Callable[..., None],
) -> None:
    repo.workbooks = [
        _workbook_row(id="wb-1", sheet_id="sheet-1", tabs=["audit", "content"], status="syncing")
    ]
    # Modules have buffered rows for this workbook's datasets.
    await store.write("sheet-1", "audits", [["a"], ["b"]])
    await store.write("sheet-1", "content_jobs", [["c"]])

    wire("manager", "u-lead")
    resp = await client.post("/api/v1/reports/sync", json={"workbookId": "wb-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "synced"  # optimistic transition
    assert "client_id" not in body

    # ONE batched push happened; a per-dataset event was recorded with real counts.
    assert sheets.calls == 1
    assert repo.synced == ["wb-1"]
    by_dataset = {e["dataset"]: e["rows"] for e in repo.events}
    assert by_dataset == {"audit": 2, "content": 1}


async def test_sync_all_marks_every_workbook(
    client: httpx.AsyncClient, repo: FakeReportsRepo, wire: Callable[..., None]
) -> None:
    repo.workbooks = [
        _workbook_row(id="wb-1", sheet_id="s1", tabs=["audit"], status="syncing"),
        _workbook_row(id="wb-2", sheet_id="s2", tabs=["milestones"], status="error"),
    ]
    wire("admin", "u-admin")
    resp = await client.post("/api/v1/reports/sync-all", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert [w["status"] for w in body] == ["synced", "synced"]
    assert set(repo.synced) == {"wb-1", "wb-2"}


async def test_sync_events_feed_shape(
    client: httpx.AsyncClient, repo: FakeReportsRepo, wire: Callable[..., None]
) -> None:
    repo.events = [
        {"id": "ev-0", "client_name": "Lumen Realty", "dataset": "audit", "rows": 176,
         "synced_at": datetime(2026, 7, 16, tzinfo=UTC)},
    ]
    wire("viewer")
    resp = await client.get("/api/v1/reports/sync-events")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == _SYNCEVENT_KEYS
    assert body[0]["dataset"] == "audit"
    assert body[0]["rows"] == 176
