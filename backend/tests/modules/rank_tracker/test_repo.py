"""Rank-repo SQL: RLS scoping through the connection seam + the SQL-safety rules.

NO DB. ``rls_connection`` / ``privileged_connection`` are replaced with a fake context
manager yielding a capturing cursor, so every test asserts on the SQL the repo actually
composes and the identity it binds it under - the two things that decide whether a
tenant boundary holds.

Two invariants are load-bearing (``backend/CLAUDE.md`` invariants #3/#10):

1. **The RLS seam is the boundary.** ``RankRepo`` must open ``rls_connection`` with the
   caller's VERIFIED user id, so Postgres applies the ``0036`` policies. A read that
   slipped onto ``privileged_connection`` would silently BYPASS RLS and return every
   tenant's board - so the seam each method uses is pinned, not assumed.
2. **Never string-format a value or an identifier.** Every value must arrive as a bound
   ``%s``; the only dynamic identifiers (the UPDATE column list) must be quoted via
   ``psycopg.sql.Identifier``. The tests drive an injection-shaped payload through both
   doors and prove it stays inert data.

The privileged ``ServiceRankStore`` (the check worker's BYPASSRLS path) is covered for
the properties that cost money when they break: the R6 beat lock, the SKIP LOCKED
claim, and the ``on conflict`` idempotency that makes a redelivery a no-op.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from app.modules.rank_tracker import repo as repo_mod
from app.modules.rank_tracker.repo import (
    BEAT_LOCK_KEY,
    RankRepo,
    ServiceRankStore,
    get_rank_repo,
    service_rank_store,
)

pytestmark = pytest.mark.unit

_CALLER = "00000000-0000-0000-0000-0000000000a1"
_TODAY = date(2026, 7, 17)
_MIGRATION = (
    Path(__file__).resolve().parents[4] / "db" / "migrations" / "0036_rank_tracker.sql"
)


class _FakeCursor:
    """Captures every ``execute(query, params)`` and replays canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[Any, Any]] = []
        self.rowcount = 0
        # Per-call row queues let a multi-statement method (lock-then-claim,
        # insert-then-update) return a different result for each statement.
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
def repo() -> RankRepo:
    return RankRepo(_CALLER)


# --------------------------------------------------------------------------- #
# 1. The RLS seam IS the tenant boundary.
# --------------------------------------------------------------------------- #
def test_every_read_binds_the_callers_verified_id_on_the_rls_seam(
    repo: RankRepo, seam: _Seam
) -> None:
    """Each read must go through ``rls_connection(<caller>)``. On the privileged seam
    the same SQL would bypass every ``0036`` policy and return every client's board."""
    repo.list_keywords()
    repo.rank_stats()
    repo.get_by_code("RK-00001")
    repo.history("kw-1")
    repo.client_name_for("cl-1")
    repo.active_cadence_counts("cl-1")
    repo.client_budget("cl-1")

    assert seam.rls_ids == [_CALLER] * 7  # every call, same verified identity
    assert seam.privileged_opens == 0  # nothing leaked onto the BYPASSRLS seam


