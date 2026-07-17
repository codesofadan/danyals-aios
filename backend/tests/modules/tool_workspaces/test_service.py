"""The nine workspace builders: rows -> the right cells, tones, and honest values.

Pure unit tests - the builders are DB-free and network-free, so every case here is a
plain function call. The router-level wiring is pinned in ``test_router.py``; the
byte-for-byte ``tools.ts`` column lock lives in ``tests/test_tool_workspace_contract.py``.

What these tests are FOR: the contract test pins labels + columns, and the router test
pins the gates. Neither can see INSIDE a cell - so the tone semantics, the honest
em dashes, and the "never invent a number" rules are pinned here, at the one layer that
decides them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.tool_workspaces.service import (
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
from app.schemas.audits import AuditStatsResponse, compute_audit_stats

pytestmark = pytest.mark.unit

_NONE = "—"


def _tiles(resp: Any) -> dict[str, str]:
    return {k.label: k.value for k in resp.kpis}


def _cell(resp: Any, row: int, col: int) -> Any:
    """One table cell, as the wire sees it (a bare str, or a {v,tone} dict)."""
    value = resp.table.rows[row][col]
    return value if isinstance(value, str) else value.model_dump()


# --------------------------------------------------------------------------- #
# Every builder: an EMPTY ledger renders an empty-but-valid table, never a crash.
# --------------------------------------------------------------------------- #
_EMPTY_BUILDS: list[tuple[str, Any]] = [
    ("technical_audit", lambda: build_technical_audit_workspace([], compute_audit_stats([]))),
    ("backlink_manager", lambda: build_backlink_manager_workspace(
        [], referring_domains=0, status_counts={}, new_in_window=0)),
    ("content_pipeline", lambda: build_content_pipeline_workspace([], {})),
    ("publishing", lambda: build_publishing_workspace(
        [], [], content_stats={}, web2_stats={})),
    ("reporting", lambda: build_reporting_workspace([], [], sent_in_window=0)),
    ("task_board", lambda: build_task_board_workspace([], [])),
    ("client_setup", lambda: build_client_setup_workspace([], [], {})),
    ("key_vault", lambda: build_key_vault_workspace([])),
    ("team_access", lambda: build_team_access_workspace([], {}, role_count=6)),
]


@pytest.mark.parametrize(("name", "build"), _EMPTY_BUILDS, ids=[n for n, _b in _EMPTY_BUILDS])
def test_empty_data_builds_an_empty_but_valid_workspace(name: str, build: Any) -> None:
    """A fresh deploy has empty ledgers; every card must still render."""
    resp = build()
    assert resp.table is not None
    assert resp.table.rows == []
    assert resp.table.cols, f"{name}: cols must survive an empty ledger"
    assert len(resp.kpis) == 3
    assert resp.bullets and resp.primary is not None


@pytest.mark.parametrize(("name", "build"), _EMPTY_BUILDS, ids=[n for n, _b in _EMPTY_BUILDS])
def test_every_kpi_value_is_a_display_string(name: str, build: Any) -> None:
    """``ToolKpi.value`` is a rendered STRING - a builder must never leak an int."""
    for kpi in build().kpis:
        assert isinstance(kpi.value, str), f"{name}/{kpi.label} is not a string"


@pytest.mark.parametrize(("name", "build"), _EMPTY_BUILDS, ids=[n for n, _b in _EMPTY_BUILDS])
def test_no_builder_invents_a_delta(name: str, build: Any) -> None:
    """``tools.ts`` shows deltas on its demo tiles, but nothing stores a baseline to
    compare against - so every delta is dropped rather than fabricated."""
    for kpi in build().kpis:
        assert kpi.delta is None, f"{name}/{kpi.label} grew a delta with no baseline"
        assert kpi.dir is None


# --------------------------------------------------------------------------- #
# 1. technical_audit
# --------------------------------------------------------------------------- #
def _audit(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "a1", "client_id": "cl-SECRET", "client_name": "NorthPeak Dental",
        "url": "northpeakdental.com", "status": "done", "score": 88,
        "runtime_seconds": 372, "created_at": "2026-07-16T09:14:00+00:00",
    }
    row.update(over)
    return row


def test_technical_audit_maps_a_crawl_row() -> None:
    resp = build_technical_audit_workspace([_audit()], AuditStatsResponse(
        this_month=1, avg_score=88, running_now=0, turnaround_min=6))
    assert _cell(resp, 0, 0) == "northpeakdental.com"
    assert _cell(resp, 0, 1) == "NorthPeak Dental"
    assert _cell(resp, 0, 2) == "88"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("failed", {"v": "Failed", "tone": "crit"}),
        ("running", {"v": "Running", "tone": "info"}),
        ("queued", {"v": "Queued", "tone": "mut"}),
        ("done", {"v": _NONE, "tone": "mut"}),
        ("nonsense", {"v": _NONE, "tone": "mut"}),  # an unknown state degrades, never KeyErrors
    ],
)
def test_technical_audit_issues_cell_reports_the_real_run_state(
    status: str, expected: dict[str, str]
) -> None:
    """No issue ledger exists, so the Issues column carries the crawl's OUTCOME - which
    is real, and is what an operator acts on. A failed crawl reads crit."""
    resp = build_technical_audit_workspace(
        [_audit(status=status, score=None)], compute_audit_stats([]))
    assert _cell(resp, 0, 3) == expected


def test_technical_audit_pending_score_is_a_dash_not_a_zero() -> None:
    resp = build_technical_audit_workspace(
        [_audit(status="queued", score=None)], compute_audit_stats([]))
    assert _cell(resp, 0, 2) == _NONE


def test_technical_audit_open_issues_is_always_an_honest_dash() -> None:
    """Pinned deliberately: nothing anywhere counts audit issues, so this tile can only
    become a number by someone inventing one."""
    resp = build_technical_audit_workspace([_audit(), _audit(id="a2")], compute_audit_stats([]))
    assert _tiles(resp)["Open issues"] == _NONE


def test_technical_audit_sites_tile_counts_distinct_urls_not_rows() -> None:
    """Five crawls of two sites is two sites monitored."""
    rows = [_audit(id=f"a{i}") for i in range(4)] + [_audit(id="a5", url="atlaslegal.com")]
    resp = build_technical_audit_workspace(rows, compute_audit_stats(rows))
    assert _tiles(resp)["Sites monitored"] == "2"


def test_technical_audit_health_tile_dashes_when_nothing_has_completed() -> None:
    """avg_score 0 means "no completed run", not "0% healthy"."""
    rows = [_audit(status="queued", score=None)]
    resp = build_technical_audit_workspace(rows, compute_audit_stats(rows))
    assert _tiles(resp)["Avg. health"] == _NONE


# --------------------------------------------------------------------------- #
# 2. backlink_manager
# --------------------------------------------------------------------------- #
def _backlink(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "client_id": "cl-SECRET", "client_name": "NorthPeak Dental",
        "ref_domain": "healthline.com", "authority": 91, "status": "new",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("new", {"v": "New", "tone": "ok"}),
        ("lost", {"v": "Lost", "tone": "warn"}),
        ("toxic", {"v": "Toxic", "tone": "crit"}),
    ],
)
def test_backlink_status_tones_match_the_demo_semantics(
    status: str, expected: dict[str, str]
) -> None:
    resp = build_backlink_manager_workspace(
        [_backlink(status=status)], referring_domains=1, status_counts={}, new_in_window=0)
    assert _cell(resp, 0, 3) == expected


def test_backlink_dr_column_reads_the_stored_authority() -> None:
    resp = build_backlink_manager_workspace(
        [_backlink(authority=54)], referring_domains=1, status_counts={}, new_in_window=0)
    assert _cell(resp, 0, 2) == "54"


def test_backlink_toxic_tile_reads_the_status_breakdown() -> None:
    resp = build_backlink_manager_workspace(
        [], referring_domains=1240, status_counts={"new": 34, "toxic": 5}, new_in_window=9)
    tiles = _tiles(resp)
    assert tiles["Referring domains"] == "1,240"  # thousands-separated
    assert tiles["New links (30d)"] == "9"  # the WINDOW, not status_counts['new']=34
    assert tiles["Toxic flagged"] == "5"


# --------------------------------------------------------------------------- #
# 3. content_pipeline
# --------------------------------------------------------------------------- #
def _job(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "client_id": "cl-SECRET", "client_name": "NorthPeak Dental",
        "topic": "Teeth whitening guide", "stage": "Drafting", "status": "drafting",
        "words": 1850, "target": "WordPress", "created_at": "2026-07-16T09:00:00+00:00",
    }
    row.update(over)
    return row


def test_content_stage_prefers_the_rows_own_label_with_a_status_tone() -> None:
    """"Editing" is a real pipeline stage the worker writes; it is not a status value.
    The DISPLAY follows the human-facing label, the TONE follows the authoritative enum."""
    resp = build_content_pipeline_workspace([_job(stage="Editing", status="drafting")], {})
    assert _cell(resp, 0, 2) == {"v": "Editing", "tone": "info"}


def test_content_stage_falls_back_to_the_status_label_when_unlabelled() -> None:
    resp = build_content_pipeline_workspace([_job(stage="", status="needs_review")], {})
    assert _cell(resp, 0, 2) == {"v": "Review", "tone": "warn"}


def test_content_words_zero_is_a_dash_not_a_zero() -> None:
    """0 words means not drafted yet; "0" would read as an empty article."""
    resp = build_content_pipeline_workspace([_job(words=0)], {})
    assert _cell(resp, 0, 3) == _NONE


def test_content_words_are_thousands_separated() -> None:
    assert _cell(build_content_pipeline_workspace([_job(words=1850)], {}), 0, 3) == "1,850"


def test_content_in_pipeline_tile_excludes_terminal_statuses() -> None:
    stats = {"queued": 4, "drafting": 5, "needs_review": 3, "publishing": 0,
             "done": 24, "failed": 2, "rejected": 1}
    tiles = _tiles(build_content_pipeline_workspace([], stats))
    assert tiles["In pipeline"] == "12"  # 4+5+3+0 - done/failed/rejected have left
    assert tiles["Drafting"] == "5"
    assert tiles["Ready for review"] == "3"


# --------------------------------------------------------------------------- #
# 4. publishing
# --------------------------------------------------------------------------- #
def _web2(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "client_id": "cl-SECRET", "client_name": "Verde Cafe",
        "topic": "Seasonal menu launch", "platform": "Medium", "status": "published",
        "created_at": "2026-07-14T09:00:00+00:00",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("done", {"v": "Live", "tone": "ok"}),        # content's live state
        ("published", {"v": "Live", "tone": "ok"}),   # web2's live state - the SAME event
        ("publishing", {"v": "Scheduled", "tone": "info"}),
        ("needs_review", {"v": "Review", "tone": "warn"}),
        ("failed", {"v": "Failed", "tone": "crit"}),
        ("draft", {"v": "Draft", "tone": "mut"}),
        ("queued", {"v": "Draft", "tone": "mut"}),
    ],
)
def test_publishing_maps_both_status_vocabularies_onto_one(
    status: str, expected: dict[str, str]
) -> None:
    resp = build_publishing_workspace(
        [_job(status=status)], [], content_stats={}, web2_stats={})
    assert _cell(resp, 0, 3) == expected


def test_publishing_target_column_serves_both_ledgers() -> None:
    resp = build_publishing_workspace(
        [_job(target="PDF/Markdown")], [_web2(platform="Tumblr")],
        content_stats={}, web2_stats={})
    targets = {_cell(resp, i, 2) for i in range(2)}
    assert targets == {"PDF/Markdown", "Tumblr"}


def test_publishing_queue_is_ordered_newest_first_across_both_ledgers() -> None:
    resp = build_publishing_workspace(
        [_job(topic="older", created_at="2026-07-01T00:00:00+00:00")],
        [_web2(topic="newer", created_at="2026-07-20T00:00:00+00:00")],
        content_stats={}, web2_stats={})
    assert [_cell(resp, i, 0) for i in range(2)] == ["newer", "older"]


def test_publishing_tiles_sum_both_ledgers() -> None:
    tiles = _tiles(build_publishing_workspace(
        [], [],
        content_stats={"published": 24, "scheduled": 5, "failed": 1},
        web2_stats={"published": 3, "scheduled": 1, "failed": 2}))
    assert tiles["Published (30d)"] == "27"
    assert tiles["Scheduled"] == "6"
    assert tiles["Failed"] == "3"


def test_publishing_undated_row_sorts_last_rather_than_crashing() -> None:
    """A row with no created_at must not blow up the merge."""
    resp = build_publishing_workspace(
        [_job(topic="undated", created_at=None)],
        [_web2(topic="dated", created_at="2026-07-20T00:00:00+00:00")],
        content_stats={}, web2_stats={})
    assert [_cell(resp, i, 0) for i in range(2)] == ["dated", "undated"]


# --------------------------------------------------------------------------- #
# 5. reporting
# --------------------------------------------------------------------------- #
def _event(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "e1", "client_name": "NorthPeak Dental", "dataset": "audit",
        "rows": 120, "synced_at": datetime(2026, 6, 30, tzinfo=UTC),
    }
    row.update(over)
    return row


def test_reporting_names_a_report_from_the_modules_own_catalogue() -> None:
    """The dataset key ('audit') is internal; GET /reports/types calls it "Audit scores",
    and the workspace must agree with that surface rather than inventing a name."""
    resp = build_reporting_workspace([_event()], [], sent_in_window=0)
    assert _cell(resp, 0, 0) == "Audit scores"


def test_reporting_period_is_the_pushes_month() -> None:
    assert _cell(build_reporting_workspace([_event()], [], sent_in_window=0), 0, 2) == "June"


def test_reporting_period_dashes_when_the_stamp_is_unusable() -> None:
    """Never guess a month."""
    resp = build_reporting_workspace([_event(synced_at=None)], [], sent_in_window=0)
    assert _cell(resp, 0, 2) == _NONE
    resp = build_reporting_workspace([_event(synced_at="not-a-date")], [], sent_in_window=0)
    assert _cell(resp, 0, 2) == _NONE


def test_reporting_status_is_sent_because_the_row_only_exists_if_it_was() -> None:
    resp = build_reporting_workspace([_event()], [], sent_in_window=0)
    assert _cell(resp, 0, 3) == {"v": "Sent", "tone": "ok"}


def test_reporting_scheduled_tile_is_an_honest_dash() -> None:
    """No report-schedule table exists in 0020 or anywhere else."""
    tiles = _tiles(build_reporting_workspace([_event()], [], sent_in_window=48))
    assert tiles["Scheduled"] == _NONE
    assert tiles["Reports sent (30d)"] == "48"


def test_reporting_sheets_synced_filters_on_the_synced_state() -> None:
    workbooks = [{"status": "synced"}, {"status": "error"}, {"status": "syncing"}]
    tiles = _tiles(build_reporting_workspace([], workbooks, sent_in_window=0))
    assert tiles["Sheets synced"] == "1"


# --------------------------------------------------------------------------- #
# 6. task_board
# --------------------------------------------------------------------------- #
def _task(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "J-2042", "client_id": "cl-SECRET", "client_name": "NorthPeak Dental",
        "title": "Technical crawl + CWV", "status": "in_progress", "assignee_name": "Bilal",
        "updated_at": datetime.now(UTC),
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("todo", {"v": "To do", "tone": "mut"}),
        ("in_progress", {"v": "In progress", "tone": "info"}),
        ("review", {"v": "In review", "tone": "warn"}),
        ("done", {"v": "Done", "tone": "ok"}),
    ],
)
def test_task_status_tones_match_the_demo_semantics(
    status: str, expected: dict[str, str]
) -> None:
    resp = build_task_board_workspace([_task(status=status)], [])
    assert _cell(resp, 0, 3) == expected


def test_task_unassigned_row_says_so() -> None:
    resp = build_task_board_workspace([_task(assignee_name="")], [])
    assert _cell(resp, 0, 2) == "Unassigned"


def test_task_tiles_count_the_whole_ledger_not_the_preview() -> None:
    """The board preview is 8 rows; the tiles must fold every task."""
    ledger = [_task(status="todo") for _ in range(10)] + [_task(status="in_progress")]
    resp = build_task_board_workspace([_task()], ledger)
    tiles = _tiles(resp)
    assert tiles["Open tasks"] == "11"
    assert tiles["In progress"] == "1"


def test_task_done_window_excludes_old_completions() -> None:
    ledger = [
        _task(status="done", updated_at=datetime.now(UTC) - timedelta(days=3)),
        _task(status="done", updated_at=datetime.now(UTC) - timedelta(days=60)),
    ]
    assert _tiles(build_task_board_workspace([], ledger))["Done (30d)"] == "1"


def test_task_done_window_excludes_an_undatable_task() -> None:
    """A row we cannot date is counted OUT of a "(30d)" tile - never optimistically in."""
    ledger = [_task(status="done", updated_at=None), _task(status="done", updated_at="junk")]
    assert _tiles(build_task_board_workspace([], ledger))["Done (30d)"] == "0"


def test_task_done_window_accepts_a_naive_timestamp() -> None:
    """psycopg is configured for tz-aware stamps, but a naive one must not raise."""
    ledger = [_task(status="done", updated_at=datetime.now(UTC).replace(tzinfo=None))]
    assert _tiles(build_task_board_workspace([], ledger))["Done (30d)"] == "1"


# --------------------------------------------------------------------------- #
# 7. client_setup
# --------------------------------------------------------------------------- #
def _site(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "s1", "domain": "northpeakdental.com", "cms_type": "wordpress",
        "client_name": "NorthPeak Dental", "client_status": "active",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", {"v": "Active", "tone": "ok"}),
        ("trial", {"v": "Trial", "tone": "info"}),
        ("past_due", {"v": "Past due", "tone": "crit"}),
        ("paused", {"v": "Paused", "tone": "mut"}),
    ],
)
def test_client_setup_status_reports_the_clients_real_state(
    status: str, expected: dict[str, str]
) -> None:
    """A site row has no status column of its own; the client's subscription state is
    the real thing that decides whether the site is being worked on."""
    resp = build_client_setup_workspace([_site(client_status=status)], [], {})
    assert _cell(resp, 0, 3) == expected


@pytest.mark.parametrize(
    ("stored", "shown"),
    [("wordpress", "WordPress"), ("webflow", "Webflow"), ("ghost", "Ghost"), ("", _NONE)],
)
def test_client_setup_cms_label_uses_the_product_spelling(stored: str, shown: str) -> None:
    """An unknown CMS is title-cased, not dropped - it is still a CMS."""
    resp = build_client_setup_workspace([_site(cms_type=stored)], [], {})
    assert _cell(resp, 0, 2) == shown


def test_client_setup_pending_counts_clients_with_no_website() -> None:
    clients = [{"id": "cl-1"}, {"id": "cl-2"}, {"id": "cl-3"}]
    tiles = _tiles(build_client_setup_workspace([], clients, {"cl-1": 2, "cl-2": 1}))
    assert tiles["Clients"] == "3"
    assert tiles["Websites"] == "3"  # the SUM of the per-client counts
    assert tiles["Pending setup"] == "1"  # cl-3 has no site


def test_client_setup_pending_is_zero_when_every_client_has_a_site() -> None:
    clients = [{"id": "cl-1"}, {"id": "cl-2"}]
    assert _tiles(build_client_setup_workspace(
        [], clients, {"cl-1": 1, "cl-2": 1}))["Pending setup"] == "0"


# --------------------------------------------------------------------------- #
# 8. key_vault  (the leak proofs live in test_key_vault_safety.py)
# --------------------------------------------------------------------------- #
def _key(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "k1", "provider": "Serper.dev", "label": "Search",
        "masked": "sk-abc••••••••4cb6", "secret_sealed": b"SEALED",
        "kind": "api_key", "key_version": 1,
        "created_at": datetime(2026, 1, 4, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 4, tzinfo=UTC),
    }
    row.update(over)
    return row


def test_key_vault_rotated_key_shows_the_rotation_month() -> None:
    assert _cell(build_key_vault_workspace([_key()]), 0, 2) == "May 2026"


def test_key_vault_never_rotated_key_says_never() -> None:
    """An untouched row still carries its INSERT stamp in updated_at; presenting that as
    a rotation date would be a fabrication."""
    stamp = datetime(2026, 4, 2, tzinfo=UTC)
    resp = build_key_vault_workspace([_key(created_at=stamp, updated_at=stamp)])
    assert _cell(resp, 0, 2) == "Never"


def test_key_vault_unlabelled_key_dashes_rather_than_borrowing_a_field() -> None:
    resp = build_key_vault_workspace([_key(label="")])
    assert _cell(resp, 0, 1) == _NONE


def test_key_vault_integrations_tile_counts_distinct_providers() -> None:
    keys = [_key(provider="Google"), _key(provider="Google"), _key(provider="Anthropic")]
    tiles = _tiles(build_key_vault_workspace(keys))
    assert tiles["Keys stored"] == "3"
    assert tiles["Integrations"] == "2"


def test_key_vault_rotating_soon_is_an_honest_dash() -> None:
    """0004/0041 store no cadence and no expiry, so "soon" has nothing to evaluate."""
    assert _tiles(build_key_vault_workspace([_key()]))["Rotating soon"] == _NONE


def test_key_vault_status_is_active_for_a_stored_key() -> None:
    assert _cell(build_key_vault_workspace([_key()]), 0, 3) == {"v": "Active", "tone": "ok"}


# --------------------------------------------------------------------------- #
# 9. team_access
# --------------------------------------------------------------------------- #
def _member(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "u1", "name": "Ayesha Raza", "role": "manager", "status": "active",
        "email": "ayesha@aios.dev", "avatar_color": "#7B69EE", "title": "Manager",
    }
    row.update(over)
    return row


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", {"v": "Active", "tone": "ok"}),
        ("away", {"v": "Away", "tone": "warn"}),
        ("invited", {"v": "Invited", "tone": "info"}),
        ("offline", {"v": "Offline", "tone": "mut"}),
    ],
)
def test_member_status_tones_match_the_demo_semantics(
    status: str, expected: dict[str, str]
) -> None:
    resp = build_team_access_workspace([_member(status=status)], {}, role_count=6)
    assert _cell(resp, 0, 2) == expected


def test_member_role_is_the_capitalized_display_role() -> None:
    resp = build_team_access_workspace([_member(role="specialist")], {}, role_count=6)
    assert _cell(resp, 0, 1) == "Specialist"


def test_member_tasks_cell_reads_the_metric_and_zeroes_an_absent_member() -> None:
    """``member_metrics`` omits members with no tasks; an absent member is all-zero."""
    roster = [_member(id="u1"), _member(id="u2", name="Bilal Anwar")]
    resp = build_team_access_workspace(roster, {"u1": 6}, role_count=6)
    assert _cell(resp, 0, 3) == "6"
    assert _cell(resp, 1, 3) == "0"


def test_team_roles_tile_is_the_governance_role_set_not_the_roles_in_use() -> None:
    """One member holding one role does not mean the agency has one role."""
    tiles = _tiles(build_team_access_workspace([_member()], {}, role_count=6))
    assert tiles["Roles"] == "6"
    assert tiles["Members"] == "1"


def test_team_pending_invites_counts_the_invited_status() -> None:
    roster = [_member(status="active"), _member(status="invited"), _member(status="invited")]
    assert _tiles(build_team_access_workspace(roster, {}, role_count=6))["Pending invites"] == "2"


# --------------------------------------------------------------------------- #
# Cross-cutting: the preview is capped, and rows stay as wide as their columns.
# --------------------------------------------------------------------------- #
def test_a_long_ledger_is_capped_at_the_preview_depth() -> None:
    resp = build_technical_audit_workspace(
        [_audit(id=f"a{i}", url=f"site{i}.com") for i in range(30)], compute_audit_stats([]))
    assert resp.table is not None
    assert len(resp.table.rows) == 8


@pytest.mark.parametrize(("name", "build"), _EMPTY_BUILDS, ids=[n for n, _b in _EMPTY_BUILDS])
def test_column_count_is_always_four(name: str, build: Any) -> None:
    """Every tools.ts tool table is a 4-column grid; a row is positional against it."""
    resp = build()
    assert resp.table is not None
    assert len(resp.table.cols) == 4, name
