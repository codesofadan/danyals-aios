"""The SheetStore adapter (7D): the operational store behind a quota-safe buffer.

The audit / content / milestone modules push rows to a client's Google Sheets
workbook through THIS adapter, never the Sheets API directly. Two moving parts:

* a REDIS WRITE-BUFFER - ``write(spreadsheet_id, tab, rows)`` appends rows to a
  per-workbook / per-tab Redis list and bumps a global ``queued`` counter. Nothing
  hits Google here, so a burst of module writes costs zero API quota.
* a QUOTA-SAFE FLUSH - ``flush(spreadsheet_id)`` drains every buffered tab for one
  workbook and emits exactly ONE batched ``batchUpdate`` through the injected
  ``SheetsClient`` (real or fake), then clears the buffer and bumps a ``flushed
  today`` counter. N writes -> 1 API call.

The SAME read/write shape holds whether the store is backed by the real
``GoogleSheetsClient`` or the ``FakeSheetsClient``; when NO client is configured
(no key) ``flush`` DEGRADES - it reports what WOULD be pushed but retains the
buffer, HELD until the credential lands (mirrors the context compactor holding its
watermark). All state lives in Redis so the store is horizontally shared and
survives a process restart.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import redis.asyncio as redis_asyncio

from app.logging_setup import get_logger
from integrations.sheets import SheetRange, SheetsClient

logger = get_logger("app.sheetstore")


def _aw(value: object) -> Awaitable[Any]:
    """Treat a redis reply (statically the ``ResponseT`` union ``Awaitable | T``) as
    the awaitable it always is on the async client - keeps the awaits mypy-strict."""
    return cast("Awaitable[Any]", value)

# The physical sheet tabs the operational store writes (broader than the 3 workbook
# datasets: off-page detail tabs feed the sheet but are not surfaced per-workbook).
SHEET_TABS: frozenset[str] = frozenset(
    {"audits", "content_jobs", "backlinks", "citations", "web2", "milestones"}
)

# Contract ``Dataset`` -> the physical sheet tab it lands on. The three datasets a
# workbook surfaces map 1:1; the off-page tabs have no workbook dataset.
DATASET_TAB: dict[str, str] = {
    "audit": "audits",
    "content": "content_jobs",
    "milestones": "milestones",
}

_PREFIX = "sheetbuf"
# The flushed-today counter is kept for two days then expires (a lazy daily roll).
_FLUSHED_TTL_SECONDS = 172_800


@dataclass(frozen=True)
class FlushResult:
    """The outcome of a flush. ``per_tab`` is rows-per-physical-tab (what was, or -
    when degraded - would be, pushed); ``batched`` is True iff a real ``batchUpdate``
    was emitted; ``degraded`` is True when no Sheets client was configured (the buffer
    is retained). ``total`` is the summed rows."""

    spreadsheet_id: str
    per_tab: dict[str, int] = field(default_factory=dict)
    total: int = 0
    batched: bool = False
    degraded: bool = False


@dataclass(frozen=True)
class BufferStats:
    """The write-buffer telemetry the connection panel reads: rows still ``queued``
    across all workbooks and rows ``flushed_today``. ``ok`` is False only when Redis
    could not be reached."""

    ok: bool
    queued: int
    flushed_today: int


class SheetStore:
    """Redis-buffered writer in front of a (key-gated) ``SheetsClient``.

    Construct with the shared async Redis client and an OPTIONAL ``SheetsClient``
    (``None`` = degraded / no key). Methods are async; the blocking Sheets call is
    offloaded off the event loop inside ``flush``.
    """

    def __init__(
        self,
        redis: redis_asyncio.Redis,
        client: SheetsClient | None,
        *,
        prefix: str = _PREFIX,
    ) -> None:
        self._redis = redis
        self._client = client
        self._prefix = prefix

    # --- keys -----------------------------------------------------------------
    def _rows_key(self, spreadsheet_id: str, tab: str) -> str:
        return f"{self._prefix}:{spreadsheet_id}:rows:{tab}"

    def _tabs_key(self, spreadsheet_id: str) -> str:
        return f"{self._prefix}:{spreadsheet_id}:tabs"

    def _queued_key(self) -> str:
        return f"{self._prefix}:queued"

    def _flushed_key(self, day: str) -> str:
        return f"{self._prefix}:flushed:{day}"

    # --- writes ---------------------------------------------------------------
    async def write(self, spreadsheet_id: str, tab: str, rows: list[list[Any]]) -> int:
        """Buffer ``rows`` for ``tab`` on ``spreadsheet_id`` (no API call). Returns the
        number of rows buffered. An unknown tab is a programming error (raises)."""
        if tab not in SHEET_TABS:
            raise ValueError(f"unknown sheet tab {tab!r}; expected one of {sorted(SHEET_TABS)}")
        if not rows:
            return 0
        encoded = [json.dumps(list(row)).encode() for row in rows]
        await _aw(self._redis.rpush(self._rows_key(spreadsheet_id, tab), *encoded))
        await _aw(self._redis.sadd(self._tabs_key(spreadsheet_id), tab))
        await _aw(self._redis.incrby(self._queued_key(), len(encoded)))
        return len(encoded)

    # --- flush ----------------------------------------------------------------
    async def _buffered_tabs(self, spreadsheet_id: str) -> list[str]:
        members = await _aw(self._redis.smembers(self._tabs_key(spreadsheet_id)))
        tabs = [m.decode() if isinstance(m, bytes | bytearray) else str(m) for m in members]
        # Deterministic order so a flush's ranges are stable across runs.
        return sorted(tabs)

    async def _read_ranges(
        self, spreadsheet_id: str, tabs: list[str]
    ) -> tuple[list[SheetRange], dict[str, int]]:
        ranges: list[SheetRange] = []
        per_tab: dict[str, int] = {}
        for tab in tabs:
            raw = await _aw(self._redis.lrange(self._rows_key(spreadsheet_id, tab), 0, -1))
            rows = [json.loads(item) for item in raw]
            if not rows:
                continue
            ranges.append(SheetRange(tab=tab, rows=rows))
            per_tab[tab] = len(rows)
        return ranges, per_tab

    async def flush(self, spreadsheet_id: str) -> FlushResult:
        """Drain ``spreadsheet_id``'s buffer and emit ONE batched ``batchUpdate``.

        With a configured client: one API round trip writes every buffered tab, the
        buffer is cleared, and the ``flushed_today`` counter advances. With NO client:
        the buffer is RETAINED and the result is marked ``degraded`` (reporting what
        would be pushed) - the push is deferred until the key lands.
        """
        tabs = await self._buffered_tabs(spreadsheet_id)
        ranges, per_tab = await self._read_ranges(spreadsheet_id, tabs)
        total = sum(per_tab.values())

        if not ranges:
            return FlushResult(spreadsheet_id=spreadsheet_id, per_tab={}, total=0, batched=False)

        if self._client is None:
            # Degraded: no key. Report what would flush; keep the buffer intact.
            logger.info("sheetstore_flush_degraded", spreadsheet_id=spreadsheet_id, queued=total)
            return FlushResult(
                spreadsheet_id=spreadsheet_id,
                per_tab=per_tab,
                total=total,
                batched=False,
                degraded=True,
            )

        # ONE batched call for the whole workbook (quota-safe), off the event loop.
        client = self._client
        await asyncio.to_thread(client.batch_update, spreadsheet_id, ranges)
        await self._drain(spreadsheet_id, tabs, total)
        return FlushResult(
            spreadsheet_id=spreadsheet_id,
            per_tab=per_tab,
            total=total,
            batched=True,
            degraded=False,
        )

    async def _drain(self, spreadsheet_id: str, tabs: list[str], total: int) -> None:
        """Clear a flushed workbook's buffer and move ``total`` from queued->flushed."""
        keys = [self._rows_key(spreadsheet_id, tab) for tab in tabs]
        keys.append(self._tabs_key(spreadsheet_id))
        if keys:
            await _aw(self._redis.delete(*keys))
        if total:
            await _aw(self._redis.incrby(self._queued_key(), -total))
            flushed_key = self._flushed_key(_today())
            await _aw(self._redis.incrby(flushed_key, total))
            await _aw(self._redis.expire(flushed_key, _FLUSHED_TTL_SECONDS))

    # --- telemetry ------------------------------------------------------------
    async def pending(self, spreadsheet_id: str) -> dict[str, int]:
        """Per-physical-tab rows currently buffered for a workbook (peek, no drain)."""
        tabs = await self._buffered_tabs(spreadsheet_id)
        out: dict[str, int] = {}
        for tab in tabs:
            n = await _aw(self._redis.llen(self._rows_key(spreadsheet_id, tab)))
            if n:
                out[tab] = int(n)
        return out

    async def buffer_stats(self) -> BufferStats:
        """The write-buffer telemetry for the connection panel. Fail-soft: any Redis
        error reports ``ok=False`` with zeroes rather than raising (the panel must
        render even when Redis is down)."""
        try:
            queued_raw = await _aw(self._redis.get(self._queued_key()))
            flushed_raw = await _aw(self._redis.get(self._flushed_key(_today())))
        except Exception:  # a down/unreachable Redis must never 500 the panel
            logger.warning("sheetstore_buffer_stats_unavailable")
            return BufferStats(ok=False, queued=0, flushed_today=0)
        return BufferStats(
            ok=True,
            queued=max(0, _as_int(queued_raw)),
            flushed_today=max(0, _as_int(flushed_raw)),
        )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _as_int(value: Any) -> int:
    """Coerce a Redis reply (bytes / str / int / None) to an int; 0 on anything odd."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
