"""Tool-workspace adapters (Part 8 Phase 2.5): the READ-ONLY ``GET /<tool>/workspace``
surface for the NINE tools whose modules already shipped in Parts 1-9.

WHY THIS MODULE EXISTS. ``frontend/lib/tools.ts`` catalogues 17 tools, and every one of
them renders through a single dynamic route (``/portal/tools/[slug]``) that feeds a
``ToolExtra`` to one ``<ToolWorkspace>``. Part 8 gave 8 of those tools a new module,
each shipping its own ``/workspace``. The other nine already HAD their modules -
audits, off-page, content, reports, tasks, clients, vault, team - and only lacked the
adapter, so their pages would have rendered ``tools.ts``'s demo constants forever. This
module is that adapter layer and nothing more.

Tables owned: NONE. Migrations: NONE. Cost-gate dials: NONE. Every route is a pure
read that reuses an EXISTING repo dependency (``AuditsRepoDep``, ``OffpageRepoDep``,
``ContentRepoDep``, ``ReportsRepoDep``, ``TasksRepoDep``, ``ClientsRepoDep``,
``VaultRepoDep``) plus the roster reader + ``TeamMetricsDep``. There are no mutations,
so - unlike every other module - there is deliberately NO ``record_activity`` call
anywhere here: activity feeds the 6B context memory with things that HAPPENED, and
opening a dashboard card is not one of them.

Contract: each route returns the shared ``ToolExtraResponse`` (``app/schemas/
tool_workspace.py``), server-authoritative, with its table columns + KPI labels + CTA
pinned BYTE-FOR-BYTE to that tool's ``lib/tools.ts`` ``EXTRAS`` block by
``tests/test_tool_workspace_contract.py``.

Access: every route carries the tool's OWN feature grant (the keys already exist in
``app/rbac/matrix.py``) + ``view_reports`` for the read. ``key_vault`` additionally
carries ``manage_vault``: the 0004 RLS select policy is owner/admin only, so a caller
holding the feature grant but not the permission would otherwise get a silently EMPTY
table instead of a clean 403 - and on a credentials screen an empty list that means
"forbidden" is a lie worth avoiding. It is the same permission the vault router itself
requires, so the app gate and the DB boundary agree.

The internal ``client_id`` NEVER appears in a response: every builder reads the
``client_name`` snapshot the repos already expose (and ``list_all_sites`` joins the
name live, selecting no id at all). Every blocking psycopg call is offloaded with
``asyncio.to_thread``. Empty data renders an empty-but-valid table, never a 500.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_feature, require_perm
from app.db.audits_repo import AuditsRepoDep
from app.db.clients_repo import ClientsRepoDep
from app.db.content_repo import ContentRepoDep
from app.db.offpage_repo import OffpageRepoDep
from app.db.reports_repo import ReportsRepoDep
from app.db.tasks_repo import TasksRepoDep
from app.db.vault_repo import VaultRepoDep
from app.modules.tool_workspaces.service import (
    # The rolling window every "(30d)" tile asks for, and the preview depth the service
    # slices its tables with - imported (not re-declared) so a read here can never fetch
    # a different depth or window than the builder renders.
    WINDOW_DAYS,
    WORKSPACE_ROW_LIMIT,
    build_backlink_manager_workspace,
    build_client_setup_workspace,
    build_content_pipeline_workspace,
    build_key_vault_workspace,
    build_publishing_workspace,
    build_reporting_workspace,
    build_task_board_workspace,
    build_team_access_workspace,
    build_technical_audit_workspace,
)
from app.rbac import ROLE_ORDER
from app.schemas.audits import compute_audit_stats
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.team_metrics import TeamMetricsDep

router = APIRouter(tags=["tool-workspaces"])

# Every workspace is a READ: the caller needs the tool's feature grant (owner is
# all-on) AND view_reports. Each tool's grant is its own dependency so a route can
# never accidentally be gated on a sibling tool's key.
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
ManageVault = Annotated[CurrentUser, Depends(require_perm("manage_vault"))]

TechnicalAuditFeature = Annotated[CurrentUser, Depends(require_feature("technical_audit"))]
BacklinkFeature = Annotated[CurrentUser, Depends(require_feature("backlink_manager"))]
ContentFeature = Annotated[CurrentUser, Depends(require_feature("content_pipeline"))]
PublishingFeature = Annotated[CurrentUser, Depends(require_feature("publishing"))]
ReportingFeature = Annotated[CurrentUser, Depends(require_feature("reporting"))]
TaskBoardFeature = Annotated[CurrentUser, Depends(require_feature("task_board"))]
ClientSetupFeature = Annotated[CurrentUser, Depends(require_feature("client_setup"))]
KeyVaultFeature = Annotated[CurrentUser, Depends(require_feature("key_vault"))]
TeamAccessFeature = Annotated[CurrentUser, Depends(require_feature("team_access"))]

def get_roster_reader() -> Callable[..., list[dict[str, Any]]]:
    """Dependency: the STAFF roster reader (overridable in tests).

    Reuses ``admin_users._fetch_all_users`` - the one roster read in the app - rather
    than adding a second copy of its ``role <> 'client'`` exclusion, which is the whole
    reason portal clients never appear on a Team screen. Imported lazily so this router
    does not drag the admin module in at import time (mirrors ``local_seo``'s enqueuer
    dependencies), and exposed as a dependency so a test can inject a fake without
    monkeypatching a module attribute.
    """
    from app.routers.admin_users import _fetch_all_users

    return _fetch_all_users


RosterReaderDep = Annotated[Callable[..., list[dict[str, Any]]], Depends(get_roster_reader)]


@router.get("/technical-audit/workspace", response_model=ToolExtraResponse)
async def technical_audit_workspace(
    repo: AuditsRepoDep, _feat: TechnicalAuditFeature, _user: ViewReports
) -> ToolExtraResponse:
    """The technical-audit workspace (``lib/tools.ts`` ``technical_audit``): KPI tiles +
    the recent-crawls table (cols ``Site|Client|Score|Issues``) + the CTA.

    Reads the ledger once and folds it two ways - the tiles via ``compute_audit_stats``
    (the same function ``GET /audits/stats`` uses, so the two surfaces cannot disagree)
    and the table off the newest rows.
    """
    rows = await asyncio.to_thread(repo.list_audits)
    return build_technical_audit_workspace(rows, compute_audit_stats(rows))


@router.get("/backlink-manager/workspace", response_model=ToolExtraResponse)
async def backlink_manager_workspace(
    repo: OffpageRepoDep, _feat: BacklinkFeature, _user: ViewReports
) -> ToolExtraResponse:
    """The backlink workspace (``lib/tools.ts`` ``backlink_manager``): KPI tiles + the
    recent-links table (cols ``Domain|Client|DR|Status``) + the CTA."""
    domains = await asyncio.to_thread(repo.referring_domain_count)
    counts = await asyncio.to_thread(repo.backlink_status_counts)
    new_links = await asyncio.to_thread(repo.new_backlink_count, days=WINDOW_DAYS)
    rows = await asyncio.to_thread(repo.list_backlinks, limit=WORKSPACE_ROW_LIMIT, offset=0)
    return build_backlink_manager_workspace(
        rows, referring_domains=domains, status_counts=counts, new_in_window=new_links
    )


@router.get("/content-pipeline/workspace", response_model=ToolExtraResponse)
async def content_pipeline_workspace(
    repo: ContentRepoDep, _feat: ContentFeature, _user: ViewReports
) -> ToolExtraResponse:
    """The content workspace (``lib/tools.ts`` ``content_pipeline``): KPI tiles + the
    content-jobs table (cols ``Topic|Client|Stage|Words``) + the CTA."""
    stats = await asyncio.to_thread(repo.stats)
    rows = await asyncio.to_thread(repo.list_jobs, limit=WORKSPACE_ROW_LIMIT, offset=0)
    return build_content_pipeline_workspace(rows, stats)


@router.get("/publishing/workspace", response_model=ToolExtraResponse)
async def publishing_workspace(
    content: ContentRepoDep,
    offpage: OffpageRepoDep,
    _feat: PublishingFeature,
    _user: ViewReports,
) -> ToolExtraResponse:
    """The publishing workspace (``lib/tools.ts`` ``publishing``): KPI tiles + the
    merged publish queue (cols ``Title|Client|Target|Status``) + the CTA.

    The tool publishes to TWO surfaces - a client's own site (content jobs) and the
    branded Web 2.0 properties - so it reads both ledgers and merges them newest-first.
    """
    content_stats = await asyncio.to_thread(content.publish_stats, days=WINDOW_DAYS)
    web2_stats = await asyncio.to_thread(offpage.web2_publish_stats, days=WINDOW_DAYS)
    jobs = await asyncio.to_thread(content.list_jobs, limit=WORKSPACE_ROW_LIMIT, offset=0)
    web2 = await asyncio.to_thread(offpage.list_web2, limit=WORKSPACE_ROW_LIMIT, offset=0)
    return build_publishing_workspace(
        jobs, web2, content_stats=content_stats, web2_stats=web2_stats
    )


@router.get("/reporting/workspace", response_model=ToolExtraResponse)
async def reporting_workspace(
    repo: ReportsRepoDep, _feat: ReportingFeature, _user: ViewReports
) -> ToolExtraResponse:
    """The reporting workspace (``lib/tools.ts`` ``reporting``): KPI tiles + the
    recent-reports table (cols ``Report|Client|Period|Status``) + the CTA."""
    sent = await asyncio.to_thread(repo.sync_event_count, days=WINDOW_DAYS)
    events = await asyncio.to_thread(repo.list_sync_events, limit=WORKSPACE_ROW_LIMIT, offset=0)
    # One workbook per client (the master rollup is excluded by list_workbooks), so the
    # Sheets-synced tile folds the list rather than asking for another aggregate.
    workbooks = await asyncio.to_thread(repo.list_workbooks)
    return build_reporting_workspace(events, workbooks, sent_in_window=sent)


@router.get("/task-board/workspace", response_model=ToolExtraResponse)
async def task_board_workspace(
    repo: TasksRepoDep, _feat: TaskBoardFeature, _user: ViewReports
) -> ToolExtraResponse:
    """The task-board workspace (``lib/tools.ts`` ``task_board``): KPI tiles + the
    team-tasks table (cols ``Task|Client|Assignee|Status``) + the CTA."""
    board = await asyncio.to_thread(repo.list_board_tasks, limit=WORKSPACE_ROW_LIMIT, offset=0)
    all_tasks = await asyncio.to_thread(repo.list_tasks)
    return build_task_board_workspace(board, all_tasks)


@router.get("/client-setup/workspace", response_model=ToolExtraResponse)
async def client_setup_workspace(
    repo: ClientsRepoDep, _feat: ClientSetupFeature, _user: ViewReports
) -> ToolExtraResponse:
    """The client-setup workspace (``lib/tools.ts`` ``client_setup``): KPI tiles + the
    websites table (cols ``Website|Client|CMS|Status``) + the CTA."""
    sites = await asyncio.to_thread(repo.list_all_sites, limit=WORKSPACE_ROW_LIMIT, offset=0)
    clients = await asyncio.to_thread(repo.list_clients)
    counts = await asyncio.to_thread(repo.site_counts)
    return build_client_setup_workspace(sites, clients, counts)


@router.get("/key-vault/workspace", response_model=ToolExtraResponse)
async def key_vault_workspace(
    repo: VaultRepoDep, _feat: KeyVaultFeature, _user: ViewReports, _vault: ManageVault
) -> ToolExtraResponse:
    """The key-vault workspace (``lib/tools.ts`` ``key_vault``): KPI tiles + the masked
    keys table (cols ``Provider|Scope|Last rotated|Status``) + the CTA.

    THE MASKED LIST ONLY. ``VaultRepo.list_keys`` is the same read the vault router's
    masked list uses; no reveal path is imported or reachable from here, and the
    builder reads a fixed allow-list of metadata columns, so the sealed bytes are never
    formatted, returned, or logged.
    """
    rows = await asyncio.to_thread(repo.list_keys)
    return build_key_vault_workspace(rows)


@router.get("/team-access/workspace", response_model=ToolExtraResponse)
async def team_access_workspace(
    metrics: TeamMetricsDep,
    roster_reader: RosterReaderDep,
    caller: TeamAccessFeature,
    _user: ViewReports,
) -> ToolExtraResponse:
    """The team-access workspace (``lib/tools.ts`` ``team_access``): KPI tiles + the
    members table (cols ``Member|Role|Status|Tasks``) + the CTA.

    The Tasks column is the REAL 7F-3 active-task metric, aggregated for the previewed
    members only (the same narrow ``member_metrics(ids)`` call the roster endpoint
    makes) - not a number this module counts for itself.
    """
    roster = await asyncio.to_thread(roster_reader, caller.id)
    shown = roster[:WORKSPACE_ROW_LIMIT]
    scored = (
        await asyncio.to_thread(metrics.member_metrics, [str(m["id"]) for m in shown])
        if shown
        else {}
    )
    return build_team_access_workspace(
        roster,
        {mid: m.active_tasks for mid, m in scored.items()},
        role_count=len(ROLE_ORDER),
    )
