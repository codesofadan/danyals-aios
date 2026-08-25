"""The macro -> micro -> nano navigation contract.

One audit is readable at three altitudes, and each level links to the next:

    GET /audits/{id}/rollups                     MACRO  pillar + subpoint verdicts
    GET /audits/{id}/findings                    MICRO  one row per PROBLEM
    GET /audits/{id}/findings/{fid}/instances    NANO   every occurrence
    GET /audits/{id}/pages                       the page-side pivot
    GET /audits/{id}/workbook                    the whole thing as one download

Guarded exactly like the existing audit reads (``view_reports`` - all six staff
roles, no client). Reads go through the RLS seam; the altitude tables are
staff-select and nothing writes them through a user JWT.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.core.auth import CurrentUser, require_perm
from app.db.audit_findings_repo import AuditFindingsRepoDep
from app.db.audits_repo import AuditsRepoDep
from app.routers.audits import ArtifactStoreDep
from app.services.audit_report import REPORT_NAME
from app.services.audit_roadmap import (
    PHASE_BACKLOG,
    PHASE_LABEL,
    PHASE_MONTHS,
    effort_table,
)
from app.services.audit_workbook import BUNDLE_NAME, WORKBOOK_NAME

router = APIRouter(tags=["audits"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]

_AUDIT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "audit not found")
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "not found")

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: The downloadable pack. Restricted to an allow-list before any path is
#: resolved, exactly as the legacy sheet download does.
_DOWNLOADS: dict[str, tuple[str, str]] = {
    "report": (REPORT_NAME, "text/html; charset=utf-8"),
    "workbook": (WORKBOOK_NAME, _XLSX),
    "bundle": (BUNDLE_NAME, "application/zip"),
    "findings.csv": ("findings.csv", "text/csv"),
    "instances.csv": ("instances.csv", "text/csv"),
    "pages.csv": ("pages.csv", "text/csv"),
    "coverage.csv": ("coverage.csv", "text/csv"),
    "pillars.csv": ("pillars.csv", "text/csv"),
    "subpoints.csv": ("subpoints.csv", "text/csv"),
    "roadmap.csv": ("roadmap.csv", "text/csv"),
    # Per-pillar issue exports. Enumerated rather than pattern-matched: the
    # allow-list is the traversal guard, and a pattern is how a guard grows a hole.
    **{
        f"issues-{d}.csv": (f"issues-{d}.csv", "text/csv")
        for d in ("onpage", "technical", "offpage", "local", "geo", "strategy")
    },
}


async def _require_audit(repo: AuditsRepoDep, audit_id: str) -> dict[str, Any]:
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    return row


@router.get("/audits/{audit_id}/rollups")
async def audit_rollups(
    audit_id: str,
    repo: AuditsRepoDep,
    altitudes: AuditFindingsRepoDep,
    _user: ViewReports,
    level: Literal["site", "dimension", "pillar", "subpoint"] | None = None,
) -> list[dict[str, Any]]:
    """MACRO. Every row carries its coverage (`checks_ran` / `checks_applicable`)
    and a `score` that is **null when nothing ran** - never 0. A caller that
    renders `score or 0` will misreport an unmeasured dimension as a failing one."""
    await _require_audit(repo, audit_id)
    return await asyncio.to_thread(altitudes.rollups, audit_id, level=level)


@router.get("/audits/{audit_id}/findings")
async def audit_findings(
    audit_id: str,
    repo: AuditsRepoDep,
    altitudes: AuditFindingsRepoDep,
    _user: ViewReports,
    dimension: str | None = None,
    pillar: str | None = None,
    subcategory: str | None = None,
    severity: str | None = None,
    check_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """MICRO. One row per PROBLEM, not per occurrence: on a real 197-page audit
    this is 461 rows describing 8,077 occurrences. `instance_count` is the blast
    radius; the instances themselves hang off the next endpoint."""
    await _require_audit(repo, audit_id)
    rows = await asyncio.to_thread(
        altitudes.findings, audit_id, dimension=dimension, pillar=pillar,
        subcategory=subcategory, severity=severity, check_id=check_id,
        limit=limit, offset=offset,
    )
    # The SAME filters as the page. Counting every finding regardless of filter
    # made a severity-filtered request return 14 rows and a total of 461, so a
    # pager read "1 to 100 of 461" over a set of 14.
    total = await asyncio.to_thread(
        altitudes.finding_count, audit_id, dimension=dimension, pillar=pillar,
        subcategory=subcategory, severity=severity, check_id=check_id,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/audits/{audit_id}/findings/{finding_id}/instances")
async def audit_finding_instances(
    audit_id: str,
    finding_id: str,
    repo: AuditsRepoDep,
    altitudes: AuditFindingsRepoDep,
    _user: ViewReports,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """NANO. Every occurrence of one cause - the "and here are all 140 of them"
    view. Paginated because a single finding can hold thousands; the uncapped
    record is `instances.csv` in the download pack."""
    await _require_audit(repo, audit_id)
    rows = await asyncio.to_thread(
        altitudes.instances, audit_id, finding_id=finding_id, limit=limit, offset=offset,
    )
    total = await asyncio.to_thread(altitudes.instance_count, audit_id, finding_id=finding_id)
    if total == 0 and not rows:
        raise _NOT_FOUND
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/audits/{audit_id}/pages")
async def audit_pages(
    audit_id: str,
    repo: AuditsRepoDep,
    altitudes: AuditFindingsRepoDep,
    _user: ViewReports,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """The page pivot: every crawled URL with its own issue counts, worst first."""
    await _require_audit(repo, audit_id)
    return await asyncio.to_thread(altitudes.pages, audit_id, limit=limit, offset=offset)


@router.get("/audits/{audit_id}/roadmap")
async def audit_roadmap(
    audit_id: str,
    repo: AuditsRepoDep,
    altitudes: AuditFindingsRepoDep,
    _user: ViewReports,
) -> dict[str, Any]:
    """The active plan, grouped into its relative windows.

    `phase` is a WINDOW, never a date: `p1_90d` means "the second and third
    months of work". Calendar dates exist only if an operator sets `start_date`
    on the roadmap, and are arithmetic on that input.

    `capacity_points_per_month` is the single operator input every timeline
    number derives from - surfaced here so a caller can show the assumption
    rather than presenting the schedule as if it were measured.
    """
    await _require_audit(repo, audit_id)
    roadmap, items = await asyncio.to_thread(altitudes.roadmap, audit_id)
    if roadmap is None:
        raise _NOT_FOUND
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item["phase"], []).append(item)
    return {
        "roadmap": roadmap,
        "effort_model": effort_table(),
        "phases": [
            {"phase": phase, "label": PHASE_LABEL.get(phase, phase),
             "items": grouped.get(phase, [])}
            for phase in (*(p for p, _ in PHASE_MONTHS), PHASE_BACKLOG)
        ],
    }


@router.get("/audits/{audit_id}/download/{name}")
async def download_audit_pack(
    audit_id: str,
    name: str,
    repo: AuditsRepoDep,
    store: ArtifactStoreDep,
    _user: ViewReports,
) -> FileResponse:
    """Download the workbook, the zip pack, or one uncapped CSV.

    ``name`` is checked against an allow-list BEFORE any path is built, and the
    file is resolved by convention from the audit id rather than from a
    database-held path, so a stored value can never redirect the read.
    """
    entry = _DOWNLOADS.get(name)
    if entry is None or store is None:
        raise _NOT_FOUND
    await _require_audit(repo, audit_id)
    filename, media = entry
    path = store.sheets_dir(audit_id) / filename
    if not path.is_file():
        raise _NOT_FOUND
    return FileResponse(path, media_type=media, filename=f"audit-{audit_id}-{filename}")
