"""Off-page module endpoints (7B): backlink + citation MONITORING and the Web 2.0
property ledger.

Reads require any provisioned staff (``view_reports``, which a portal client does
NOT hold - so clients are 403'd out of this namespace, mirroring tasks/milestones).
Writes (the citation Submit/Update actions and the toxic-backlink flagger) require a
LEAD (owner/admin/manager) - the same set the RLS insert/update policies gate to; the
app-layer 403 here is clean UX on top of that DB boundary. The paid-tier gate for the
off-page deliverable lives at the service layer, not here.

Responses are the frontend ``Backlink`` / ``Citation`` / ``Web2Property`` shapes
(``lib/offpage.ts``); the internal ``client_id`` never leaks. Every mutation offloads
the blocking psycopg call with ``asyncio.to_thread`` and records an activity entry
(kind=content, entity=client) so the off-page work keeps each client's context fresh.
The Web 2.0 PUBLISH pipeline is a later chunk - only the read endpoints exist now.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.offpage_repo import OffpageRepoDep
from app.schemas.offpage import (
    BacklinkResponse,
    BacklinkStatus,
    CitationActionRequest,
    CitationBulkRequest,
    CitationResponse,
    FlagToxicRequest,
    NapStatus,
    OffpageKpisResponse,
    Web2PropertyResponse,
    action_for,
)
from app.services.activity import record_activity

router = APIRouter(tags=["offpage"])

# All six staff roles hold view_reports; a portal client does NOT (clients are
# confined out of the staff namespace, mirroring tasks.py / milestones.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Writes are lead-only (owner/admin/manager) - the RLS insert/update set. Owner
# auto-passes require_role.
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_CITATION_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found"
)


class FlagToxicResponse(BaseModel):
    """The outcome of a disavow-review flag pass: how many backlinks were moved into
    ``toxic``."""

    flagged: int


def _client_entity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """The context entity an off-page mutation touches - always the CLIENT the row
    belongs to (its world is what changed). A client-less row (should not happen for
    a live row) links nothing so the event is still recorded, just unlinked."""
    client_id = row.get("client_id")
    return ("client", str(client_id)) if client_id is not None else (None, None)


async def _record_per_client(
    actor: CurrentUser, rows: list[dict[str, Any]], *, action: str
) -> None:
    """Record ONE activity per distinct client touched by a batch mutation, so every
    affected client's context is refreshed (and the feed is not spammed per-row)."""
    seen: set[str] = set()
    for row in rows:
        client_id = row.get("client_id")
        if client_id is None:
            continue
        key = str(client_id)
        if key in seen:
            continue
        seen.add(key)
        await record_activity(
            actor, kind="content", action=action, target=row.get("client_name", ""),
            entity_type="client", entity_id=key,
        )


# --- backlinks ----------------------------------------------------------------


