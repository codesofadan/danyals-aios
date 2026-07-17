"""The nine workspace builders - PURE row -> ``ToolExtra`` presentation mapping.

DB-free and network-free by construction: every builder takes rows/stats a router
already fetched from an EXISTING repo and maps them onto that tool's fixed
``lib/tools.ts`` columns + KPI tiles. No SQL, no business logic, no aggregate this
layer computes that a module already owns.

THE HONESTY RULE, and where it bites. ``tools.ts`` was written against DEMO data, so
a few of its tiles ask for numbers no shipped table stores. The rule is: emit the real
value, or an em dash - never a plausible-looking invention. Three tiles are dashes and
each says why at its builder:

* ``technical_audit`` "Open issues"  - the audits ledger tracks JOB state (status /
  score / artifacts); there is no issue ledger to count. The ``Issues`` COLUMN carries
  the crawl's real outcome instead (a failed crawl reads ``crit``).
* ``reporting`` "Scheduled"          - 0020 stores workbooks + push EVENTS; there is
  no report-schedule table, so nothing can be counted as scheduled.
* ``key_vault`` "Rotating soon"      - 0004/0041 store no rotation policy and no
  expiry, so "soon" has no definition. See ``build_key_vault_workspace``.

Every KPI DELTA in ``tools.ts`` is likewise dropped: a delta needs a stored baseline
("vs last period") and no module keeps one. A bare count is honest; a computed-looking
arrow would not be. The contract test pins labels/cols only, so dropping deltas is
inside the contract.

Each ``WORKSPACE_TABLE_COLS_<TOOL>`` constant is pinned BYTE-FOR-BYTE to its
``tools.ts`` block by ``tests/test_tool_workspace_contract.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from app.schemas.audits import AuditStatsResponse
from app.schemas.identity import to_team_role
from app.schemas.reports import REPORT_TYPES
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)

# Every workspace table is a PREVIEW: the tool's own module owns the full, paginated
# board. Eight rows is what the dashboard card shows (mirrors the sibling modules).
#
# PUBLIC because the router bounds its reads by the same number. The team_access route
# in particular fetches per-member metrics for exactly the members it will RENDER, so a
# router that previewed a different depth than the builder slices would silently show
# "0 tasks" for the members past the router's cut. One constant, no drift.
WORKSPACE_ROW_LIMIT = 8

# The honest stand-in for "there is no number here" (mirrors tools.ts, which already
# renders an em dash for an absent Words count).
_NONE = "—"

# The rolling window every "(30d)" tile in tools.ts asks for.
WINDOW_DAYS = 30


def _tone(value: str, tone: str) -> ToolCellObj:
    """A toned cell, narrowing the tone literal at the one place tones are built."""
    return ToolCellObj(v=value, tone=cast("Any", tone))


def _text(row: dict[str, Any], key: str) -> str:
    """A row's display string for ``key`` ('' when absent/NULL)."""
    return str(row.get(key) or "")


def _count(value: int) -> str:
    """A KPI count as a thousands-separated display string."""
    return f"{value:,}"


def _month(value: Any) -> str:
    """A timestamp's month name ("June") - the ``Period`` column's display form.

    Returns the em dash when the value is absent or unparseable, never a guessed
    month. psycopg hands back a ``datetime``; a string is tolerated for fakes/tests.
    """
    if isinstance(value, datetime):
        return value.strftime("%B")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%B")
        except ValueError:
            return _NONE
    return _NONE


def _month_year(value: Any) -> str:
    """A timestamp as "May 2026" (the ``Last rotated`` column's display form)."""
    if isinstance(value, datetime):
        return value.strftime("%b %Y")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%b %Y")
        except ValueError:
            return _NONE
    return _NONE


def _within_window(value: Any, *, days: int = WINDOW_DAYS) -> bool:
    """Whether a timestamp falls inside the trailing ``days`` window.

    Used only where the router already holds the rows (the tasks board); every other
    windowed tile is a repo-side aggregate. An unparseable/absent stamp is OUTSIDE the
    window - a row we cannot date must never be counted INTO a "(30d)" tile.
    """
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(value, datetime):
        return False
    stamped = value if value.tzinfo else value.replace(tzinfo=UTC)
    return (datetime.now(UTC) - stamped).days < days


