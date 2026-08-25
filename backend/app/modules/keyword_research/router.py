"""Keyword-research module endpoints (Part 8 Phase 2A): the staff-only keyword BANK.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /keyword-research/workspace`` adapter emits the ``lib/tools.ts``
``keyword_research`` EXTRA shape (KPIs + the opportunity table + the CTA), with table
columns pinned to ``tests/test_tool_workspace_contract.py``.

Tables owned: ``keywords`` / ``keyword_clusters`` / ``keyword_lists`` /
``keyword_list_members`` (migration ``0035_keyword_research``). Cost-gate dial:
``keyword_research`` (the DataForSEO metrics spend; the research worker gates on it).

Access: every route requires the ``keyword_research`` FEATURE grant. Reads add
``view_reports``; the paid research + all mutations add the ``run_research`` MODULE
perm (held by the leads owner/admin/manager, and ONLY them) - which lines up with the
RLS insert/update policies (leads write) byte-for-byte. The internal
``client_id`` never leaks (``client`` is the snapshotted name); every mutation offloads
the blocking psycopg call with ``asyncio.to_thread`` and records an activity entry
(kind=client, entity=client) so the keyword work keeps each client's context fresh.
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Callable, Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.core.auth import CurrentUser, require_feature, require_module_perm, require_perm
from app.core.pagination import PageDep
from app.modules.keyword_research.repo import KeywordRepoDep
from app.modules.keyword_research.schemas import (
    CannibalizationConflict,
    ClusterResponse,
    KeywordCreate,
    KeywordResearchRequest,
    KeywordResponse,
    KeywordStats,
    KeywordUpdate,
    ResearchQueuedResponse,
    SearchIntent,
)
from app.modules.keyword_research.service import build_workspace, find_cannibalization
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

router = APIRouter(tags=["keyword-research"])

# Every tool route requires the fine-grained keyword_research feature grant (owner is
# all-on). Reads additionally require view_reports; paid research + mutations require
# the run_research MODULE perm - held by the leads (owner/admin/manager), mirroring the
# 0035 RLS insert/update policies exactly. ``run_research`` is a ModulePermKey, so it
# goes through require_module_perm; require_perm would deny every non-owner role.
Feature = Annotated[CurrentUser, Depends(require_feature("keyword_research"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
RunResearch = Annotated[CurrentUser, Depends(require_module_perm("run_research"))]

_KEYWORD_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found"
)
_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
_NOTHING_TO_UPDATE = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
)


def get_research_enqueuer() -> Callable[[str, str | None, str | None], None]:
    """Dependency: enqueue the keyword-research worker (overridable in tests).

    The Celery task is imported lazily so the API process never pulls in the task
    module just to import this router (mirrors ``get_web2_write_enqueuer``)."""

    def _enqueue(seed: str, geo: str | None, client_id: str | None) -> None:
        from app.modules.keyword_research.tasks import research_keywords

        research_keywords.delay(seed, geo, client_id)

    return _enqueue


ResearchEnqueuerDep = Annotated[
    Callable[[str, str | None, str | None], None], Depends(get_research_enqueuer)
]


def _client_entity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """The context entity a keyword mutation touches - the CLIENT the row belongs to,
    or unlinked (both ``None``) for an un-assigned bank keyword."""
    client_id = row.get("client_id")
    return ("client", str(client_id)) if client_id is not None else (None, None)


# --- reads --------------------------------------------------------------------


@router.get("/keyword-research/keywords", response_model=list[KeywordResponse])
async def list_keywords(
    repo: KeywordRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    cluster_id: Annotated[str | None, Query(alias="clusterId")] = None,
    intent: Annotated[SearchIntent | None, Query()] = None,
    winnable: Annotated[bool | None, Query()] = None,
    geo: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
) -> list[KeywordResponse]:
    """The keyword bank (best opportunities first). Filters narrow the board by client,
    cluster, intent, winnability, geo, or how the keyword entered the bank."""
    rows = await asyncio.to_thread(
        repo.list_keywords,
        client_id=client_id,
        cluster_id=cluster_id,
        intent=intent,
        winnable=winnable,
        geo=geo,
        source=source,
        limit=page.limit,
        offset=page.offset,
    )
    return [KeywordResponse.from_row(r) for r in rows]


# The CSV export contract: a STABLE, pinned header row (a spreadsheet formula or a
# re-import may key on it), a hard row cap, and ONLY clean columns - the internal
# client_id never appears (the same rule every JSON response follows).
_EXPORT_COLUMNS: tuple[str, ...] = (
    "keyword", "volume", "difficulty", "intent", "winnable", "cpc", "updated_at"
)
_EXPORT_ROW_CAP = 5000
_EXPORT_FILENAME = "keywords.csv"


def _export_cell(row: dict[str, Any], col: str) -> str:
    """One CSV cell: ``''`` for NULL (never the string ``None``), booleans as
    ``true``/``false``, the numeric metrics at 2dp (matching the JSON rounding),
    and timestamps in ISO-8601."""
    value = row.get(col)
    if value is None:
        return ""
    if col == "winnable":
        return "true" if value else "false"
    if col in ("difficulty", "cpc"):
        return f"{float(value):.2f}"
    if col == "updated_at" and hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


@router.get("/keyword-research/keywords/export.csv")
async def export_keywords_csv(
    repo: KeywordRepoDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> StreamingResponse:
    """The bank as a ``text/csv`` download - the missing OUT half of the CSV import.

    Guarded exactly like the module's other reads (feature + ``view_reports``) and
    client-scoped exactly like the list route (``clientId`` narrows; the repo read is
    RLS-scoped either way). Best opportunities first, capped at 5000 rows; streamed
    line-by-line with a Content-Disposition filename."""
    rows = await asyncio.to_thread(
        repo.list_keywords, client_id=client_id, limit=_EXPORT_ROW_CAP, offset=0
    )

    def _lines() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(_EXPORT_COLUMNS)
        yield buf.getvalue()
        for row in rows:
            buf.seek(0)
            buf.truncate()
            writer.writerow([_export_cell(row, col) for col in _EXPORT_COLUMNS])
            yield buf.getvalue()

    return StreamingResponse(
        _lines(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_EXPORT_FILENAME}"'},
    )


@router.get("/keyword-research/stats", response_model=KeywordStats)
async def keyword_stats(repo: KeywordRepoDep, _feat: Feature, _user: ViewReports) -> KeywordStats:
    """The bank summary tiles: saved keywords, distinct clusters, average difficulty."""
    row = await asyncio.to_thread(repo.keyword_stats)
    return KeywordStats.from_row(row)


@router.get("/keyword-research/workspace", response_model=ToolExtraResponse)
async def keyword_workspace(
    repo: KeywordRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``keyword_research`` shape): KPI tiles, the
    top-opportunity table (cols ``Keyword|Volume|Difficulty|Intent``), and the CTA."""
    stats_row = await asyncio.to_thread(repo.keyword_stats)
    top = await asyncio.to_thread(repo.list_keywords, limit=8, offset=0)
    return build_workspace(KeywordStats.from_row(stats_row), top)


