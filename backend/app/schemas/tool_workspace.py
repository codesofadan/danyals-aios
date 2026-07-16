"""Shared tool-workspace response models - the server-authoritative mirror of the
frontend ``lib/tools.ts`` ``ToolExtra`` shape.

Every Part-8 tool module exposes a ``GET /<tool>/workspace`` endpoint that returns
this shape, so the dashboard's per-tool workspace (``lib/tools.ts`` ``EXTRAS``) can
light up from live data instead of the demo constants. The frontend renders these
generically, so there is no contract-lock on the whole object (fields are dynamic);
what IS pinned is the per-tool ``table.cols`` + ``kpis[].label`` + ``primary`` -
enforced by ``tests/test_tool_workspace_contract.py`` (the tools' substitute for the
response-model contract lock), which parses ``tools.ts`` and asserts each module's
adapter emits BYTE-IDENTICAL columns.

Cells mirror ``lib/tools.ts`` ``Cell = string | { v: string; tone: CellTone }``:
a bare display string, OR a ``{v, tone}`` object when the cell carries a status
tone. The union is modelled directly so a builder can emit either form and the
serialised JSON matches the frontend one-for-one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Verbatim from lib/tools.ts CellTone.
ToolCellTone = Literal["ok", "info", "warn", "mut", "crit"]


class ToolCellObj(BaseModel):
    """A toned table cell (``lib/tools.ts`` ``{ v, tone }``)."""

    v: str
    tone: ToolCellTone


# A cell is a bare string OR a toned object (lib/tools.ts ``Cell``).
ToolCell = str | ToolCellObj


class ToolKpi(BaseModel):
    """One KPI tile (``lib/tools.ts`` ``ToolKpi``): a label + value, plus an optional
    delta + direction arrow. ``delta``/``dir`` are omitted for a plain count tile."""

    label: str
    value: str
    delta: str | None = None
    dir: Literal["up", "down"] | None = None


class ToolTable(BaseModel):
    """The workspace table (``lib/tools.ts`` ``ToolTable``): a titled, iconed grid
    whose ``cols`` are contract-pinned to ``tools.ts`` and whose ``rows`` are lists
    of cells (bare strings or toned objects)."""

    title: str
    icon: str
    cols: list[str]
    rows: list[list[ToolCell]]


class ToolPrimary(BaseModel):
    """The workspace's primary call-to-action button (``label`` + ``icon``)."""

    label: str
    icon: str


class ToolExtraResponse(BaseModel):
    """A tool workspace in the frontend ``ToolExtra`` shape: KPI tiles, an optional
    table, an optional primary action, and the bullet feature list."""

    kpis: list[ToolKpi]
    table: ToolTable | None = None
    primary: ToolPrimary | None = None
    bullets: list[str]
