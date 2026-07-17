"""On-page repo SQL: the RLS seam, the SQL-safety rules, and the 0038 DB guard.

NO DB. ``rls_connection`` / ``privileged_connection`` are replaced with a fake context
manager yielding a capturing cursor, so every test asserts on the SQL the repo actually
composes and the identity it binds it under - the two things that decide whether a
tenant boundary holds.

Three invariants are load-bearing here:

1. **The RLS seam is the boundary** (invariant #3/#10). ``OnPageRepo`` must open
   ``rls_connection`` with the caller's VERIFIED user id. A read that slipped onto
   ``privileged_connection`` would silently BYPASS every 0038 policy.
2. **The APPLY path must run on the RLS seam.** This is stronger than the usual rule
   and it is the point of the whole module: the 0038 guard trigger refuses a
   recommendation lifecycle write that is not lead-attributed, so a recommendation
   UPDATE that leaked onto the privileged seam would be REJECTED BY POSTGRES - and,
   worse, would mean an unattended worker was rewriting a client's live site.
3. **Never string-format a value or an identifier.** Every value arrives as a bound
   ``%s``; the only dynamic identifiers (an UPDATE column list) are quoted via
   ``psycopg.sql.Identifier``. An injection-shaped payload is driven through both
   doors and must stay inert data.

The final section is a TEXT assertion on ``0038_on_page.sql`` itself: the 3-actor guard
cannot be unit-tested without a database, but its ABSENCE can be caught here, and that
trigger is the last line of defence for a client's live pages.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from app.modules.on_page import repo as repo_mod
from app.modules.on_page.repo import (
    OnPageRepo,
    ServiceOnPageStore,
    get_on_page_repo,
    service_on_page_store,
)

pytestmark = pytest.mark.unit

_CALLER = "00000000-0000-0000-0000-0000000000a1"
_MIGRATION = (
    Path(__file__).resolve().parents[3].parent / "db" / "migrations" / "0038_on_page.sql"
)


class _FakeCursor:
    """Captures every ``execute(query, params)`` and replays canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[Any, Any]] = []
        self.rowcount = 0
        self.row_queue: list[list[dict[str, Any]]] | None = None

    def execute(self, query: Any, params: Any = None) -> None:
        self.calls.append((query, params))
        if self.row_queue is not None:
            self.rows = self.row_queue.pop(0) if self.row_queue else []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    @property
    def queries(self) -> list[str]:
        return [_as_text(q) for q, _p in self.calls]

    @property
    def last_query(self) -> str:
        return _as_text(self.calls[-1][0])

    @property
    def last_params(self) -> Any:
        return self.calls[-1][1]


def _as_text(query: Any) -> str:
    """Render a str or a ``psycopg.sql.Composable`` to comparable text."""
    if isinstance(query, sql.Composable):
        return str(query.as_string(None))  # type: ignore[arg-type]
    return str(query)


class _Seam:
    """Records which connection seam was opened, and under which identity."""

    def __init__(self, cur: _FakeCursor) -> None:
        self.cur = cur
        self.rls_ids: list[str] = []
        self.privileged_opens = 0

    @contextlib.contextmanager
    def rls(self, user_id: str, **_kw: Any) -> Iterator[_FakeCursor]:
        self.rls_ids.append(user_id)
        yield self.cur

    @contextlib.contextmanager
    def privileged(self, **_kw: Any) -> Iterator[_FakeCursor]:
        self.privileged_opens += 1
        yield self.cur


@pytest.fixture
def cur() -> _FakeCursor:
    return _FakeCursor()


@pytest.fixture
def seam(cur: _FakeCursor, monkeypatch: pytest.MonkeyPatch) -> _Seam:
    """Replace BOTH connection seams so a test can prove which one a method used."""
    s = _Seam(cur)
    monkeypatch.setattr(repo_mod, "rls_connection", s.rls)
    monkeypatch.setattr(repo_mod, "privileged_connection", s.privileged)
    return s


@pytest.fixture
def repo() -> OnPageRepo:
    return OnPageRepo(_CALLER)