def test_every_mutation_stays_on_the_rls_seam(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Writes are RLS-scoped too: the 0036 insert/update policies (leads-only) are what
    # actually enforce the write boundary, and they only apply on this seam.
    cur.rows = [{"id": "kw-1"}]
    repo.add_keywords(
        client_id="cl-1", client_name="Acme", site_id=None,
        keywords=[("Roofer", "roofer")], target_url="", engine="google", device="desktop",
        location="", location_code=None, language="en", country="us", tags=[],
        cadence="weekly", next_check_on=_TODAY,
    )
    repo.update_keyword("RK-00001", {"status": "paused"})

    assert seam.privileged_opens == 0
    assert set(seam.rls_ids) == {_CALLER}


def test_the_repo_dependency_binds_the_identity_from_the_verified_user(seam: _Seam) -> None:
    """``get_rank_repo`` must take the id off the server-verified ``CurrentUser``.

    This is the join between auth and RLS: bind anything client-supplied here and the
    whole boundary is impersonatable.
    """
    from app.core.auth import CurrentUser

    user = CurrentUser(
        id="00000000-0000-0000-0000-0000000000b2", email="op@aios.dev", role="manager",
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )
    get_rank_repo(user).rank_stats()
    assert seam.rls_ids == ["00000000-0000-0000-0000-0000000000b2"]


def test_repo_reads_are_not_client_scoped_in_sql_so_rls_decides(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An unfiltered read emits NO client predicate - visibility is Postgres's call.

    Staff see the whole board (``is_staff()``); clients have no select policy at all
    (they read the portal view). Hard-coding a client filter here would be a second,
    divergent boundary.
    """
    repo.list_keywords()
    assert "where" not in cur.last_query.lower()
    assert "client_id" not in cur.last_query


# --------------------------------------------------------------------------- #
# 2. Ordering + aggregates.
# --------------------------------------------------------------------------- #
def test_the_board_puts_unranked_rows_last_not_first(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Postgres sorts NULLs FIRST for ``asc`` by default, so a plain ``order by
    latest_position`` would open the board with every keyword that does not rank."""
    repo.list_keywords()
    assert "order by latest_position asc nulls last, keyword, code" in cur.last_query


def test_stats_averages_ranked_rows_only(repo: RankRepo, cur: _FakeCursor, seam: _Seam) -> None:
    # The documented KPI choice, enforced in SQL: `avg` ignores NULLs natively and the
    # filter makes that explicit rather than incidental.
    repo.rank_stats()
    query = cur.last_query
    assert "avg(latest_position) filter (where latest_position is not null)" in query
    assert "coalesce(" in query  # an all-unranked board reads 0, not NULL


def test_stats_counts_every_row_as_tracked(repo: RankRepo, cur: _FakeCursor, seam: _Seam) -> None:
    # An unranked keyword IS tracked (and IS billed), so it must count here even though
    # it does not enter the average.
    repo.rank_stats()
    assert "count(*) as tracked" in cur.last_query


def test_stats_top_three_excludes_nulls(repo: RankRepo, cur: _FakeCursor, seam: _Seam) -> None:
    repo.rank_stats()
    assert "latest_position is not null and latest_position <= 3" in cur.last_query


def test_stats_of_an_empty_board_is_zeros_not_none(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = []
    assert repo.rank_stats() == {"tracked": 0, "avg_position": 0, "top_three": 0}


def test_stats_can_be_scoped_to_one_client(repo: RankRepo, cur: _FakeCursor, seam: _Seam) -> None:
    repo.rank_stats(client_id="cl-1")
    assert "where client_id = %s" in cur.last_query
    assert cur.last_params == ["cl-1"]


def test_history_is_newest_first_and_bounded(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.history("kw-1", limit=30)
    assert "order by checked_on desc limit %s" in cur.last_query
    assert cur.last_params == ("kw-1", 30)


def test_active_cadence_counts_excludes_paused_rows(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The projection prices the ACTIVE book: a paused subscription costs nothing, so
    including it would quote the client for spend that is not happening."""
    cur.rows = [{"cadence": "weekly", "n": 8}, {"cadence": "daily", "n": 2}]
    assert repo.active_cadence_counts("cl-1") == {"weekly": 8, "daily": 2}
    assert "status = 'active'" in cur.last_query
    assert "group by cadence" in cur.last_query
    assert cur.last_params == ("cl-1",)


def test_client_budget_returns_none_when_there_is_no_row(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # None = "no cap configured", which the projection treats as uncapped. It must be
    # distinguishable from (0, 0).
    cur.rows = []
    assert repo.client_budget("cl-1") is None


def test_client_budget_returns_the_cap_and_spent_pair(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"cap": 50, "spent": 12}]
    assert repo.client_budget("cl-1") == (50.0, 12.0)


# --------------------------------------------------------------------------- #
# 3. SQL safety: values bound, identifiers quoted, nothing interpolated.
# --------------------------------------------------------------------------- #
_INJECTION = "'; drop table public.tracked_keywords; --"


@pytest.mark.parametrize(
    ("kwarg", "column"),
    [
        ("client_id", "client_id = %s"),
        ("status", "status = %s"),
        ("engine", "engine = %s"),
        ("device", "device = %s"),
        ("tag", "tags @> array[%s]::text[]"),
    ],
)
def test_every_list_filter_is_a_bound_param_never_interpolated(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam, kwarg: str, column: str
) -> None:
    """Drive an injection payload through each filter: the SQL must carry a ``%s``
    placeholder and the payload must appear ONLY in the params."""
    repo.list_keywords(**{kwarg: _INJECTION})
    query, params = cur.calls[-1]
    text = _as_text(query)
    assert column in text
    assert _INJECTION not in text  # never spliced into the statement
    assert _INJECTION in params  # ... it stays inert data


def test_pagination_is_bound_too(repo: RankRepo, cur: _FakeCursor, seam: _Seam) -> None:
    repo.list_keywords(limit=5, offset=10)
    assert "limit %s offset %s" in cur.last_query
    assert cur.last_params == [5, 10]


def test_omitted_filters_add_no_clause_at_all(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A None filter must not become "= NULL" (which matches nothing) nor a literal.
    repo.list_keywords(client_id=None, status=None, engine=None, device=None, tag=None)
    assert "where" not in cur.last_query.lower()
    assert cur.last_params == []


def test_update_quotes_column_identifiers_and_binds_values(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The UPDATE's column list is the only dynamic identifier in the module: it must be
    composed with ``sql.Identifier`` (double-quoted), never f-stringed."""
    cur.rows = [{"code": "RK-00001"}]
    repo.update_keyword("RK-00001", {"status": "paused", "cadence": "daily"})
    text = cur.last_query
    assert '"status" = %s' in text and '"cadence" = %s' in text
    assert "paused" not in text and "daily" not in text  # values not spliced
    assert cur.last_params == ["paused", "daily", "RK-00001"]


def test_update_binds_the_code_rather_than_formatting_it(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The code comes straight off the URL path - the one caller-controlled string.
    cur.rows = [{"code": _INJECTION}]
    repo.update_keyword(_INJECTION, {"status": "paused"})
    assert _INJECTION not in cur.last_query
    assert _INJECTION in cur.last_params


def test_update_of_an_invisible_row_returns_none(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """RLS makes an unauthorised/unknown row simply invisible: the UPDATE matches 0 rows
    and the repo reports ``None`` (the router turns that into a clean 404)."""
    cur.rows = []
    assert repo.update_keyword("RK-NOPE", {"status": "paused"}) is None


def test_update_with_no_changes_degrades_to_a_plain_read(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"code": "RK-00001"}]
    assert repo.update_keyword("RK-00001", {}) == {"code": "RK-00001"}
    assert len(cur.calls) == 1
    assert "update" not in cur.last_query.lower()  # never an empty SET clause


def test_add_keywords_binds_every_row_and_defers_dedupe_to_the_unique_index(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.add_keywords(
        client_id="cl-1", client_name="Acme", site_id="s-1",
        keywords=[("Roof Repair", "roof repair"), ("Roofer", "roofer")],
        target_url="/roofing", engine="google", device="mobile", location="Karachi",
        location_code=1001, language="en", country="pk", tags=["money"],
        cadence="weekly", next_check_on=_TODAY,
    )
    query, params = cur.calls[-1]
    text = _as_text(query)
    assert (
        "on conflict (client_id, normalized_keyword, engine, device, location, language) "
        "do nothing" in text
    )
    assert "Roof Repair" not in text  # values bound, not spliced
    # Both the display form and the normalized key are bound, positionally, per row.
    assert params[:5] == ["cl-1", "Acme", "s-1", "Roof Repair", "roof repair"]
    assert params[15:20] == ["cl-1", "Acme", "s-1", "Roofer", "roofer"]


def test_add_keywords_with_nothing_usable_never_opens_a_connection(
    repo: RankRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An empty batch must be a no-op, not an INSERT with an empty VALUES list.
    assert repo.add_keywords(
        client_id="cl-1", client_name="Acme", site_id=None, keywords=[], target_url="",
        engine="google", device="desktop", location="", location_code=None, language="en",
        country="us", tags=[], cadence="weekly", next_check_on=_TODAY,
    ) == []
    assert cur.calls == [] and seam.rls_ids == []


def test_subscriptions_dedupe_via_a_nulls_not_distinct_index() -> None:
    """A duplicate subscription is a duplicate NIGHTLY CHARGE, so the dedupe has to hold
    even when an optional column is NULL.

    ``add_keywords`` leans entirely on ``on conflict (...) do nothing``, so the dedupe is
    only as good as the index it resolves against. Under DEFAULT SQL NULL semantics two
    NULLs are DISTINCT, so the constraint would never fire for a row with a NULL member -
    re-adding the same keyword would silently insert a SECOND subscription and bill it
    every night. 0036 therefore declares the index ``unique nulls not distinct`` (PG15+;
    we deploy PG16). This exact defect was found and fixed once in 0035 already.
    """
    normalized = " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())
    assert (
        "unique nulls not distinct (client_id, normalized_keyword, engine, device, "
        "location, language)" in normalized
    ), "0036 must declare the tracked_keywords unique index as `nulls not distinct`"


def test_the_history_table_has_a_one_snapshot_per_day_key() -> None:
    """The idempotency key the whole never-double-charge story rests on."""
    normalized = " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())
    assert "unique (keyword_id, checked_on)" in normalized


def test_history_is_append_only_at_the_app_tier() -> None:
    """Rank history is evidence the client is billed against, so 0036 deliberately
    grants NO update/delete policy on it - the sweeper runs as service_role instead."""
    sql_text = _MIGRATION.read_text(encoding="utf-8").lower()
    assert "create policy keyword_rankings_select" in sql_text
    assert "create policy keyword_rankings_insert" in sql_text
    assert "for update" not in sql_text.split("keyword_rankings_insert")[1]
    assert "create policy keyword_rankings_update" not in sql_text
    assert "create policy keyword_rankings_delete" not in sql_text


def test_both_tables_are_force_rls_and_the_client_reads_a_view_instead() -> None:
    normalized = " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())
    for table in ("tracked_keywords", "keyword_rankings"):
        assert f"alter table public.{table} enable row level security" in normalized
        assert f"alter table public.{table} force row level security" in normalized
    assert "create or replace view public.portal_rank_keywords with (security_barrier = true)" in normalized
    assert "where client_id = public.current_client_id()" in normalized
    assert "grant select on public.portal_rank_keywords to authenticated, anon" in normalized


def test_the_portal_view_exposes_no_cost_or_tenant_columns() -> None:
    """A client may see WHERE they rank, never what the agency pays to find out."""
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    view = sql_text.split("create or replace view public.portal_rank_keywords")[1].split(";")[0]
    for forbidden in ("cost", "client_id,", "site_id", "next_check_on", "provider"):
        assert forbidden not in view, f"portal view leaks {forbidden}"


# --------------------------------------------------------------------------- #
# 4. The privileged worker store (BYPASSRLS).
# --------------------------------------------------------------------------- #
def test_service_store_uses_the_privileged_seam_only(cur: _FakeCursor, seam: _Seam) -> None:
    """The check worker holds no user JWT, so its writes MUST run on
    ``privileged_connection`` (service_role). It must never open an RLS connection -
    there is no identity to bind."""
    cur.row_queue = [[{"locked": True}], [], [{"id": "kw-1"}], []]
    store = ServiceRankStore()
    store.claim_due_keywords(10)
    store.get_keyword("kw-1")
    assert seam.rls_ids == []
    assert seam.privileged_opens >= 2


def test_the_claim_takes_the_beat_lock_first_and_bails_when_it_cannot(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """R6: if a previous nightly dispatch is still draining, this tick must be a clean
    no-op - not a second fan-out, which would pay for every keyword twice."""
    cur.rows = [{"locked": False}]
    assert ServiceRankStore().claim_due_keywords(10) == []
    assert len(cur.calls) == 1  # it never even ran the claim
    assert "pg_try_advisory_xact_lock" in cur.queries[0]
    assert cur.calls[0][1] == (BEAT_LOCK_KEY,)  # the key is bound, not formatted


def test_the_claim_runs_only_after_the_lock_is_held(cur: _FakeCursor, seam: _Seam) -> None:
    cur.row_queue = [[{"locked": True}], [{"id": "kw-1"}]]
    assert ServiceRankStore().claim_due_keywords(10) == [{"id": "kw-1"}]
    assert "pg_try_advisory_xact_lock" in cur.queries[0]
    assert "for update skip locked" in cur.queries[1]


def test_the_claim_advances_next_check_on_in_the_same_statement(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """A keyword must leave the due set the moment it is handed out. Otherwise a
    redelivered dispatch re-fans it out and pays for a second check - the history's
    `on conflict` would swallow the duplicate ROW, but the money is already gone."""
    cur.row_queue = [[{"locked": True}], []]
    ServiceRankStore().claim_due_keywords(10)
    claim = cur.queries[1]
    assert "update public.tracked_keywords" in claim
    assert "set next_check_on = current_date +" in claim
    assert "case when t.cadence = 'daily' then 1 else 7 end" in claim


def test_the_claim_only_considers_active_due_rows(cur: _FakeCursor, seam: _Seam) -> None:
    cur.row_queue = [[{"locked": True}], []]
    ServiceRankStore().claim_due_keywords(25)
    claim = cur.queries[1]
    assert "k.status = 'active'" in claim
    assert "k.next_check_on <= current_date" in claim
    assert cur.calls[1][1] == (25,)  # the batch bound is a param


def test_the_lock_is_xact_scoped_not_session_scoped(cur: _FakeCursor, seam: _Seam) -> None:
    """On a POOLED connection a SESSION-scoped advisory lock could be released onto
    someone else's checkout, or leak forever if the worker died holding it. The
    xact-scoped form releases exactly when the claim transaction commits."""
    cur.row_queue = [[{"locked": True}], []]
    ServiceRankStore().claim_due_keywords(10)
    assert "pg_try_advisory_xact_lock" in cur.queries[0]
    assert "pg_advisory_lock" not in cur.queries[0]  # the session-scoped form


def test_get_keyword_left_joins_the_site_domain(cur: _FakeCursor, seam: _Seam) -> None:
    """The domain is what the check actually looks FOR in the SERP. An inner join would
    make every keyword with no linked site silently vanish from the worker's view."""
    cur.rows = [{"id": "kw-1"}]
    ServiceRankStore().get_keyword("kw-1")
    assert "left join public.sites s on s.id = t.site_id" in cur.last_query
    assert cur.last_params == ("kw-1",)


def test_record_check_is_idempotent_on_the_days_unique_key(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The property that makes ``task_acks_late`` redelivery safe."""
    cur.rows = []  # `returning id` found nothing -> the conflict fired
    assert _record(ServiceRankStore()) is False
    assert "on conflict (keyword_id, checked_on) do nothing" in cur.queries[0]
    assert len(cur.calls) == 1  # ... and the roll-forward was SKIPPED


def test_a_conflicting_redelivery_never_rolls_the_read_model_forward(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """Re-applying the same day would overwrite the real previous_position with today's
    and silently zero out the reported movement."""
    cur.rows = []
    _record(ServiceRankStore())
    assert not any("previous_position" in q for q in cur.queries)


def test_record_check_rolls_the_read_model_forward_on_a_fresh_snapshot(
    cur: _FakeCursor, seam: _Seam
) -> None:
    cur.row_queue = [[{"id": "r-1"}], []]
    assert _record(ServiceRankStore()) is True
    roll = cur.queries[1]
    assert "update public.tracked_keywords" in roll
    assert "previous_position = %s" in roll and "latest_position = %s" in roll


def test_best_position_coalesces_so_a_never_ranked_row_can_improve(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """``least(NULL, 5)`` is NULL in SQL, so without the coalesce a keyword's FIRST
    ranking would leave best_position permanently NULL."""
    cur.row_queue = [[{"id": "r-1"}], []]
    _record(ServiceRankStore())
    roll = cur.queries[1]
    assert "least(coalesce(best_position, %s), %s)" in roll


def test_an_unranked_reading_never_clobbers_the_best_position(
    cur: _FakeCursor, seam: _Seam
) -> None:
    # position NULL (unranked today) must leave the historical best intact - a keyword
    # that once hit #1 still HAS hit #1.
    cur.row_queue = [[{"id": "r-1"}], []]
    _record(ServiceRankStore(), position=None)
    assert "case when %s is null then best_position" in cur.queries[1]


def test_record_check_binds_every_value(cur: _FakeCursor, seam: _Seam) -> None:
    # The payload is provider-derived text - it must be bound like any untrusted value.
    cur.row_queue = [[{"id": "r-1"}], []]
    _record(ServiceRankStore(), ranking_url=_INJECTION)
    for query, params in cur.calls:
        assert _INJECTION not in _as_text(query)
        assert params is not None and _INJECTION in params


def test_replace_check_corrects_todays_row_without_touching_previous_position(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The forced re-check's write. It must NOT re-roll previous_position: that already
    rolled when today's first check landed, and re-rolling would overwrite yesterday's
    real reading with this morning's."""
    ServiceRankStore().replace_check(
        "kw-1", checked_on=_TODAY, position=1, ranking_url="/x", serp_features=[],
        own_urls="[]", delta=6, provider="serper", cost=0.01, next_check_on=_TODAY,
        checked_at=datetime.now(UTC), features=[],
    )
    update_ranking, update_keyword = cur.queries[0], cur.queries[1]
    assert "update public.keyword_rankings set" in update_ranking
    assert "where keyword_id = %s and checked_on = %s" in update_ranking
    assert "previous_position" not in update_keyword


def test_replace_check_accumulates_the_cost_rather_than_overwriting_it(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The client paid for BOTH reads of the day, so the day's recorded cost must be
    the sum - not just the last one."""
    ServiceRankStore().replace_check(
        "kw-1", checked_on=_TODAY, position=1, ranking_url="/x", serp_features=[],
        own_urls="[]", delta=None, provider="serper", cost=0.01, next_check_on=_TODAY,
        checked_at=datetime.now(UTC), features=[],
    )
    assert "cost = cost + %s" in cur.queries[0]


def test_record_stall_holds_the_freshness_stamp(cur: _FakeCursor, seam: _Seam) -> None:
    """The staleness signal's whole mechanism: advancing ONLY the schedule and HOLDING
    latest_checked_at is what lets the read side see the lag (the context worker's
    'HOLD the watermark' precedent)."""
    ServiceRankStore().record_stall("kw-1", next_check_on=_TODAY)
    assert "set next_check_on = %s" in cur.last_query
    assert "latest_checked_at" not in cur.last_query
    assert "latest_position" not in cur.last_query  # and the rank itself is untouched
    assert cur.last_params == (_TODAY, "kw-1")


def test_rollup_thins_before_it_purges(cur: _FakeCursor, seam: _Seam) -> None:
    result = ServiceRankStore().rollup_history(
        rollup_before=date(2026, 4, 18), purge_before=date(2024, 7, 18)
    )
    assert "distinct on (keyword_id, date_trunc('week', checked_on))" in cur.queries[0]
    assert cur.queries[1].strip().startswith("delete from public.keyword_rankings where checked_on < %s")
    assert result == {"rolled_up": 0, "purged": 0}  # the fake cursor reports no rowcount


def test_rollup_binds_its_date_windows(cur: _FakeCursor, seam: _Seam) -> None:
    ServiceRankStore().rollup_history(
        rollup_before=date(2026, 4, 18), purge_before=date(2024, 7, 18)
    )
    assert cur.calls[0][1] == (date(2026, 4, 18), date(2026, 4, 18))
    assert cur.calls[1][1] == (date(2024, 7, 18),)


def test_service_store_factory_is_stateless(seam: _Seam) -> None:
    # Each method opens its own connection, so instances hold no handle and are safe to
    # build per call from the task.
    assert isinstance(service_rank_store(), ServiceRankStore)
    assert service_rank_store() is not service_rank_store()


def _record(store: ServiceRankStore, **over: Any) -> bool:
    kwargs: dict[str, Any] = {
        "client_id": "cl-1", "checked_on": _TODAY, "position": 3, "ranking_url": "/x",
        "serp_features": ["local_pack"], "own_urls": "[]", "delta": 4, "provider": "serper",
        "cost": 0.01, "previous_position": 7, "next_check_on": _TODAY,
        "checked_at": datetime.now(UTC), "features": ["local_pack"],
    }
    kwargs.update(over)
    return store.record_check("kw-1", **kwargs)
