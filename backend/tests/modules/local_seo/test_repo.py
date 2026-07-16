"""Local-repo SQL: RLS scoping through the connection seam + the SQL-safety rules.

NO DB. ``rls_connection`` / ``privileged_connection`` are replaced with a fake context
manager yielding a capturing cursor, so every test asserts on the SQL the repo
actually composes and the identity it binds it under - the two things that decide
whether a tenant boundary holds.

Two invariants are load-bearing here (see ``backend/CLAUDE.md`` invariants #3/#10):

1. **The RLS seam is the boundary.** ``LocalRepo`` must open ``rls_connection`` with
   the caller's VERIFIED user id (never a client-supplied string), so Postgres applies
   the ``0039`` policies. A read that slipped onto ``privileged_connection`` would
   silently BYPASS RLS - so the seam each method uses is pinned, not assumed.
2. **Never string-format a value or an identifier.** Every value must arrive as a
   bound ``%s`` param; the only dynamic identifiers (the profile column lists) must be
   quoted via ``psycopg.sql.Identifier``.

The privileged ``ServiceLocalStore`` (the refresh worker's BYPASSRLS path) is covered
for its SKIP LOCKED claim and its paired current-row + history write.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any

import pytest
from psycopg import sql

from app.modules.local_seo import repo as repo_mod
from app.modules.local_seo.repo import (
    LocalRepo,
    ServiceLocalStore,
    get_local_repo,
    service_local_store,
)

pytestmark = pytest.mark.unit

_CALLER = "00000000-0000-0000-0000-0000000000a1"
_INJECTION = "'; drop table public.local_rankings; --"


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
    """Replace BOTH connection seams so a test can prove which one a method used."""
    s = _Seam(cur)
    monkeypatch.setattr(repo_mod, "rls_connection", s.rls)
    monkeypatch.setattr(repo_mod, "privileged_connection", s.privileged)
    return s


@pytest.fixture
def repo() -> LocalRepo:
    return LocalRepo(_CALLER)


# --------------------------------------------------------------------------- #
# 1. The RLS seam IS the tenant boundary.
# --------------------------------------------------------------------------- #
def test_every_read_binds_the_callers_verified_id_on_the_rls_seam(
    repo: LocalRepo, seam: _Seam
) -> None:
    """Each read must go through ``rls_connection(<caller>)``. On the privileged seam
    the same SQL would bypass every ``0039`` policy and return every tenant's board."""
    repo.list_rankings()
    repo.get_ranking("rk-1")
    repo.rank_history("rk-1")
    repo.list_profiles()
    repo.get_profile("gp-1")
    repo.citations_for_client("cl-1")
    repo.client_name_for("cl-1")

    assert seam.rls_ids == [_CALLER] * 7  # every call, same verified identity
    assert seam.privileged_opens == 0  # nothing leaked onto the BYPASSRLS seam