@router.get("/keyword-research/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    repo: KeywordRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[ClusterResponse]:
    """The topical clusters (biggest by total volume first), optionally per client."""
    rows = await asyncio.to_thread(
        repo.list_clusters, client_id=client_id, limit=page.limit, offset=page.offset
    )
    return [ClusterResponse.from_row(r) for r in rows]


@router.get("/keyword-research/cannibalization", response_model=list[CannibalizationConflict])
async def cannibalization(
    repo: KeywordRepoDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[CannibalizationConflict]:
    """The cannibalization guard: landing URLs claimed by more than one intent (two
    pages competing for the same URL/intent), optionally scoped to one client."""
    rows = await asyncio.to_thread(repo.cannibalization_rows, client_id=client_id)
    return find_cannibalization(rows)


# --- mutations ----------------------------------------------------------------


@router.post(
    "/keyword-research/keywords",
    response_model=list[KeywordResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_keywords(
    body: KeywordCreate, repo: KeywordRepoDep, _feat: Feature, actor: RunResearch
) -> list[KeywordResponse]:
    """Bulk-add keywords to the bank (run_research). A client-scoped add snapshots the
    client name (404 if the client is unknown/invisible); a client-less add fills the
    bank. Duplicates (client, keyword, geo) are skipped. Records one activity entry."""
    client_name = ""
    if body.client_id is not None:
        resolved = await asyncio.to_thread(repo.client_name_for, body.client_id)
        if resolved is None:
            raise _CLIENT_NOT_FOUND
        client_name = resolved
    rows = await asyncio.to_thread(
        repo.add_keywords,
        client_id=body.client_id,
        client_name=client_name,
        geo=body.geo,
        keywords=body.keywords,
        created_by=actor.id,
    )
    ent_type, ent_id = ("client", body.client_id) if body.client_id is not None else (None, None)
    await record_activity(
        actor, kind="client", action=f"added {len(rows)} keywords",
        target=client_name, entity_type=ent_type, entity_id=ent_id,
    )
    return [KeywordResponse.from_row(r) for r in rows]


@router.post(
    "/keyword-research/research",
    response_model=ResearchQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_research(
    body: KeywordResearchRequest,
    repo: KeywordRepoDep,
    _feat: Feature,
    actor: RunResearch,
    enqueue: ResearchEnqueuerDep,
) -> ResearchQueuedResponse:
    """Kick off a cost-gated keyword research run for ``seed`` (run_research). Validates
    the optional client, enqueues the worker (fetch -> classify -> cluster -> upsert),
    and returns immediately. A client-scoped run snapshots the client name (404 if
    unknown). The paid provider pull is gated in the worker, not here."""
    client_name = ""
    if body.client_id is not None:
        resolved = await asyncio.to_thread(repo.client_name_for, body.client_id)
        if resolved is None:
            raise _CLIENT_NOT_FOUND
        client_name = resolved
    enqueue(body.seed, body.geo, body.client_id)
    ent_type, ent_id = ("client", body.client_id) if body.client_id is not None else (None, None)
    await record_activity(
        actor, kind="client", action=f"researched keywords for '{body.seed}'",
        target=client_name, entity_type=ent_type, entity_id=ent_id,
    )
    return ResearchQueuedResponse(seed=body.seed, queued=True)


@router.patch("/keyword-research/keywords/{code}", response_model=KeywordResponse)
async def update_keyword(
    code: str, body: KeywordUpdate, repo: KeywordRepoDep, _feat: Feature, actor: RunResearch
) -> KeywordResponse:
    """Assign / edit ONE keyword (run_research): reassign to a client, set the target
    URL, override the intent (source -> manual), or replace the tags. 404 if the code
    is unknown; 400 if nothing was provided."""
    existing = await asyncio.to_thread(repo.get_by_code, code)
    if existing is None:
        raise _KEYWORD_NOT_FOUND

    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise _NOTHING_TO_UPDATE

    changes: dict[str, Any] = {}
    if "client_id" in provided:
        if body.client_id is None:  # unassign -> return to the bank
            changes["client_id"] = None
            changes["client_name"] = ""
        else:
            resolved = await asyncio.to_thread(repo.client_name_for, body.client_id)
            if resolved is None:
                raise _CLIENT_NOT_FOUND
            changes["client_id"] = body.client_id
            changes["client_name"] = resolved
    if "target_url" in provided:
        changes["target_url"] = body.target_url or ""
    if "intent" in provided and body.intent is not None:
        changes["intent"] = body.intent
        changes["intent_source"] = "manual"
        changes["intent_confidence"] = 1.0
    if "tags" in provided:
        changes["tags"] = body.tags or []
    if not changes:
        raise _NOTHING_TO_UPDATE

    row = await asyncio.to_thread(repo.update_keyword, code, changes)
    if row is None:
        raise _KEYWORD_NOT_FOUND

    ent_type, ent_id = _client_entity(row)
    await record_activity(
        actor, kind="client", action="updated a keyword",
        target=row.get("client_name", "") or row.get("keyword", ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    return KeywordResponse.from_row(row)
