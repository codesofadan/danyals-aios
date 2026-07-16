"""Onboarding-repo SQL: RLS scoping through the connection seam + the SQL-safety rules.

NO DB. ``rls_connection`` / ``privileged_connection`` are replaced with a fake context
manager yielding a capturing cursor, so every test asserts on the SQL the repo actually
composes and the identity it binds it under - the two things that decide whether a
tenant boundary holds.

Two invariants are load-bearing here (see ``backend/CLAUDE.md`` invariants #3/#10):

1. **The RLS seam is the boundary.** ``OnboardingRepo`` must open ``rls_connection``
   with the caller's VERIFIED user id (never a client-supplied string), so Postgres
   applies the ``0040`` policies. This module has NO privileged store at all - a
   stronger position than having one and being careful with it - and the sweep below
   pins exactly that: not one method may touch the BYPASSRLS seam.
2. **Never string-format a value or an identifier.** Every value must arrive as a
   bound ``%s`` param; the only dynamic identifiers (the UPDATE column lists) must be
   quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import pytest
from psycopg import sql

from app.modules.client_onboarding import repo as repo_mod
from app.modules.client_onboarding.repo import (
    LIVE_STATUSES,
    OnboardingRepo,
    get_onboarding_repo,
)

pytestmark = pytest.mark.unit

_CALLER = "00000000-0000-0000-0000-0000000000a1"
_INJECTION = "'; drop table public.onboarding_steps; --"


class _FakeCursor:
    """Captures every ``execute(query, params)`` and replays canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[Any, Any]] = []
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
    s = _Seam(cur)
    monkeypatch.setattr(repo_mod, "rls_connection", s.rls)
    # The module imports no privileged_connection at all; install one anyway so a
    # future method that reaches for it is caught by the sweep rather than by prod.
    monkeypatch.setattr(repo_mod, "privileged_connection", s.privileged, raising=False)
    return s


@pytest.fixture
def repo() -> OnboardingRepo:
    return OnboardingRepo(_CALLER)


# --------------------------------------------------------------------------- #
# 1. The RLS seam IS the tenant boundary.
# --------------------------------------------------------------------------- #
def test_every_read_binds_the_callers_verified_id_on_the_rls_seam(
    repo: OnboardingRepo, seam: _Seam
) -> None:
    """Each read must go through ``rls_connection(<caller>)``. On the privileged seam
    the same SQL would bypass every ``0040`` policy and expose the whole board."""
    repo.list_runs()
    repo.get_run("run-1")
    repo.active_run_for("cl-1")
    repo.list_steps("run-1")
    repo.list_board()
    repo.live_run_steps()
    repo.get_step("run-1", "st-1")
    repo.onboarding_stats()
    repo.client_name_for("cl-1")
    repo.staff_for("u-1")

    assert seam.rls_ids == [_CALLER] * 10  # every call, same verified identity
    assert seam.privileged_opens == 0  # nothing leaked onto the BYPASSRLS seam