# --------------------------------------------------------------------------- #
# 1. technical_audit - the audits job ledger (0008).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_TECHNICAL_AUDIT: list[str] = ["Site", "Client", "Score", "Issues"]
_TECHNICAL_AUDIT_TABLE = ("Recent crawls", "troubleshoot")
_TECHNICAL_AUDIT_PRIMARY = ToolPrimary(label="Run crawl", icon="fact_check")
_TECHNICAL_AUDIT_BULLETS = [
    "Run full technical crawls",
    "Review & mark issues fixed",
    "Track Core Web Vitals over time",
]

# An audit's run state -> (display, tone). This is what the ``Issues`` column carries:
# the ledger has no issue COUNT to show (see the module docstring), but it does know
# whether the crawl succeeded, and that is the state an operator acts on. A `done`
# crawl reads as an em dash - we have no issue count for it - and its Score column
# already carries the composite health.
_AUDIT_STATE: dict[str, tuple[str, str]] = {
    "done": (_NONE, "mut"),
    "failed": ("Failed", "crit"),
    "running": ("Running", "info"),
    "queued": ("Queued", "mut"),
}


def _audit_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Site, Client, Score, Issues]."""
    score = row.get("score")
    state, tone = _AUDIT_STATE.get(_text(row, "status"), (_NONE, "mut"))
    return [
        _text(row, "url"),
        _text(row, "client_name"),
        # A pending/failed crawl has no composite score; show a dash, not a zero.
        str(int(score)) if score is not None else _NONE,
        _tone(state, tone),
    ]


def build_technical_audit_workspace(
    audits: list[dict[str, Any]], stats: AuditStatsResponse
) -> ToolExtraResponse:
    """The technical-audit workspace off the audits ledger + its OWN computed stats.

    ``stats`` is ``compute_audit_stats`` (the exact function ``GET /audits/stats``
    uses), so the tile and the audits screen can never disagree.

    "Sites monitored" counts DISTINCT target urls in the ledger - the set of sites the
    crawler actually watches. "Open issues" is an em dash: nothing counts issues (see
    the module docstring). "Avg. health" is the mean composite over COMPLETED runs
    (0 means nothing has completed, which renders as a dash rather than a 0% health).
    """
    sites = len({_text(a, "url") for a in audits if _text(a, "url")})
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Sites monitored", value=_count(sites)),
            ToolKpi(label="Open issues", value=_NONE),
            ToolKpi(
                label="Avg. health",
                value=f"{stats.avg_score}%" if stats.avg_score > 0 else _NONE,
            ),
        ],
        table=ToolTable(
            title=_TECHNICAL_AUDIT_TABLE[0],
            icon=_TECHNICAL_AUDIT_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_TECHNICAL_AUDIT),
            rows=[_audit_row(a) for a in audits[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_TECHNICAL_AUDIT_PRIMARY,
        bullets=list(_TECHNICAL_AUDIT_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 2. backlink_manager - the backlinks ledger (0018).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_BACKLINK_MANAGER: list[str] = ["Domain", "Client", "DR", "Status"]
_BACKLINK_TABLE = ("Recent links", "hub")
_BACKLINK_PRIMARY = ToolPrimary(label="Run link sweep", icon="hub")
_BACKLINK_BULLETS = [
    "Monitor the backlink profile",
    "Flag lost or toxic links",
    "Track referring-domain growth",
]

# backlink_status -> (display, tone), matching the tools.ts demo semantics exactly:
# a won link is good, a lost one wants attention, a toxic one is a disavow candidate.
_BACKLINK_STATE: dict[str, tuple[str, str]] = {
    "new": ("New", "ok"),
    "lost": ("Lost", "warn"),
    "toxic": ("Toxic", "crit"),
}


def _backlink_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Domain, Client, DR, Status]."""
    state, tone = _BACKLINK_STATE.get(_text(row, "status"), (_NONE, "mut"))
    return [
        _text(row, "ref_domain"),
        _text(row, "client_name"),
        # `authority` IS the domain rating (0-100), stored per link.
        str(int(row.get("authority") or 0)),
        _tone(state, tone),
    ]