# --------------------------------------------------------------------------- #
# 1. The RLS seam IS the tenant boundary.
# --------------------------------------------------------------------------- #
def test_every_read_binds_the_callers_verified_id_on_the_rls_seam(
    repo: OnPageRepo, seam: _Seam
) -> None:
    repo.list_recommendations()
    repo.get_recommendation("rec-1")
    repo.list_analyses()
    repo.get_analysis_by_code("OP-0001")
    repo.client_name_for("cl-1")
    repo.site_url_for("site-1")

    assert seam.rls_ids == [_CALLER] * 6
    assert seam.privileged_opens == 0  # nothing leaked onto the BYPASSRLS seam


def test_the_live_site_writes_run_on_the_rls_seam_under_the_acting_lead(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    """THE module's core security property. The 0038 guard refuses a recommendation
    lifecycle write from ``service_role`` (``auth.uid() IS NULL``) outright, because
    applying a fix REWRITES A LIVE CLIENT PAGE and must be attributable to a human. So
    the apply/dismiss/revert UPDATE has to carry the lead's identity."""
    cur.rows = [{"id": "rec-1"}]
    repo.update_recommendation("rec-1", {"status": "applied"}, "open")

    assert seam.privileged_opens == 0
    assert seam.rls_ids and all(uid == _CALLER for uid in seam.rls_ids)


def test_create_analysis_runs_on_the_rls_seam(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    cur.rows = [{"code": "OP-0001"}]
    repo.create_analysis(
        client_id="cl-1", client_name="NorthPeak", site_id=None,
        page_url="https://np.example/p", target_keyword="kw",
        source_audit_id=None, created_by=_CALLER,
    )
    assert seam.rls_ids == [_CALLER]
    assert seam.privileged_opens == 0


def test_the_stats_read_is_rls_scoped(repo: OnPageRepo, seam: _Seam, cur: _FakeCursor) -> None:
    cur.rows = [{"analyzed": 3, "open": 2, "applied": 1}]
    assert repo.stats() == {"analyzed": 3, "open": 2, "applied": 1}
    assert seam.rls_ids == [_CALLER]


def test_stats_on_an_empty_board_yields_zeros(repo: OnPageRepo, seam: _Seam) -> None:
    assert repo.stats() == {"analyzed": 0, "open": 0, "applied": 0}


# --------------------------------------------------------------------------- #
# 2. SQL safety: bound values, quoted identifiers.
# --------------------------------------------------------------------------- #
def test_every_list_filter_is_a_bound_param_never_interpolated(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    evil = "'; drop table public.page_recommendations; --"
    repo.list_recommendations(
        client_id=evil, analysis_code=evil, status=evil, impact=evil,
        issue_code=evil, quick_win=True, limit=10, offset=0,
    )
    assert evil not in cur.last_query          # never reached the SQL text
    assert evil in cur.last_params             # it is inert DATA
    assert cur.last_query.count("%s") == len(cur.last_params)


def test_an_injection_shaped_code_stays_data_on_the_analysis_read(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    evil = "OP-1'; drop table public.onpage_analyses; --"
    repo.get_analysis_by_code(evil)
    assert evil not in cur.last_query
    assert cur.last_params == (evil,)


def test_update_column_names_are_quoted_identifiers_and_values_are_bound(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    cur.rows = [{"id": "rec-1"}]
    repo.update_recommendation(
        "rec-1", {"status": "applied", "current_value": "'; drop table x; --"}, "open"
    )
    update = cur.queries[0]
    assert '"status" = %s' in update              # quoted identifier, bound value
    assert '"current_value" = %s' in update
    # The VALUES are nowhere in the SQL text - they are bound params, inert data.
    assert "drop table" not in update
    assert cur.calls[0][1][:2] == ["applied", "'; drop table x; --"]


def test_the_expect_status_guard_is_appended_as_a_bound_param(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    """The optimistic-concurrency gate: ``where id = %s and status = %s``. It is what
    turns a concurrent double-apply into a no-op instead of a second live write."""
    cur.rows = [{"id": "rec-1"}]
    repo.update_recommendation("rec-1", {"status": "applied"}, "open")
    assert "where id = %s and status = %s" in cur.queries[0]
    assert cur.calls[0][1] == ["applied", "rec-1", "open"]


def test_without_expect_status_no_status_predicate_is_added(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    cur.rows = [{"id": "rec-1"}]
    repo.update_recommendation("rec-1", {"status": "applied"})
    assert "where id = %s" in cur.queries[0]
    assert "and status = %s" not in cur.queries[0]


def test_an_update_that_matches_no_row_returns_none(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    """A racing transition already moved the row -> 0 rows -> the router raises 409
    rather than silently double-advancing."""
    cur.rows = []
    assert repo.update_recommendation("rec-1", {"status": "applied"}, "open") is None
    assert repo.update_analysis("OP-0001", {"status": "queued"}, "done") is None


def test_the_analysis_update_binds_expect_status_too(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    cur.rows = [{"id": "an-1"}]
    repo.update_analysis("OP-0001", {"status": "queued"}, "done")
    assert "where code = %s and status = %s" in cur.queries[0]
    assert cur.calls[0][1] == ["queued", "OP-0001", "done"]


def test_jsonb_columns_are_wrapped_for_psycopg(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    """A raw dict is not adaptable to jsonb; an unwrapped write would fail at runtime."""
    from psycopg.types.json import Jsonb

    cur.rows = [{"id": "rec-1"}]
    repo.update_recommendation("rec-1", {"fix_payload": {"proposed_value": "x"}})
    assert isinstance(cur.calls[0][1][0], Jsonb)


def test_an_empty_change_set_short_circuits_to_a_plain_read(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    repo.update_recommendation("rec-1", {})
    assert all("update" not in q.lower() for q in cur.queries)


def test_the_recommendation_read_joins_the_analysis_for_its_public_code(
    repo: OnPageRepo, seam: _Seam
) -> None:
    """So a response can name its analysis (OP-####) without a second round-trip AND
    without ever surfacing the analysis UUID."""
    repo.list_recommendations()
    assert "join public.onpage_analyses" in repo_mod._REC_SELECT
    assert "a.code as analysis_code" in repo_mod._REC_SELECT


def test_the_recommendation_board_is_ordered_by_priority(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    repo.list_recommendations()
    assert "order by r.priority_score desc" in cur.last_query


def test_pagination_is_always_bound_not_formatted(
    repo: OnPageRepo, seam: _Seam, cur: _FakeCursor
) -> None:
    repo.list_recommendations(limit=25, offset=50)
    assert "limit %s offset %s" in cur.last_query
    assert cur.last_params[-2:] == [25, 50]


def test_the_repo_dependency_binds_the_verified_caller_id() -> None:
    class _User:
        id = _CALLER

    assert get_on_page_repo(_User()).\
        _user_id == _CALLER  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 3. The privileged store (the ANALYSIS worker only).
# --------------------------------------------------------------------------- #
@pytest.fixture
def store() -> ServiceOnPageStore:
    return ServiceOnPageStore()


def test_the_analysis_worker_store_uses_the_privileged_seam(
    store: ServiceOnPageStore, seam: _Seam, cur: _FakeCursor
) -> None:
    """The analysis worker has no user JWT. It only READS the client's page, so it is
    allowed to be anonymous - the 0038 trigger still holds it to the analysis
    lifecycle and forbids it from touching a recommendation's status."""
    store.load_analysis("OP-0001")
    store.update_analysis("OP-0001", {"status": "done"})
    store.clear_open_recommendations("an-1")
    store.audit_json_path("au-1")

    assert seam.privileged_opens == 4
    assert seam.rls_ids == []


def test_clear_open_recommendations_never_erases_a_human_decision(
    store: ServiceOnPageStore, seam: _Seam, cur: _FakeCursor
) -> None:
    """Applied / dismissed / reverted rows are the RECORD of what a lead decided about
    this page. A re-analysis rebuilds the OPEN queue and must not touch the rest."""
    store.clear_open_recommendations("an-1")
    assert "status = 'open'" in cur.last_query
    assert cur.last_params == ("an-1",)


def test_insert_recommendations_binds_every_value_and_wraps_the_jsonb(
    store: ServiceOnPageStore, seam: _Seam, cur: _FakeCursor
) -> None:
    from psycopg.types.json import Jsonb

    store.insert_recommendations("an-1", [{
        "client_id": "cl-1", "site_id": None, "page_url": "/p",
        "issue": "'; drop table x; --", "issue_code": "title_short", "impact": "High",
        "fix_kind": "title", "fix_payload": {"proposed_value": "t"},
        "current_value": "old", "priority_score": 75.0, "quick_win": True,
        "detail": {"length": 12},
    }])
    assert "drop table" not in cur.last_query      # inert data, not SQL
    assert "'; drop table x; --" in cur.last_params
    assert isinstance(cur.last_params[8], Jsonb)   # fix_payload
    assert isinstance(cur.last_params[12], Jsonb)  # detail


def test_inserting_no_recommendations_is_a_no_op(
    store: ServiceOnPageStore, seam: _Seam, cur: _FakeCursor
) -> None:
    assert store.insert_recommendations("an-1", []) == 0
    assert cur.calls == []


def test_the_store_factory_is_stateless() -> None:
    assert isinstance(service_on_page_store(), ServiceOnPageStore)


# --------------------------------------------------------------------------- #
# 4. The 0038 guard trigger: a TEXT assertion on the migration itself.
# --------------------------------------------------------------------------- #
# The 3-actor guard cannot be exercised without a live Postgres (the DB gate covers
# that), but its DISAPPEARANCE can be caught right here in the unit gate - and it is
# the last thing standing between a leaked service credential and a client's live
# pages. So we assert the migration still SAYS what it must.
def test_the_migration_declares_the_guard_trigger_on_both_tables() -> None:
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    assert "create or replace function public.onpage_guard_update()" in sql_text
    assert "before update on public.onpage_analyses" in sql_text
    assert "before update on public.page_recommendations" in sql_text
    assert "execute function public.onpage_guard_update()" in sql_text


def test_the_guard_is_security_definer_with_an_empty_search_path() -> None:
    """SECURITY DEFINER without a pinned search_path is a privilege-escalation hole:
    a caller could shadow ``public`` and have the definer run their function."""
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    guard = sql_text.split("function public.onpage_guard_update()")[1]
    assert "security definer" in guard
    assert "set search_path = ''" in guard


def test_the_guard_encodes_the_three_actor_model() -> None:
    sql_text = _MIGRATION.read_text(encoding="utf-8").lower()
    guard = sql_text.split("function public.onpage_guard_update()")[1]

    # 1. The WORKER (service_role => auth.uid() IS NULL) drives ONLY the analysis
    #    lifecycle: queued -> analyzing -> done|held|failed.
    assert "auth.uid() is null" in guard
    assert "'queued'" in guard and "'analyzing'" in guard
    assert "in ('done', 'held', 'failed')" in guard

    # 2. The LEADS own the apply gate.
    assert "public.current_app_role() in ('owner', 'admin', 'manager')" in guard

    # 3. A non-lead drives NOTHING.
    assert "a non-lead may not modify" in guard


def test_the_guard_forbids_the_worker_from_driving_a_recommendation_lifecycle() -> None:
    """THE rule that makes 'a live-site write is always lead-attributed' true even for
    a leaked service_role credential - service_role bypasses POLICIES but not TRIGGERS."""
    guard = _MIGRATION.read_text(encoding="utf-8").lower().split(
        "function public.onpage_guard_update()"
    )[1]
    assert "may not drive a recommendation lifecycle" in guard


def test_both_tables_are_enable_plus_force_rls() -> None:
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    for table in ("onpage_analyses", "page_recommendations"):
        assert f"alter table public.{table} enable row level security" in sql_text
        assert f"alter table public.{table} force row level security" in sql_text


def test_recommendation_writes_are_lead_only_in_rls() -> None:
    """The RLS policy and the app's Lead gate must agree, or a caller passes one and
    hits an opaque error at the other."""
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    for policy in ("page_recommendations_insert", "page_recommendations_update"):
        block = sql_text.split(f"create policy {policy}")[1].split(";")[0]
        assert "in ('owner', 'admin', 'manager')" in block


def test_clients_get_no_select_policy_on_either_table() -> None:
    """A portal client must not be able to read on-page work at all: staff-only via
    is_staff(), and no client policy exists to grant them anything."""
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    assert sql_text.count("using (public.is_staff())") == 2
    assert "client_id = auth.uid()" not in sql_text