def test_every_mutation_stays_on_the_rls_seam(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Writes are RLS-scoped too: the 0040 insert/update policies (leads-only) are what
    # actually enforce the write boundary, and they only apply on this seam.
    cur.rows = [{"id": "run-1"}]
    repo.insert_run(
        client_id="cl-1", client_name="Acme", template_key="local_seo_default",
        owner_user_id="u-1", owner_name="Sara",
    )
    repo.update_run("run-1", {"status": "completed"})
    repo.seed_steps(
        run_id="run-1", client_id="cl-1", client_name="Acme",
        steps=[{"step_key": "kickoff", "label": "Kickoff", "sort_order": 1}],
    )
    repo.update_step("run-1", "st-1", {"status": "completed"})

    assert seam.privileged_opens == 0
    assert set(seam.rls_ids) == {_CALLER}


def test_the_module_has_no_privileged_store_at_all() -> None:
    """This module deliberately ships NO BYPASSRLS seam: every write has a real
    authenticated lead behind it, and the sensitivity of the data makes "no such seam
    exists" materially stronger than "one exists but we are careful". The one
    privileged write onboarding causes is the vault seal, inside app/services/vault.py
    where it always lived."""
    assert not hasattr(repo_mod, "ServiceOnboardingStore")
    assert "privileged_connection" not in repo_mod.__dict__


def test_the_repo_dependency_binds_the_identity_from_the_verified_user(seam: _Seam) -> None:
    """``get_onboarding_repo`` must take the id off the server-verified ``CurrentUser``.

    This is the join between auth and RLS: bind anything client-supplied here and the
    whole boundary is impersonatable."""
    from app.core.auth import CurrentUser

    user = CurrentUser(
        id="00000000-0000-0000-0000-0000000000b2", email="op@aios.dev", role="manager",
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )
    get_onboarding_repo(user).onboarding_stats()
    assert seam.rls_ids == ["00000000-0000-0000-0000-0000000000b2"]


def test_reads_are_not_client_scoped_in_sql_so_rls_decides(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An unfiltered board read emits NO client predicate - visibility is Postgres's
    call. Staff see the whole board (``is_staff()``); clients have no select policy at
    all. Hard-coding a filter here would be a second, divergent boundary."""
    repo.list_board()
    assert "where" not in cur.last_query.lower()
    assert "client_id" not in cur.last_query


# --------------------------------------------------------------------------- #
# 2. THE SECRET NEVER TOUCHES THIS TABLE.
# --------------------------------------------------------------------------- #
def test_the_steps_table_has_no_secret_column_in_any_composed_statement(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The structural guarantee: onboarding_steps has no secret column (0040), so no
    statement this repo composes can write one. Only the opaque reference moves."""
    repo.seed_steps(
        run_id="run-1", client_id="cl-1", client_name="Acme",
        steps=[{"step_key": "collect_gbp", "label": "Collect GBP access", "sort_order": 2}],
    )
    repo.update_step("run-1", "st-1", {"vault_secret_id": "vk-1", "status": "completed"})
    for query in cur.queries:
        assert "secret_sealed" not in query
        assert "secret" not in query.replace("vault_secret_id", "")


def test_update_step_binds_the_vault_reference_as_a_plain_value(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The reference is data like any other: bound, never spliced.
    cur.rows = [{"id": "st-1"}]
    repo.update_step("run-1", "st-1", {"vault_secret_id": "vk-9f2a"})
    assert '"vault_secret_id" = %s' in cur.last_query
    assert "vk-9f2a" not in cur.last_query
    assert cur.last_params == ["vk-9f2a", "st-1", "run-1"]


def test_a_plaintext_secret_can_never_reach_the_steps_table_through_update(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Belt-and-braces: even if a caller somehow handed the repo a secret-shaped
    change, the column does not exist - so this would fail at the DB, not silently
    persist. The test pins that the repo adds no such column of its own."""
    cur.rows = [{"id": "st-1"}]
    repo.update_step("run-1", "st-1", {"status": "completed"})
    assert "hunter2" not in cur.last_query
    assert cur.last_params == ["completed", "st-1", "run-1"]


# --------------------------------------------------------------------------- #
# 3. SQL safety: values bound, identifiers quoted, nothing interpolated.
# --------------------------------------------------------------------------- #
def test_list_runs_status_filter_is_a_bound_param(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_runs(status=_INJECTION)
    assert "where status = %s" in cur.last_query
    assert _INJECTION not in cur.last_query
    assert _INJECTION in cur.last_params


def test_list_board_status_filter_is_a_bound_param(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_board(status=_INJECTION)
    assert "where status = %s" in cur.last_query
    assert _INJECTION not in cur.last_query
    assert _INJECTION in cur.last_params


def test_omitted_filters_add_no_clause_at_all(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A None filter must not become "= NULL" (which matches nothing) nor a literal.
    repo.list_runs(status=None)
    assert "where" not in cur.last_query.lower()
    assert cur.last_params == []


def test_pagination_is_bound_and_capped_by_the_caller(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_runs(limit=5, offset=10)
    assert "limit %s offset %s" in cur.last_query
    assert cur.last_params == [5, 10]


def test_list_runs_orders_newest_first_with_a_stable_tiebreak(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An unstable sort would duplicate/skip rows between pages.
    repo.list_runs()
    assert "order by created_at desc, id" in cur.last_query


def test_list_steps_orders_by_the_template_order(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_steps("run-1")
    assert "order by sort_order, id" in cur.last_query
    assert cur.last_params == ("run-1",)


def test_update_run_quotes_column_identifiers_and_binds_values(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"id": "run-1"}]
    repo.update_run("run-1", {"status": "completed", "completed_at": "2026-07-17"})
    assert '"status" = %s' in cur.last_query
    assert '"completed_at" = %s' in cur.last_query
    assert "completed" not in cur.last_query.replace('"completed_at"', "")
    assert cur.last_params == ["completed", "2026-07-17", "run-1"]


def test_update_step_quotes_column_identifiers_and_binds_values(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The UPDATE's column list is the only dynamic identifier here: it must be
    composed with ``sql.Identifier`` (double-quoted), never f-stringed."""
    cur.rows = [{"id": "st-1"}]
    repo.update_step("run-1", "st-1", {"status": "completed", "notes": _INJECTION})
    assert '"status" = %s' in cur.last_query and '"notes" = %s' in cur.last_query
    assert _INJECTION not in cur.last_query  # values not spliced
    assert cur.last_params == ["completed", _INJECTION, "st-1", "run-1"]


def test_update_step_binds_the_ids_rather_than_formatting_them(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Both ids come straight off the URL path - the caller-controlled strings.
    cur.rows = [{"id": "st-1"}]
    repo.update_step(_INJECTION, _INJECTION, {"status": "completed"})
    assert _INJECTION not in cur.last_query
    assert cur.last_params == ["completed", _INJECTION, _INJECTION]


def test_update_step_is_scoped_to_its_run(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """A step id from ANOTHER run must not be editable through this run's URL - the
    run_id predicate is what makes a mismatched pair a clean 404 instead of an edit
    applied to the wrong client's checklist."""
    cur.rows = [{"id": "st-1"}]
    repo.update_step("run-1", "st-1", {"status": "completed"})
    assert "where id = %s and run_id = %s" in cur.last_query


def test_get_step_is_scoped_to_its_run(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.get_step("run-1", "st-1")
    assert "where id = %s and run_id = %s" in cur.last_query
    assert cur.last_params == ("st-1", "run-1")


def test_update_of_an_invisible_row_returns_none(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """RLS makes an unauthorised/unknown row simply invisible: the UPDATE matches 0
    rows and the repo reports ``None`` (the router turns that into a clean 404)."""
    cur.rows = []
    assert repo.update_step("run-1", "st-nope", {"status": "completed"}) is None
    assert repo.update_run("run-nope", {"status": "completed"}) is None


def test_update_with_no_changes_degrades_to_a_plain_read(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"id": "st-1"}]
    assert repo.update_step("run-1", "st-1", {}) == {"id": "st-1"}
    assert "update" not in cur.last_query.lower()  # never an empty SET clause
    cur.calls.clear()
    assert repo.update_run("run-1", {}) == {"id": "st-1"}
    assert "update" not in cur.last_query.lower()


# --------------------------------------------------------------------------- #
# 4. The one-live-run rule.
# --------------------------------------------------------------------------- #
def test_live_statuses_are_exactly_the_partial_index_predicate() -> None:
    """The 0040 partial unique index fires on ``status in ('in_progress','on_hold')``.
    This constant drives the app-side guard, the KPI and the workspace board - if it
    drifted from the index, the guard would let through exactly what the index then
    rejects with an opaque error."""
    assert LIVE_STATUSES == ("in_progress", "on_hold")


def test_the_partial_unique_index_predicate_matches_this_constant() -> None:
    # Pin BOTH halves: the constant above is only as good as the index it mirrors.
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[4] / "db" / "migrations" / "0040_client_onboarding.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())
    assert "create unique index if not exists onboarding_runs_one_active" in normalized
    assert "on public.onboarding_runs (client_id) where status in ('in_progress', 'on_hold')" \
        in normalized


def test_active_run_lookup_binds_the_live_statuses(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.active_run_for("cl-1")
    assert "where client_id = %s and status = any(%s)" in cur.last_query
    assert cur.last_params == ("cl-1", ["in_progress", "on_hold"])


def test_insert_run_defers_the_duplicate_guard_to_the_index(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """``on conflict do nothing`` + the partial unique index is what actually holds
    under a race; the app-side ``active_run_for`` check is only there to turn the
    common case into a clean 409."""
    cur.rows = [{"id": "run-1"}]
    repo.insert_run(
        client_id="cl-1", client_name="Acme", template_key="local_seo_default",
        owner_user_id="u-1", owner_name="Sara", target_date=None,
    )
    assert "on conflict do nothing returning *" in cur.last_query
    assert cur.last_params == ("cl-1", "Acme", "local_seo_default", "u-1", "Sara", None)


def test_insert_run_returns_none_when_the_index_rejected_it(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = []  # `on conflict do nothing` wrote nothing
    assert repo.insert_run(
        client_id="cl-1", client_name="Acme", template_key="t", owner_user_id=None,
        owner_name="", target_date=None,
    ) is None


# --------------------------------------------------------------------------- #
# 5. Seeding SQL.
# --------------------------------------------------------------------------- #
def test_seed_steps_binds_every_row_and_defers_dedupe_to_the_unique_index(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.seed_steps(
        run_id="run-1", client_id="cl-1", client_name="Acme",
        steps=[
            {"step_key": "kickoff", "label": "Kickoff call & goals", "sort_order": 1},
            {"step_key": "collect_gbp", "label": "Collect GBP access", "sort_order": 2},
        ],
    )
    assert "on conflict (run_id, step_key) do nothing" in cur.last_query
    assert "Kickoff call & goals" not in cur.last_query  # values bound, not spliced
    assert cur.last_params == [
        "run-1", "cl-1", "Acme", "kickoff", "Kickoff call & goals", 1,
        "run-1", "cl-1", "Acme", "collect_gbp", "Collect GBP access", 2,
    ]


def test_seed_steps_with_nothing_to_write_never_opens_a_connection(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An empty seed must be a no-op, not an INSERT with an empty VALUES list.
    assert repo.seed_steps(run_id="run-1", client_id="cl-1", client_name="A", steps=[]) == []
    assert cur.calls == [] and seam.rls_ids == []


def test_the_steps_unique_index_backs_the_conflict_clause() -> None:
    """``seed_steps`` leans entirely on ``on conflict (run_id, step_key) do nothing``,
    so the idempotency is only as good as the index it resolves against."""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[4] / "db" / "migrations" / "0040_client_onboarding.sql"
    ).read_text(encoding="utf-8")
    assert "unique (run_id, step_key)" in " ".join(migration.lower().split())


# --------------------------------------------------------------------------- #
# 6. Stats + snapshot lookups.
# --------------------------------------------------------------------------- #
def test_stats_reads_all_three_tiles_in_one_round_trip(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.onboarding_stats()
    assert len(cur.calls) == 1
    assert len(seam.rls_ids) == 1


def test_stats_counts_pending_steps_of_live_runs_only(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """A pending step on a completed/archived run is HISTORY, not a to-do - counting
    it would make the "steps pending" tile grow forever and stop meaning anything."""
    repo.onboarding_stats()
    query = " ".join(cur.last_query.split())
    assert "join public.onboarding_runs r on r.id = s.run_id" in query
    assert "where r.status = any(%s)" in query
    assert "s.status in ('pending', 'in_progress', 'blocked')" in query


def test_stats_thirty_day_window_is_bounded_by_completed_at(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.onboarding_stats()
    query = " ".join(cur.last_query.split())
    assert "completed_at >= now() - interval '30 days'" in query
    assert cur.last_params == (["in_progress", "on_hold"], ["in_progress", "on_hold"])


def test_stats_of_an_empty_board_is_zeros_not_none(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = []
    assert repo.onboarding_stats() == {
        "in_onboarding": 0, "steps_pending": 0, "completed_30d": 0
    }


def test_live_run_steps_reads_only_live_runs(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.live_run_steps()
    query = " ".join(cur.last_query.split())
    assert "join public.onboarding_runs r on r.id = s.run_id" in query
    assert "where r.status = any(%s)" in query
    assert cur.last_params == (["in_progress", "on_hold"],)


def test_live_run_steps_is_one_query_not_an_n_plus_one(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"run_id": f"r{i}"} for i in range(20)]
    repo.live_run_steps()
    assert len(cur.calls) == 1  # the whole live board in one round-trip


def test_client_name_for_returns_none_when_rls_hides_the_client(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An invisible client is indistinguishable from a missing one - the router turns
    both into 404, so a caller cannot probe for the existence of another tenant."""
    cur.rows = []
    assert repo.client_name_for("cl-someone-elses") is None
    assert cur.last_params == ("cl-someone-elses",)


def test_client_name_for_returns_the_display_snapshot(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"name": "Orchard Pediatrics"}]
    assert repo.client_name_for("cl-1") == "Orchard Pediatrics"


def test_staff_lookup_excludes_portal_clients_in_sql(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """A portal client must never become the owner of an onboarding step: that would
    hand a tenant a seat on a staff-only board. The exclusion belongs in SQL, where a
    caller cannot route around it."""
    repo.staff_for("u-1")
    assert "role <> 'client'" in cur.last_query
    assert cur.last_params == ("u-1",)


def test_staff_lookup_returns_the_display_snapshot(
    repo: OnboardingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"name": "Sara Khan", "avatar_color": "#7B69EE"}]
    row = repo.staff_for("u-1")
    assert row is not None and row["name"] == "Sara Khan"