@router.get("/offpage/backlinks", response_model=list[BacklinkResponse])
async def list_backlinks(
    repo: OffpageRepoDep,
    page: PageDep,
    _user: ViewReports,
    status_filter: Annotated[BacklinkStatus | None, Query(alias="status")] = None,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[BacklinkResponse]:
    """The referring-domain profile (freshest first). ``status=toxic`` returns the
    disavow-review queue; ``status``/``clientId`` narrow the board."""
    rows = await asyncio.to_thread(
        repo.list_backlinks,
        status=status_filter,
        client_id=client_id,
        limit=page.limit,
        offset=page.offset,
    )
    return [BacklinkResponse.from_row(r) for r in rows]


@router.post("/offpage/backlinks/flag-toxic", response_model=FlagToxicResponse)
async def flag_toxic_backlinks(
    body: FlagToxicRequest, repo: OffpageRepoDep, actor: Lead
) -> FlagToxicResponse:
    """Flag every backlink at/above ``spamThreshold`` spam as ``toxic`` (queue them
    for a disavow review). Lead-only. Idempotent; returns how many were moved."""
    rows = await asyncio.to_thread(
        repo.flag_toxic_backlinks, spam_threshold=body.spam_threshold
    )
    await _record_per_client(actor, rows, action="flagged toxic backlinks for disavow")
    return FlagToxicResponse(flagged=len(rows))


# --- citations ----------------------------------------------------------------


@router.get("/offpage/citations", response_model=list[CitationResponse])
async def list_citations(
    repo: OffpageRepoDep,
    page: PageDep,
    _user: ViewReports,
    nap: Annotated[NapStatus | None, Query()] = None,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[CitationResponse]:
    """The local directory / NAP listings. ``nap``/``clientId`` narrow the board."""
    rows = await asyncio.to_thread(
        repo.list_citations,
        nap_status=nap,
        client_id=client_id,
        limit=page.limit,
        offset=page.offset,
    )
    return [CitationResponse.from_row(r) for r in rows]


@router.post("/offpage/citations/{citation_id}/action", response_model=CitationResponse)
async def act_on_citation(
    citation_id: str,
    body: CitationActionRequest,
    repo: OffpageRepoDep,
    actor: Lead,
) -> CitationResponse:
    """Mark ONE listing handled: a Submit (created a missing listing) or an Update
    (fixed drift) both resolve the NAP to ``consistent``. Lead-only; 404 if unknown."""
    row = await asyncio.to_thread(repo.get_citation, citation_id)
    if row is None:
        raise _CITATION_NOT_FOUND

    changes: dict[str, Any] = {"nap_status": "consistent", "action": action_for("consistent")}
    if body.note is not None:
        changes["note"] = body.note
    updated = await asyncio.to_thread(repo.update_citation, citation_id, changes)
    if updated is None:
        raise _CITATION_NOT_FOUND

    ent_type, ent_id = _client_entity(row)
    verb = "submitted a citation" if body.action == "Submit" else "updated a citation"
    await record_activity(
        actor, kind="content", action=verb, target=row.get("client_name", ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    return CitationResponse.from_row(updated)


@router.post("/offpage/citations/bulk", response_model=list[CitationResponse])
async def bulk_update_citations(
    body: CitationBulkRequest, repo: OffpageRepoDep, actor: Lead
) -> list[CitationResponse]:
    """Mark many listings ``consistent`` in one shot (a batch Submit/Update). Only
    the rows RLS lets the caller see are affected. Lead-only. Records one activity per
    distinct client touched."""
    changes: dict[str, Any] = {"nap_status": "consistent", "action": action_for("consistent")}
    rows = await asyncio.to_thread(repo.bulk_update_citations, body.ids, changes)
    await _record_per_client(actor, rows, action="reconciled citations")
    return [CitationResponse.from_row(r) for r in rows]


# --- web 2.0 ------------------------------------------------------------------


@router.get("/offpage/web2", response_model=list[Web2PropertyResponse])
async def list_web2(
    repo: OffpageRepoDep,
    page: PageDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Web2PropertyResponse]:
    """The Web 2.0 property ledger (newest-published first). The PUBLISH pipeline
    lands in a later chunk; this endpoint reads the existing placements."""
    rows = await asyncio.to_thread(
        repo.list_web2, client_id=client_id, limit=page.limit, offset=page.offset
    )
    return [Web2PropertyResponse.from_row(r) for r in rows]


# --- KPIs ---------------------------------------------------------------------


@router.get("/offpage/kpis", response_model=OffpageKpisResponse)
async def offpage_kpis(repo: OffpageRepoDep, _user: ViewReports) -> OffpageKpisResponse:
    """The off-page summary tiles: live profile size (distinct referring domains) plus
    the new/lost 30-day monitoring deltas and the toxic disavow-review queue size."""
    counts = await asyncio.to_thread(repo.backlink_status_counts)
    referring = await asyncio.to_thread(repo.referring_domain_count)
    return OffpageKpisResponse(
        referring_domains=referring,
        new_links_30d=counts.get("new", 0),
        lost_links_30d=counts.get("lost", 0),
        toxic_flagged=counts.get("toxic", 0),
    )