def test_local_stats_runs_all_three_counts_on_the_rls_seam(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The KPI tiles must be tenant-scoped like everything else: on the privileged seam
    # a client's dashboard would count every OTHER client's profiles and citations.
    cur.row_queue = [
        [{"gbp_profiles": 9}], [{"avg_map_rank": 3.2}], [{"citations": 210}]
    ]
    assert repo.local_stats() == {"gbp_profiles": 9, "avg_map_rank": 3.2, "citations": 210}
    assert seam.rls_ids == [_CALLER]  # one connection, three statements
    assert seam.privileged_opens == 0


def test_every_mutation_stays_on_the_rls_seam(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Writes are RLS-scoped too: the 0039 insert/update policies (leads-only) are what
    # actually enforce the write boundary, and they only apply on this seam.
    cur.rows = [{"id": "rk-1"}]
    repo.add_ranking(
        client_id="cl-1", client_name="Verde", profile_id="gp-1", keyword="cafe", geo="KHI"
    )
    repo.set_ranking_active("rk-1", is_active=False)
    repo.add_profile({"client_id": "cl-1", "location_label": "Karachi"})
    repo.update_profile("gp-1", {"primary_category": "Cafe"})

    assert seam.privileged_opens == 0
    assert set(seam.rls_ids) == {_CALLER}


def test_the_repo_dependency_binds_the_identity_from_the_verified_user(seam: _Seam) -> None:
    """``get_local_repo`` must take the id off the server-verified ``CurrentUser``.

    This is the join between auth and RLS: bind anything client-supplied here and the
    whole boundary is impersonatable.
    """
    from app.core.auth import CurrentUser

    user = CurrentUser(
        id="00000000-0000-0000-0000-0000000000b2", email="op@aios.dev", role="manager",
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )
    get_local_repo(user).list_profiles()
    assert seam.rls_ids == ["00000000-0000-0000-0000-0000000000b2"]


def test_repo_reads_are_not_client_scoped_in_sql_so_rls_decides(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An unfiltered read emits NO client predicate - visibility is Postgres's call.

    Staff see the whole board (``is_staff()``); clients have no select policy at all.
    Hard-coding a client filter here would be a second, divergent boundary.
    """
    repo.list_rankings()
    assert "where" not in cur.last_query.lower()
    assert "r.client_id" not in cur.last_query


# --------------------------------------------------------------------------- #
# 2. The citations KPI reads the EXISTING 0018 table.
# --------------------------------------------------------------------------- #
def test_the_citations_kpi_reads_the_existing_offpage_ledger(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The Citations tile counts ``public.citations`` - the table 0018_offpage owns.
    This module creates no citations table and must never write this one."""
    cur.row_queue = [[{"gbp_profiles": 1}], [{"avg_map_rank": 2}], [{"citations": 210}]]
    repo.local_stats()
    assert "count(*) as citations from public.citations" in cur.queries[2]


def test_the_citations_read_is_a_plain_select_never_a_write(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The off-page module owns every write to this ledger; local_seo only reads it.
    repo.citations_for_client("cl-1")
    query = cur.last_query.lower()
    assert query.startswith("select")
    for verb in ("insert", "update", "delete"):
        assert verb not in query
    assert cur.last_params == ("cl-1",)


def test_the_nap_read_selects_only_the_columns_the_report_folds(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A `select *` would couple this module to the off-page table's shape.
    repo.citations_for_client("cl-1")
    assert "select directory, nap_status, note from public.citations" in cur.last_query


def test_the_avg_map_rank_sql_counts_ranked_active_rows_only(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The documented choice, enforced in SQL: an unranked row has no number to
    average, and avg() over an empty set is NULL - hence the coalesce."""
    cur.row_queue = [[{"gbp_profiles": 1}], [{"avg_map_rank": 0}], [{"citations": 0}]]
    repo.local_stats()
    avg_sql = cur.queries[1]
    assert "coalesce(avg(rank), 0)" in avg_sql
    assert "where rank is not null and is_active" in avg_sql


def test_stats_coalesces_an_empty_board_to_zero_not_null(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.row_queue = [[], [], []]  # every count came back empty
    assert repo.local_stats() == {"gbp_profiles": 0, "avg_map_rank": 0, "citations": 0}


# --------------------------------------------------------------------------- #
# 3. SQL safety: values bound, identifiers quoted, nothing interpolated.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("kwarg", "column"),
    [
        ("client_id", "r.client_id = %s"),
        ("profile_id", "r.profile_id = %s"),
        ("keyword", "r.keyword = %s"),
        ("geo", "r.geo = %s"),
    ],
)
def test_every_list_filter_is_a_bound_param_never_interpolated(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam, kwarg: str, column: str
) -> None:
    """Drive an injection payload through each filter: the SQL must carry a ``%s``
    placeholder and the payload must appear ONLY in the params."""
    repo.list_rankings(**{kwarg: _INJECTION})
    query, params = cur.calls[-1]
    text = _as_text(query)
    assert column in text
    assert _INJECTION not in text  # never spliced into the statement
    assert _INJECTION in params  # ... it stays inert data


def test_boolean_and_pagination_filters_are_bound_too(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_rankings(in_map_pack=True, is_active=False, limit=5, offset=10)
    assert "r.in_map_pack = %s" in cur.last_query
    assert "r.is_active = %s" in cur.last_query
    assert "limit %s offset %s" in cur.last_query
    assert cur.last_params == [True, False, 5, 10]


def test_omitted_filters_add_no_clause_at_all(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A None filter must not become "= NULL" (which matches nothing) nor a literal.
    repo.list_rankings(client_id=None, keyword=None, in_map_pack=None)
    assert "where" not in cur.last_query.lower()
    assert cur.last_params == []


def test_the_ranking_list_sorts_unranked_rows_last(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """A bare ``order by rank`` floats every NULL to the TOP in Postgres - the board
    would open with the businesses that are not in the pack presented as the best."""
    repo.list_rankings()
    assert "order by r.rank asc nulls last" in cur.last_query


def test_the_ranking_list_joins_the_profile_for_the_location_cell(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_rankings()
    assert "join public.gbp_profiles p on p.id = r.profile_id" in cur.last_query
    assert "p.location_label" in cur.last_query


def test_add_ranking_defers_dedupe_to_the_nulls_not_distinct_index(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Re-tracking an existing (profile, keyword, geo) is benign and idempotent.

    The clause is only as good as the index it resolves against - 0039 declares it
    ``unique nulls not distinct``, which ``test_schemas`` pins.
    """
    cur.rows = [{"id": "rk-1"}]
    repo.add_ranking(
        client_id="cl-1", client_name="Verde", profile_id="gp-1", keyword="cafe", geo=None
    )
    text = cur.queries[0]
    assert "on conflict (profile_id, keyword, geo) do update" in text
    assert cur.calls[0][1] == ("cl-1", "Verde", "gp-1", "cafe", None)


def test_add_ranking_binds_a_null_geo_rather_than_omitting_the_column(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A geo-less add must bind NULL positionally - not drop the column (which would
    # shift every subsequent value into the wrong slot).
    cur.rows = [{"id": "rk-1"}]
    repo.add_ranking(
        client_id="cl-1", client_name="", profile_id="gp-1", keyword="cafe", geo=None
    )
    assert cur.calls[0][1][-1] is None


def test_add_profile_quotes_column_identifiers_and_binds_values(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.add_profile({"client_id": "cl-1", "location_label": "Karachi"})
    text = cur.last_query
    assert '"client_id"' in text and '"location_label"' in text  # quoted identifiers
    assert "Karachi" not in text  # values not spliced
    assert cur.last_params == ["cl-1", "Karachi"]


def test_update_profile_quotes_column_identifiers_and_binds_values(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The UPDATE's column list is a dynamic identifier: it must be composed with
    ``sql.Identifier`` (double-quoted), never f-stringed."""
    repo.update_profile("gp-1", {"primary_category": "Cafe", "nap_phone": "555"})
    text = cur.last_query
    assert '"primary_category" = %s' in text
    assert '"nap_phone" = %s' in text
    assert "Cafe" not in text and "555" not in text
    assert cur.last_params == ["Cafe", "555", "gp-1"]


def test_update_profile_binds_the_id_rather_than_formatting_it(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The id comes straight off the URL path - the one caller-controlled string.
    repo.update_profile(_INJECTION, {"nap_phone": "555"})
    assert _INJECTION not in cur.last_query
    assert _INJECTION in cur.last_params


def test_update_profile_with_no_changes_degrades_to_a_plain_read(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"id": "gp-1"}]
    assert repo.update_profile("gp-1", {}) == {"id": "gp-1"}
    assert len(cur.calls) == 1
    assert "update" not in cur.last_query.lower()  # never an empty SET clause


def test_add_profile_with_no_values_never_opens_a_connection(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An empty insert must be a no-op, not a statement with an empty column list.
    assert repo.add_profile({}) is None
    assert cur.calls == [] and seam.rls_ids == []


def test_set_active_of_an_invisible_row_returns_none_without_a_reread(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """RLS makes an unauthorised/unknown row simply invisible: the UPDATE matches 0
    rows and the repo reports ``None`` (the router turns that into a clean 404)."""
    cur.rows = []  # the `returning id` found nothing
    assert repo.set_ranking_active("rk-nope", is_active=True) is None
    assert len(cur.calls) == 1  # no pointless re-read


def test_client_name_for_returns_none_when_rls_hides_the_client(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An invisible client is indistinguishable from a missing one - the router turns
    both into 404, so a caller cannot probe for the existence of another tenant."""
    cur.rows = []
    assert repo.client_name_for("cl-someone-elses") is None
    assert cur.last_params == ("cl-someone-elses",)


def test_rank_history_is_bounded_and_newest_first(
    repo: LocalRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.rank_history("rk-1", limit=30)
    assert "order by checked_at desc limit %s" in cur.last_query
    assert cur.last_params == ("rk-1", 30)


# --------------------------------------------------------------------------- #
# 4. The privileged worker store (BYPASSRLS).
# --------------------------------------------------------------------------- #
def test_service_store_uses_the_privileged_seam_only(cur: _FakeCursor, seam: _Seam) -> None:
    """The refresh worker holds no user JWT, so its writes MUST run on
    ``privileged_connection`` (service_role). It must never open an RLS connection -
    there is no identity to bind."""
    store = ServiceLocalStore()
    store.claim_due_rankings(10)
    store.profile_for_ranking("gp-1")
    store.record_check(
        "rk-1", client_id="cl-1", rank=2, previous_rank=4, rank_change=2,
        in_map_pack=True, found_url="", top_competitors=[], provider="fake",
    )
    assert seam.rls_ids == []
    assert seam.privileged_opens >= 3


def test_the_claim_is_skip_locked_so_two_beats_never_take_the_same_row(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """SKIP LOCKED is the exactly-once-ish backbone: without it two concurrent beats
    would both claim the row and pay for the SAME check twice."""
    ServiceLocalStore().claim_due_rankings(50)
    text = cur.last_query
    assert "for update skip locked" in text
    assert "where is_active" in text  # inactive rows cost nothing
    assert "order by last_checked_at asc nulls first" in text  # oldest/never first
    assert cur.last_params == (50,)


def test_the_claim_stamps_last_checked_so_a_failing_row_cannot_starve_the_queue(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """Stamping AT CLAIM rotates the queue. Without it a row that fails every time
    would stay oldest forever and be re-claimed ahead of everything else, burning the
    whole batch on one broken keyword."""
    ServiceLocalStore().claim_due_rankings(10)
    assert "set last_checked_at = now()" in cur.last_query


def test_the_claim_returns_the_previous_rank_the_worker_needs_for_the_delta(
    cur: _FakeCursor, seam: _Seam
) -> None:
    ServiceLocalStore().claim_due_rankings(10)
    text = cur.last_query
    for column in ("r.id", "r.client_id", "r.profile_id", "r.keyword", "r.geo", "r.rank"):
        assert column in text


def test_record_check_writes_the_current_row_and_history_in_one_transaction(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """Both writes share ONE connection, so the current state and its timeline can
    never disagree (a crash between them would leave the board lying)."""
    ServiceLocalStore().record_check(
        "rk-1", client_id="cl-1", rank=2, previous_rank=4, rank_change=2,
        in_map_pack=True, found_url="https://x.example",
        top_competitors=["A", "B"], provider="serper_places",
    )
    assert seam.privileged_opens == 1  # ONE transaction
    assert "update public.local_rankings" in cur.queries[0]
    assert "insert into public.local_rank_history" in cur.queries[1]


def test_record_check_persists_a_null_rank_as_null(cur: _FakeCursor, seam: _Seam) -> None:
    """The honest absence reaches the DB as NULL on BOTH the current row and the
    history point - the schema's "checked, not in the pack"."""
    ServiceLocalStore().record_check(
        "rk-1", client_id="cl-1", rank=None, previous_rank=2, rank_change=0,
        in_map_pack=False, found_url="", top_competitors=[], provider="fake",
    )
    assert cur.calls[0][1][0] is None  # update ... set rank = NULL
    assert cur.calls[1][1][2] is None  # insert history rank NULL


def test_record_check_serializes_the_competitor_list_as_json(
    cur: _FakeCursor, seam: _Seam
) -> None:
    # top_competitors is a jsonb column; a bare Python list would not adapt.
    ServiceLocalStore().record_check(
        "rk-1", client_id="cl-1", rank=1, previous_rank=None, rank_change=0,
        in_map_pack=True, found_url="", top_competitors=["Bean There"], provider="fake",
    )
    assert json.loads(cur.calls[0][1][5]) == ["Bean There"]


def test_the_service_store_binds_every_value(cur: _FakeCursor, seam: _Seam) -> None:
    # The worker's payload is provider-derived text - it must be bound like any other
    # untrusted value (a competitor's business name is attacker-influenceable).
    ServiceLocalStore().record_check(
        "rk-1", client_id="cl-1", rank=1, previous_rank=None, rank_change=0,
        in_map_pack=True, found_url=_INJECTION, top_competitors=[_INJECTION],
        provider="fake",
    )
    for query, _params in cur.calls:
        assert _INJECTION not in _as_text(query)
    assert _INJECTION in cur.calls[0][1]


def test_update_profile_sync_serializes_its_json_columns(cur: _FakeCursor, seam: _Seam) -> None:
    ServiceLocalStore().update_profile_sync(
        "gp-1", primary_category="Cafe", secondary_categories=["Bakery"],
        nap_name="V", nap_address="1 Main St", nap_phone="555", website_uri="",
        regular_hours={"mon": "9-5"}, review_count=3, avg_rating=4.5,
        completeness_score=80, audit={"missing": []},
    )
    params = cur.last_params
    assert json.loads(params[6]) == {"mon": "9-5"}  # regular_hours jsonb
    assert json.loads(params[10]) == {"missing": []}  # audit jsonb
    assert params[1] == ["Bakery"]  # text[] adapts natively


def test_service_store_factory_is_stateless(seam: _Seam) -> None:
    # Each method opens its own connection, so instances hold no handle and are safe
    # to build per call from the task.
    assert isinstance(service_local_store(), ServiceLocalStore)
    assert service_local_store() is not service_local_store()