def build_backlink_manager_workspace(
    backlinks: list[dict[str, Any]],
    *,
    referring_domains: int,
    status_counts: dict[str, int],
    new_in_window: int,
) -> ToolExtraResponse:
    """The backlink workspace off the 0018 ledger's own aggregates.

    All three tiles are real: ``referring_domains`` is the repo's live profile size
    (distinct non-lost domains), ``new_in_window`` is its windowed discovery count, and
    Toxic reads the status breakdown. No delta - nothing stores last month's profile.
    """
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Referring domains", value=_count(referring_domains)),
            ToolKpi(label="New links (30d)", value=_count(new_in_window)),
            ToolKpi(label="Toxic flagged", value=_count(status_counts.get("toxic", 0))),
        ],
        table=ToolTable(
            title=_BACKLINK_TABLE[0],
            icon=_BACKLINK_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_BACKLINK_MANAGER),
            rows=[_backlink_row(b) for b in backlinks[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_BACKLINK_PRIMARY,
        bullets=list(_BACKLINK_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 3. content_pipeline - the content_jobs ledger (0017).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_CONTENT_PIPELINE: list[str] = ["Topic", "Client", "Stage", "Words"]
_CONTENT_TABLE = ("Content jobs", "article")
_CONTENT_PRIMARY = ToolPrimary(label="New content brief", icon="article")
_CONTENT_BULLETS = [
    "Create briefs & AI drafts",
    "Edit and refine copy",
    "Send drafts to the review gate",
]

# content_status -> (fallback display, tone). The TONE always comes from `status` (the
# enum is authoritative); the DISPLAY prefers the row's own free-text `stage` label,
# which is what the pipeline writes for the human ("Editing" is a real stage, not a
# status). The fallback here covers a row whose stage label is empty.
_CONTENT_STATE: dict[str, tuple[str, str]] = {
    "queued": ("Queued", "mut"),
    "drafting": ("Drafting", "info"),
    "needs_review": ("Review", "warn"),
    "publishing": ("Publishing", "info"),
    "done": ("Done", "ok"),
    "failed": ("Failed", "crit"),
    "rejected": ("Rejected", "mut"),
}

# The statuses a job passes THROUGH - i.e. still in the pipeline. done/failed/rejected
# are terminal and are deliberately absent.
_CONTENT_IN_FLIGHT = ("queued", "drafting", "needs_review", "publishing")


def _content_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Topic, Client, Stage, Words]."""
    label, tone = _CONTENT_STATE.get(_text(row, "status"), (_NONE, "mut"))
    words = int(row.get("words") or 0)
    return [
        _text(row, "topic"),
        _text(row, "client_name"),
        _tone(_text(row, "stage") or label, tone),
        # 0 words = not drafted yet. An em dash says that; "0" would read as an
        # empty article (tools.ts renders the dash for its Queued demo row too).
        _count(words) if words else _NONE,
    ]


def build_content_pipeline_workspace(
    jobs: list[dict[str, Any]], stats: dict[str, int]
) -> ToolExtraResponse:
    """The content workspace off ``ContentRepo.stats()`` (the module's own breakdown).

    All three tiles are real: "In pipeline" totals the NON-terminal statuses (a done or
    rejected job has left the pipeline), and the other two read one status each.
    """
    in_pipeline = sum(stats.get(s, 0) for s in _CONTENT_IN_FLIGHT)
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="In pipeline", value=_count(in_pipeline)),
            ToolKpi(label="Drafting", value=_count(stats.get("drafting", 0))),
            ToolKpi(label="Ready for review", value=_count(stats.get("needs_review", 0))),
        ],
        table=ToolTable(
            title=_CONTENT_TABLE[0],
            icon=_CONTENT_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_CONTENT_PIPELINE),
            rows=[_content_row(j) for j in jobs[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_CONTENT_PRIMARY,
        bullets=list(_CONTENT_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 4. publishing - content publish (0017) + Web 2.0 placements (0018/0028).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_PUBLISHING: list[str] = ["Title", "Client", "Target", "Status"]
_PUBLISHING_TABLE = ("Publish queue", "rocket_launch")
_PUBLISHING_PRIMARY = ToolPrimary(label="Publish", icon="rocket_launch")
_PUBLISHING_BULLETS = [
    "Push approved content live",
    "Publish to WordPress or export",
    "Schedule and track publishes",
]

# The publish queue spans TWO ledgers with two status enums that mean the same things.
# Both are mapped onto ONE display vocabulary here so a mixed queue reads consistently
# (content 'done' and web2 'published' are the same event: it is live).
_PUBLISH_STATE: dict[str, tuple[str, str]] = {
    "draft": ("Draft", "mut"),
    "queued": ("Draft", "mut"),
    "drafting": ("Draft", "mut"),
    "needs_review": ("Review", "warn"),
    "publishing": ("Scheduled", "info"),
    "done": ("Live", "ok"),
    "published": ("Live", "ok"),
    "failed": ("Failed", "crit"),
    "rejected": ("Rejected", "mut"),
}


def _publish_row(row: dict[str, Any], *, target_key: str) -> list[ToolCell]:
    """One row: [Title, Client, Target, Status].

    ``target_key`` is where THIS ledger keeps its destination: content jobs carry a
    ``target`` (WordPress / PDF-Markdown), Web 2.0 placements carry a ``platform``
    (Medium / Tumblr / ...). Both answer "where does this go", so one column serves.
    """
    label, tone = _PUBLISH_STATE.get(_text(row, "status"), (_NONE, "mut"))
    return [
        _text(row, "topic"),
        _text(row, "client_name"),
        _text(row, target_key) or _NONE,
        _tone(label, tone),
    ]


def _created_at_key(row: dict[str, Any]) -> str:
    """Sort key for the merged queue: the row's creation stamp as a sortable string.

    ISO-8601 sorts lexicographically, so this orders correctly whether psycopg handed
    back a ``datetime`` or a fake handed back a string. An undated row sorts LAST
    (empty string) rather than crashing the merge.
    """
    return str(row.get("created_at") or "")


def build_publishing_workspace(
    content_jobs: list[dict[str, Any]],
    web2: list[dict[str, Any]],
    *,
    content_stats: dict[str, int],
    web2_stats: dict[str, int],
) -> ToolExtraResponse:
    """The publish queue - BOTH publish surfaces in one board.

    The tool publishes two things and the tiles say so: a content job going live on
    WordPress and a Web 2.0 branded post going live on Medium are both a publish, so
    each tile sums the two ledgers' own aggregates rather than picking a favourite.
    The board merges both, newest first.
    """
    rows = sorted(
        [(_created_at_key(r), _publish_row(r, target_key="target")) for r in content_jobs]
        + [(_created_at_key(r), _publish_row(r, target_key="platform")) for r in web2],
        key=lambda pair: pair[0],
        reverse=True,
    )
    return ToolExtraResponse(
        kpis=[
            ToolKpi(
                label="Published (30d)",
                value=_count(content_stats.get("published", 0) + web2_stats.get("published", 0)),
            ),
            ToolKpi(
                label="Scheduled",
                value=_count(content_stats.get("scheduled", 0) + web2_stats.get("scheduled", 0)),
            ),
            ToolKpi(
                label="Failed",
                value=_count(content_stats.get("failed", 0) + web2_stats.get("failed", 0)),
            ),
        ],
        table=ToolTable(
            title=_PUBLISHING_TABLE[0],
            icon=_PUBLISHING_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_PUBLISHING),
            rows=[row for _key, row in rows[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_PUBLISHING_PRIMARY,
        bullets=list(_PUBLISHING_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 5. reporting - the workbooks + sync-event ledgers (0020).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_REPORTING: list[str] = ["Report", "Client", "Period", "Status"]
_REPORTING_TABLE = ("Recent reports", "summarize")
_REPORTING_PRIMARY = ToolPrimary(label="Build report", icon="summarize")
_REPORTING_BULLETS = [
    "Build & schedule client reports",
    "Sync scores to Google Sheets",
    "Send web + PDF reports",
]

# dataset -> its human title, reusing the module's OWN catalogue (GET /reports/types)
# so the workspace and the reports screen name a report identically.
_REPORT_TITLES: dict[str, str] = {t.key: t.title for t in REPORT_TYPES}


def _report_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Report, Client, Period, Status].

    A sync EVENT is a report that was pushed, so Status is always "Sent": the row only
    exists because the push happened (the log is append-only and failures are never
    appended). That is a fact about the row, not an assumption.
    """
    dataset = _text(row, "dataset")
    return [
        _REPORT_TITLES.get(dataset, dataset or _NONE),
        _text(row, "client_name"),
        _month(row.get("synced_at")),
        _tone("Sent", "ok"),
    ]


def build_reporting_workspace(
    events: list[dict[str, Any]], workbooks: list[dict[str, Any]], *, sent_in_window: int
) -> ToolExtraResponse:
    """The reporting workspace off the push log + the workbook ledger.

    "Scheduled" is an em dash: 0020 stores workbooks and the pushes that HAPPENED, and
    there is no report-schedule table anywhere - so there is no set of scheduled
    reports to count. "Sheets synced" counts workbooks currently in the ``synced``
    state (the master rollup is excluded upstream by ``list_workbooks``).
    """
    synced = sum(1 for w in workbooks if _text(w, "status") == "synced")
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Reports sent (30d)", value=_count(sent_in_window)),
            ToolKpi(label="Scheduled", value=_NONE),
            ToolKpi(label="Sheets synced", value=_count(synced)),
        ],
        table=ToolTable(
            title=_REPORTING_TABLE[0],
            icon=_REPORTING_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_REPORTING),
            rows=[_report_row(e) for e in events[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_REPORTING_PRIMARY,
        bullets=list(_REPORTING_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 6. task_board - the tasks ledger (0011).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_TASK_BOARD: list[str] = ["Task", "Client", "Assignee", "Status"]
_TASK_TABLE = ("Team tasks", "checklist")
_TASK_PRIMARY = ToolPrimary(label="New task", icon="add_task")
_TASK_BULLETS = [
    "Create, assign & track tasks",
    "Move work across the board",
    "See team throughput",
]

# task_status -> (display, tone), matching the tools.ts demo semantics: an unstarted
# task is neutral, work in flight is informational, a review is waiting on a human.
_TASK_STATE: dict[str, tuple[str, str]] = {
    "todo": ("To do", "mut"),
    "in_progress": ("In progress", "info"),
    "review": ("In review", "warn"),
    "done": ("Done", "ok"),
}


def _task_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Task, Client, Assignee, Status]."""
    label, tone = _TASK_STATE.get(_text(row, "status"), (_NONE, "mut"))
    return [
        _text(row, "title"),
        _text(row, "client_name"),
        # The joined roster name; an unassigned task says so rather than showing ''.
        _text(row, "assignee_name") or "Unassigned",
        _tone(label, tone),
    ]


def build_task_board_workspace(
    board: list[dict[str, Any]], all_tasks: list[dict[str, Any]]
) -> ToolExtraResponse:
    """The task board off the tasks ledger.

    ``board`` is the newest-first preview (assignee names joined); ``all_tasks`` is the
    ledger the tiles count over - the same "fetch rows, fold in Python" shape
    ``GET /audits/stats`` uses, so no new aggregate SQL is invented for three counts.

    "Done (30d)" windows on ``updated_at`` - the stamp of the move to done - and a task
    we cannot date is counted OUT, never in.
    """
    open_tasks = sum(1 for t in all_tasks if _text(t, "status") != "done")
    in_progress = sum(1 for t in all_tasks if _text(t, "status") == "in_progress")
    done_recent = sum(
        1
        for t in all_tasks
        if _text(t, "status") == "done" and _within_window(t.get("updated_at"))
    )
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Open tasks", value=_count(open_tasks)),
            ToolKpi(label="In progress", value=_count(in_progress)),
            ToolKpi(label="Done (30d)", value=_count(done_recent)),
        ],
        table=ToolTable(
            title=_TASK_TABLE[0],
            icon=_TASK_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_TASK_BOARD),
            rows=[_task_row(t) for t in board[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_TASK_PRIMARY,
        bullets=list(_TASK_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 7. client_setup - the clients + sites tables (0003).
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_CLIENT_SETUP: list[str] = ["Website", "Client", "CMS", "Status"]
_CLIENT_SETUP_TABLE = ("Websites", "add_business")
_CLIENT_SETUP_PRIMARY = ToolPrimary(label="Add website", icon="add_business")
_CLIENT_SETUP_BULLETS = [
    "Add & edit clients",
    "Register websites & CMS",
    "Set up tracking & integrations",
]

# sub_status -> (display, tone). A site row has no status of its own (0003 gives it a
# domain + a CMS and nothing else), so the Status column reports the CLIENT's real
# subscription state - the thing that actually decides whether the site is being
# worked on. Past-due is crit because delivery is at risk.
_CLIENT_STATE: dict[str, tuple[str, str]] = {
    "active": ("Active", "ok"),
    "trial": ("Trial", "info"),
    "past_due": ("Past due", "crit"),
    "paused": ("Paused", "mut"),
}

# cms_type is stored lowercase/free-text; these are the spellings the product uses.
# Anything else is title-cased rather than dropped - an unknown CMS is still a CMS.
_CMS_LABELS: dict[str, str] = {
    "wordpress": "WordPress",
    "webflow": "Webflow",
    "shopify": "Shopify",
    "wix": "Wix",
    "squarespace": "Squarespace",
    "custom": "Custom",
}


def _site_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Website, Client, CMS, Status]."""
    cms = _text(row, "cms_type")
    label, tone = _CLIENT_STATE.get(_text(row, "client_status"), (_NONE, "mut"))
    return [
        _text(row, "domain"),
        _text(row, "client_name"),
        _CMS_LABELS.get(cms.lower(), cms.title()) if cms else _NONE,
        _tone(label, tone),
    ]


def build_client_setup_workspace(
    sites: list[dict[str, Any]], clients: list[dict[str, Any]], site_counts: dict[str, int]
) -> ToolExtraResponse:
    """The client-setup workspace off the clients + sites tables.

    "Pending setup" counts clients with ZERO registered websites - the real, checkable
    meaning of "not set up yet" for a tool whose job is registering sites (rather than
    a guess off the subscription status, which says nothing about setup).
    """
    with_sites = {cid for cid, n in site_counts.items() if n > 0}
    pending = sum(1 for c in clients if str(c.get("id", "")) not in with_sites)
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Clients", value=_count(len(clients))),
            ToolKpi(label="Websites", value=_count(sum(site_counts.values()))),
            ToolKpi(label="Pending setup", value=_count(pending)),
        ],
        table=ToolTable(
            title=_CLIENT_SETUP_TABLE[0],
            icon=_CLIENT_SETUP_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_CLIENT_SETUP),
            rows=[_site_row(s) for s in sites[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_CLIENT_SETUP_PRIMARY,
        bullets=list(_CLIENT_SETUP_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 8. key_vault - the MASKED metadata list (0004/0041). THE SENSITIVE ONE.
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_KEY_VAULT: list[str] = ["Provider", "Scope", "Last rotated", "Status"]
_KEY_VAULT_TABLE = ("Keys & integrations", "key")
_KEY_VAULT_PRIMARY = ToolPrimary(label="Add key", icon="key")
_KEY_VAULT_BULLETS = [
    "Manage API keys & integrations",
    "Rotate credentials safely",
    "Super-Admin scoped access",
]

# The ONLY columns this builder is allowed to read off a vault row. `VaultRepo.list_keys`
# does `select *`, so the row dict handed in DOES contain `secret_sealed` - this
# allow-list is what guarantees the sealed bytes are never read, never formatted into a
# cell, and never reachable from the response. Nothing here decrypts: `reveal_secret` is
# the one decrypt path in the system and it is owner-only, in the vault router, and is
# not imported by this module.
_VAULT_DISPLAY_FIELDS = frozenset({"provider", "label", "created_at", "updated_at"})


def _vault_row(row: dict[str, Any]) -> list[ToolCell]:
    """One row: [Provider, Scope, Last rotated, Status] - masked metadata ONLY.

    Every value read here comes from ``_VAULT_DISPLAY_FIELDS``. Even the ``masked``
    preview is deliberately NOT rendered: no column asks for it, so the workspace
    shows strictly less than the vault list already does.

    "Last rotated" reads ``updated_at``, but only when it has actually moved past
    ``created_at``: the vault's only update path is ``rotate_key`` (which re-seals and
    re-stamps), so an untouched row still carrying its insert stamp has never been
    rotated and says "Never" rather than dressing its creation date up as a rotation.
    """
    created, updated = row.get("created_at"), row.get("updated_at")
    rotated = _month_year(updated) if updated and created and updated != created else "Never"
    return [
        _text(row, "provider"),
        # `label` is the key's human scope ("PageSpeed"). An unlabelled key shows a
        # dash rather than borrowing any other field to fill the cell.
        _text(row, "label") or _NONE,
        rotated,
        # A stored key is usable: there is no disabled/expiry column to contradict it.
        _tone("Active", "ok"),
    ]


def build_key_vault_workspace(keys: list[dict[str, Any]]) -> ToolExtraResponse:
    """The key-vault workspace off the MASKED metadata list - no secret, ever.

    "Rotating soon" is an em dash, and this is the honest answer rather than a missing
    feature: 0004/0041 store no rotation cadence, no expiry, and no policy, so "soon"
    has no definition to evaluate. Any number here would be invented - and inventing a
    rotation warning on a credentials screen is exactly the kind of fiction an operator
    would act on. "Integrations" counts DISTINCT providers (several keys can belong to
    one integration).
    """
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Keys stored", value=_count(len(keys))),
            ToolKpi(
                label="Integrations",
                value=_count(len({_text(k, "provider") for k in keys if _text(k, "provider")})),
            ),
            ToolKpi(label="Rotating soon", value=_NONE),
        ],
        table=ToolTable(
            title=_KEY_VAULT_TABLE[0],
            icon=_KEY_VAULT_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_KEY_VAULT),
            rows=[_vault_row(k) for k in keys[:WORKSPACE_ROW_LIMIT]],
        ),
        primary=_KEY_VAULT_PRIMARY,
        bullets=list(_KEY_VAULT_BULLETS),
    )


# --------------------------------------------------------------------------- #
# 9. team_access - the staff roster (0002) + the 7F-3 team metrics.
# --------------------------------------------------------------------------- #
WORKSPACE_TABLE_COLS_TEAM_ACCESS: list[str] = ["Member", "Role", "Status", "Tasks"]
_TEAM_TABLE = ("Members", "admin_panel_settings")
_TEAM_PRIMARY = ToolPrimary(label="Invite member", icon="group_add")
_TEAM_BULLETS = [
    "Manage members & roles",
    "Grant or revoke permissions",
    "Review the access audit trail",
]

# user_status -> (display, tone), matching the tools.ts demo semantics: an away member
# is a scheduling risk, an invited one has not accepted yet.
_MEMBER_STATE: dict[str, tuple[str, str]] = {
    "active": ("Active", "ok"),
    "away": ("Away", "warn"),
    "invited": ("Invited", "info"),
    "offline": ("Offline", "mut"),
}


def _member_row(row: dict[str, Any], active_tasks: int) -> list[ToolCell]:
    """One row: [Member, Role, Status, Tasks]."""
    label, tone = _MEMBER_STATE.get(_text(row, "status"), (_NONE, "mut"))
    return [
        _text(row, "name"),
        # The capitalized display role, via the roster's OWN mapper - so the workspace
        # and the Team screen spell a role identically.
        to_team_role(_text(row, "role") or "viewer"),
        _tone(label, tone),
        str(active_tasks),
    ]


def build_team_access_workspace(
    roster: list[dict[str, Any]], active_tasks: dict[str, int], *, role_count: int
) -> ToolExtraResponse:
    """The team-access workspace off the staff roster + the real task metrics.

    "Roles" is the size of the governance role set (``ROLE_ORDER``) - the roles that
    EXIST to be granted, which is what an access screen manages. It is deliberately not
    "roles currently in use": hiring nobody as an analyst does not delete the role.
    "Tasks" per member is the 7F-3 active-task metric, not a number computed here.
    """
    return ToolExtraResponse(
        kpis=[
            ToolKpi(label="Members", value=_count(len(roster))),
            ToolKpi(label="Roles", value=_count(role_count)),
            ToolKpi(
                label="Pending invites",
                value=_count(sum(1 for m in roster if _text(m, "status") == "invited")),
            ),
        ],
        table=ToolTable(
            title=_TEAM_TABLE[0],
            icon=_TEAM_TABLE[1],
            cols=list(WORKSPACE_TABLE_COLS_TEAM_ACCESS),
            rows=[
                _member_row(m, active_tasks.get(str(m.get("id", "")), 0))
                for m in roster[:WORKSPACE_ROW_LIMIT]
            ],
        ),
        primary=_TEAM_PRIMARY,
        bullets=list(_TEAM_BULLETS),
    )
