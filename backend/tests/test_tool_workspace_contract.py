"""Tool-workspace contract: every ``GET /<tool>/workspace`` adapter must emit the
frontend ``lib/tools.ts`` ``EXTRAS[<tool_key>]`` shape BYTE-FOR-BYTE.

This is the Part-8 tool modules' substitute for ``test_contract_lock.py``. Those
modules are SERVER-AUTHORITATIVE (no ``lib/*.ts`` type mirrors their response
models), so the field-set lock does not apply - but the tool WORKSPACE is still
rendered generically by the dashboard off ``lib/tools.ts``, and the pieces the
renderer depends on positionally MUST match: the table's ``cols`` (a row is a
positional cell list - a reordered/renamed column silently misrenders every row),
the ``kpis[].label`` tiles, and the ``primary`` CTA.

So this file greps ``tools.ts`` (mirroring the TS-parsing technique in
``test_contract_lock.py``) and asserts the live adapter's JSON against it.

ADDING A LATER TOOL MODULE: append ONE entry to ``_TOOL_ADAPTERS`` below - do NOT
write a new bespoke file. Every test here is parametrized over that list, so one
line buys the whole contract sweep for the new module. An entry carries the
``tools.ts`` key, the workspace route, and a ``wire`` callable that installs the
module's fake repo (each module owns a different repo dependency, so the wiring -
and only the wiring - is per-module).

No DB, no network: the repo dependency is faked and the caller is an owner (whose
feature grant short-circuits before any grant lookup).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user

pytestmark = pytest.mark.unit

# Repo root: backend/tests/ -> backend/ -> repo root (as in test_contract_lock.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_TS = _REPO_ROOT / "frontend" / "lib" / "tools.ts"


# --------------------------------------------------------------------------- #
# The tools.ts EXTRAS reader.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolExtraTs:
    """The contract-bearing pieces of one ``EXTRAS[key]`` block in ``tools.ts``."""

    kpi_labels: list[str]
    table_title: str
    table_icon: str
    table_cols: list[str]
    primary_label: str
    primary_icon: str


def _extras_block(tool_key: str) -> str:
    """The raw body of ``EXTRAS[<tool_key>]``.

    Blocks are 2-space indented and close on a 2-space-indented ``},`` - the only
    such line inside a block belongs to the block itself, so the non-greedy match
    stops at the right brace.
    """
    src = _TOOLS_TS.read_text(encoding="utf-8")
    match = re.search(rf"^  {tool_key}: \{{$(.*?)^  \}},$", src, re.DOTALL | re.MULTILINE)
    assert match, f"EXTRAS['{tool_key}'] not found in {_TOOLS_TS}"
    return match.group(1)


def _quoted(text: str) -> list[str]:
    """Every double-quoted literal in ``text``, in source order."""
    return re.findall(r'"([^"]*)"', text)


def read_tool_extra(tool_key: str) -> ToolExtraTs:
    """Parse the contract-bearing fields of one ``tools.ts`` EXTRAS block.

    Every sub-parse asserts, so a regex that stops matching (a ``tools.ts``
    reformat, a renamed key) FAILS loudly instead of vacuously passing on empty
    data - the failure mode this whole file exists to prevent.
    """
    block = _extras_block(tool_key)

    # kpis: [ { label: "...", value: "..." }, ... ]  - scoped to the kpis array so
    # the primary CTA's `label` can never be harvested as a KPI tile.
    kpis = re.search(r"kpis:\s*\[(.*?)\n\s*\],", block, re.DOTALL)
    assert kpis, f"kpis array not parsed for '{tool_key}'"
    kpi_labels = re.findall(r'label:\s*"([^"]*)"', kpis.group(1))
    assert kpi_labels, f"no kpi labels parsed for '{tool_key}'"

    # table: { title: "...", icon: "...", cols: [...], rows: [...] }
    table = re.search(r"table:\s*\{(.*?)\n\s*\},", block, re.DOTALL)
    assert table, f"table block not parsed for '{tool_key}'"
    title = re.search(r'title:\s*"([^"]*)"', table.group(1))
    icon = re.search(r'icon:\s*"([^"]*)"', table.group(1))
    cols = re.search(r"cols:\s*\[([^\]]*)\]", table.group(1))
    assert title and icon and cols, f"table title/icon/cols not parsed for '{tool_key}'"
    table_cols = _quoted(cols.group(1))
    assert table_cols, f"no table cols parsed for '{tool_key}'"

    # primary: { label: "...", icon: "..." }
    primary = re.search(r'primary:\s*\{\s*label:\s*"([^"]*)",\s*icon:\s*"([^"]*)"\s*\}', block)
    assert primary, f"primary CTA not parsed for '{tool_key}'"

    return ToolExtraTs(
        kpi_labels=kpi_labels,
        table_title=title.group(1),
        table_icon=icon.group(1),
        table_cols=table_cols,
        primary_label=primary.group(1),
        primary_icon=primary.group(2),
    )


# --------------------------------------------------------------------------- #
# The registry: ONE entry per tool module. Append here; never fork this file.
# --------------------------------------------------------------------------- #
class ToolAdapter(NamedTuple):
    """One module's workspace adapter under contract.

    ``tool_key``  - the ``lib/tools.ts`` EXTRAS key (= the RBAC feature key).
    ``path``      - the live workspace route.
    ``wire``      - installs the module's fake repo on the app; returns nothing.
    """

    tool_key: str
    path: str
    wire: Callable[[FastAPI], None]


def _wire_keyword_research(app: FastAPI) -> None:
    """Fake keyword repo: a two-row bank + non-zero stats (so the table + KPI tiles
    are actually populated - an empty adapter would pass the col lock vacuously)."""
    from app.modules.keyword_research.repo import get_keyword_repo

    class _FakeKeywordRepo:
        def keyword_stats(self) -> dict[str, Any]:
            return {"saved": 640, "clusters": 28, "avg_difficulty": 34.2}

        def list_keywords(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"keyword": "invisalign cost", "volume": 8100, "difficulty": 42.0,
                 "intent": "Commercial"},
                {"keyword": "realtor near me", "volume": 12400, "difficulty": 55.0,
                 "intent": "Local"},
            ]

    app.dependency_overrides[get_keyword_repo] = _FakeKeywordRepo


def _wire_billing(app: FastAPI) -> None:
    """Fake billing repo: a two-row ledger + non-zero tiles (so the table + KPI tiles
    are actually populated - an empty adapter would pass the col lock vacuously).

    ``subscription_mrr`` and ``invoice_counts`` are SEPARATE reads over separate
    tables by design (MRR is subscription-derived, never invoice-derived), so the
    fake mirrors that split rather than collapsing them into one stats dict.
    """
    from app.modules.billing.repo import get_billing_repo

    class _FakeBillingRepo:
        def subscription_mrr(self) -> int:
            return 28_400  # sum(clients.mrr) - NOT the invoices below

        def invoice_counts(self) -> dict[str, int]:
            return {"open_invoices": 3, "past_due": 1}

        def list_invoices(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"client_name": "Meridian Wealth", "total": 1490, "due_date": "2026-08-27",
                 "status": "paid"},
                {"client_name": "Atlas Legal", "total": 690, "due_date": "2026-07-05",
                 "status": "past_due"},
            ]

    app.dependency_overrides[get_billing_repo] = _FakeBillingRepo


_TOOL_ADAPTERS: list[ToolAdapter] = [
    ToolAdapter("keyword_research", "/api/v1/keyword-research/workspace", _wire_keyword_research),
    ToolAdapter("billing", "/api/v1/billing/workspace", _wire_billing),
]

_IDS = [a.tool_key for a in _TOOL_ADAPTERS]


def _owner() -> CurrentUser:
    """An owner caller: all-on, so ``require_feature`` short-circuits without the
    grant lookup (which would need a DB)."""
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000ff", email="owner@aios.dev", role="owner",
        status="active", name="Owner", title="", avatar_color="#7B69EE", phone="",
        two_fa=False,
    )


async def _fetch_workspace(app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter) -> Any:
    app.dependency_overrides[get_current_user] = _owner
    adapter.wire(app)
    resp = await client.get(adapter.path)
    assert resp.status_code == 200, f"{adapter.path}: {resp.status_code} {resp.text}"
    return resp.json()


# --------------------------------------------------------------------------- #
# 1. Reader guards - a bad regex must FAIL, never vacuously pass.
# --------------------------------------------------------------------------- #
def test_tools_ts_exists_and_declares_the_extras_map() -> None:
    src = _TOOLS_TS.read_text(encoding="utf-8")
    assert "const EXTRAS: Record<string, ToolExtra>" in src, (
        f"{_TOOLS_TS} no longer declares the EXTRAS map - this reader is parsing "
        "something else entirely"
    )


def test_reader_rejects_an_unknown_tool_key() -> None:
    # Proves the reader MATCHES rather than silently returning empty data: if this
    # ever stopped raising, every contract assertion below would pass vacuously.
    with pytest.raises(AssertionError, match="not found"):
        read_tool_extra("definitely_not_a_real_tool")


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
def test_reader_parses_real_data_for_every_registered_tool(adapter: ToolAdapter) -> None:
    ts = read_tool_extra(adapter.tool_key)
    assert ts.kpi_labels and all(ts.kpi_labels), "kpi labels missing/blank"
    assert ts.table_cols and all(ts.table_cols), "table cols missing/blank"
    assert ts.table_title and ts.table_icon, "table title/icon missing"
    assert ts.primary_label and ts.primary_icon, "primary CTA missing"


def test_registry_is_not_empty_and_has_unique_keys() -> None:
    # Guards against a refactor silently emptying the sweep (cf. test_contract_lock).
    assert _TOOL_ADAPTERS, "no tool adapters registered"
    assert len({a.tool_key for a in _TOOL_ADAPTERS}) == len(_TOOL_ADAPTERS)
    assert len({a.path for a in _TOOL_ADAPTERS}) == len(_TOOL_ADAPTERS)


# --------------------------------------------------------------------------- #
# 2. The contract: the live adapter vs tools.ts.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_table_cols_are_byte_identical_to_tools_ts(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    """The strictest lock: a table row is a POSITIONAL cell list, so a renamed or
    reordered column misrenders every row without any other test noticing."""
    body = await _fetch_workspace(app, client, adapter)
    ts = read_tool_extra(adapter.tool_key)
    assert body["table"]["cols"] == ts.table_cols, (
        f"{adapter.tool_key}: workspace cols drifted from tools.ts - "
        f"backend={body['table']['cols']} tools.ts={ts.table_cols}"
    )


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_kpi_labels_match_tools_ts(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    body = await _fetch_workspace(app, client, adapter)
    ts = read_tool_extra(adapter.tool_key)
    assert [k["label"] for k in body["kpis"]] == ts.kpi_labels


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_table_title_icon_and_primary_match_tools_ts(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    body = await _fetch_workspace(app, client, adapter)
    ts = read_tool_extra(adapter.tool_key)
    assert body["table"]["title"] == ts.table_title
    assert body["table"]["icon"] == ts.table_icon
    assert body["primary"] == {"label": ts.primary_label, "icon": ts.primary_icon}


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_rows_are_positional_and_match_the_col_count(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    """Every emitted row must be exactly as wide as ``cols`` and every cell must be
    the ``lib/tools.ts`` ``Cell`` union (a bare string OR ``{v, tone}``)."""
    body = await _fetch_workspace(app, client, adapter)
    tones = {"ok", "info", "warn", "mut", "crit"}
    width = len(body["table"]["cols"])
    rows = body["table"]["rows"]
    assert rows, f"{adapter.tool_key}: fake repo produced no rows - the col lock " \
                 "would pass vacuously"
    for row in rows:
        assert len(row) == width, f"row {row} is not {width} cells wide"
        for cell in row:
            if isinstance(cell, dict):
                assert set(cell) == {"v", "tone"}, f"bad toned cell {cell}"
                assert cell["tone"] in tones, f"unknown tone {cell['tone']}"
            else:
                assert isinstance(cell, str), f"cell {cell!r} is neither str nor {{v,tone}}"


@pytest.mark.parametrize("adapter", _TOOL_ADAPTERS, ids=_IDS)
async def test_workspace_emits_the_tool_extra_envelope(
    app: FastAPI, client: httpx.AsyncClient, adapter: ToolAdapter
) -> None:
    """The envelope is the ``lib/tools.ts`` ``ToolExtra``: kpis + bullets always,
    table + primary optional. Nothing else may appear."""
    body = await _fetch_workspace(app, client, adapter)
    assert set(body) <= {"kpis", "table", "primary", "bullets"}, f"extra keys: {set(body)}"
    assert {"kpis", "bullets"} <= set(body)
    assert body["bullets"] and all(isinstance(b, str) for b in body["bullets"])
    for kpi in body["kpis"]:
        assert set(kpi) <= {"label", "value", "delta", "dir"}
        assert isinstance(kpi["value"], str), "a KPI value is a display STRING"


# --------------------------------------------------------------------------- #
# 3. keyword_research: the pinned literals (Part 8 Phase 2A).
# --------------------------------------------------------------------------- #
# Belt-and-braces over the parametrized sweep: these are the exact values the
# dashboard renders, spelled out so a drift names itself in the failure output
# rather than only showing up as a tools.ts-vs-backend diff.
def test_keyword_research_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("keyword_research")
    assert ts.table_cols == ["Keyword", "Volume", "Difficulty", "Intent"]
    assert ts.kpi_labels == ["Saved keywords", "Clusters", "Avg. difficulty"]
    assert ts.primary_label == "Research keywords"
    assert ts.primary_icon == "search"
    assert ts.table_title == "Opportunity keywords"
    assert ts.table_icon == "search"


def test_keyword_research_service_constant_matches_tools_ts() -> None:
    # The adapter builds from this module constant; pin it to tools.ts directly so a
    # drift is caught even if the route is refactored away.
    from app.modules.keyword_research.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("keyword_research").table_cols == WORKSPACE_TABLE_COLS


# --------------------------------------------------------------------------- #
# 4. billing: the pinned literals (Part 8 Phase 2H).
# --------------------------------------------------------------------------- #
def test_billing_tools_ts_literals_are_pinned() -> None:
    ts = read_tool_extra("billing")
    assert ts.table_cols == ["Client", "Amount", "Due", "Status"]
    assert ts.kpi_labels == ["MRR", "Open invoices", "Past due"]
    assert ts.primary_label == "New invoice"
    assert ts.primary_icon == "payments"
    assert ts.table_title == "Invoices"
    assert ts.table_icon == "payments"


def test_billing_service_constant_matches_tools_ts() -> None:
    from app.modules.billing.service import WORKSPACE_TABLE_COLS

    assert read_tool_extra("billing").table_cols == WORKSPACE_TABLE_COLS


async def test_billing_mrr_tile_reads_the_subscription_table_not_the_ledger(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """The module's load-bearing scope rule, pinned at the workspace edge.

    The fake ledger bills 1490 + 690 = 2180; the fake subscription book carries an MRR
    of 28,400. The MRR tile must render the SUBSCRIPTION number - if the adapter ever
    starts summing invoices, this tile flips to "$2.2k" and this test names it.
    """
    adapter = next(a for a in _TOOL_ADAPTERS if a.tool_key == "billing")
    body = await _fetch_workspace(app, client, adapter)
    tiles = {k["label"]: k["value"] for k in body["kpis"]}
    assert tiles["MRR"] == "$28.4k"  # sum(clients.mrr), compact-formatted
    assert tiles["MRR"] != "$2.2k"  # ... and emphatically NOT sum(invoices)
    assert tiles["Open invoices"] == "3"  # these two DO come from the ledger
    assert tiles["Past due"] == "1"
