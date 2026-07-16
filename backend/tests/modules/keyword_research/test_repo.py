"""Keyword-repo SQL: RLS scoping through the connection seam + the SQL-safety rules.

NO DB. ``rls_connection`` / ``privileged_connection`` are replaced with a fake
context manager yielding a capturing cursor, so every test asserts on the SQL the
repo actually composes and the identity it binds it under - the two things that
decide whether a tenant boundary holds.

Two invariants are load-bearing here (see ``backend/CLAUDE.md`` invariants #3/#10):

1. **The RLS seam is the boundary.** ``KeywordRepo`` must open ``rls_connection``
   with the caller's VERIFIED user id (never a client-supplied string), so Postgres
   applies the ``0035`` policies. A read that slipped onto ``privileged_connection``
   would silently BYPASS RLS - so the seam each method uses is pinned, not assumed.
2. **Never string-format a value or an identifier.** Every value must arrive as a
   bound ``%s`` param; the only dynamic identifiers (the UPDATE column list) must be
   quoted via ``psycopg.sql.Identifier``. The tests below drive an injection-shaped
   payload through both doors and prove it stays inert data.

The privileged ``ServiceKeywordStore`` (the research worker's BYPASSRLS ingest) is
covered for its upsert IDEMPOTENCY - the property that makes a Celery redelivery a
safe no-op.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from app.modules.keyword_research import repo as repo_mod
from app.modules.keyword_research.repo import (
    KeywordRepo,
    ServiceKeywordStore,
    get_keyword_repo,
    service_keyword_store,
)

pytestmark = pytest.mark.unit

_CALLER = "00000000-0000-0000-0000-0000000000a1"


class _FakeCursor:
    """Captures every ``execute(query, params)`` and replays canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[Any, Any]] = []
        # Per-call row queues let a multi-statement method (select-then-update)
        # return a different result for each statement.
        self.row_queue: list[list[dict[str, Any]]] | None = None

    def execute(self, query: Any, params: Any = None) -> None:
        self.calls.append((query, params))
        if self.row_queue is not None:
            self.rows = self.row_queue.pop(0) if self.row_queue else []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    # --- assertions helpers ---
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
    """Render a str or a ``psycopg.sql.Composable`` to comparable text.

    ``as_string(None)`` is psycopg3's context-free rendering - enough to assert on
    the composed SQL without a live connection.
    """
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
def repo() -> KeywordRepo:
    return KeywordRepo(_CALLER)


# --------------------------------------------------------------------------- #
# 1. The RLS seam IS the tenant boundary.
# --------------------------------------------------------------------------- #
def test_every_read_binds_the_callers_verified_id_on_the_rls_seam(
    repo: KeywordRepo, seam: _Seam
) -> None:
    """Each read must go through ``rls_connection(<caller>)``. On the privileged seam
    the same SQL would bypass every ``0035`` policy and return the whole bank."""
    repo.list_keywords()
    repo.keyword_stats()
    repo.get_by_code("KW-00001")
    repo.list_clusters()
    repo.cannibalization_rows()
    repo.client_name_for("cl-1")

    assert seam.rls_ids == [_CALLER] * 6  # every call, same verified identity
    assert seam.privileged_opens == 0  # nothing leaked onto the BYPASSRLS seam


def test_every_mutation_stays_on_the_rls_seam(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Writes are RLS-scoped too: the 0035 insert/update policies (leads-only) are
    # what actually enforce the write boundary, and they only apply on this seam.
    cur.rows = [{"id": "kw-1"}]
    repo.add_keywords(
        client_id="cl-1", client_name="Acme", geo="us", keywords=["roofer"],
        created_by=_CALLER,
    )
    repo.update_keyword("KW-00001", {"target_url": "/x"})

    assert seam.privileged_opens == 0
    assert set(seam.rls_ids) == {_CALLER}


def test_the_repo_dependency_binds_the_identity_from_the_verified_user(
    seam: _Seam,
) -> None:
    """``get_keyword_repo`` must take the id off the server-verified ``CurrentUser``.

    This is the join between auth and RLS: bind anything client-supplied here and
    the whole boundary is impersonatable.
    """
    from app.core.auth import CurrentUser

    user = CurrentUser(
        id="00000000-0000-0000-0000-0000000000b2", email="op@aios.dev", role="manager",
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )
    built = get_keyword_repo(user)
    built.keyword_stats()
    assert seam.rls_ids == ["00000000-0000-0000-0000-0000000000b2"]


def test_repo_reads_are_not_client_scoped_in_sql_so_rls_decides(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An unfiltered read emits NO client predicate - visibility is Postgres's call.

    Staff see the whole bank (``is_staff()``); clients have no select policy at all.
    Hard-coding a client filter here would be a second, divergent boundary.
    """
    repo.list_keywords()
    assert "where" not in cur.last_query.lower()
    assert "client_id" not in cur.last_query


# --------------------------------------------------------------------------- #
# 2. Nullable-client bank rows.
# --------------------------------------------------------------------------- #
def test_null_client_bank_rows_are_returned_to_staff_untouched(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """A NULL-client "bank" row is a first-class row: the repo must not filter it out.

    ``is_staff()`` never references client_id, so Postgres shows these to staff and
    hides them from clients - the repo just passes them through.
    """
    cur.rows = [
        {"code": "KW-1", "client_id": None, "client_name": "", "keyword": "plumber"},
        {"code": "KW-2", "client_id": "cl-1", "client_name": "Acme", "keyword": "roofer"},
    ]
    rows = repo.list_keywords()
    assert [r["code"] for r in rows] == ["KW-1", "KW-2"]  # the bank row survives


def test_add_keywords_binds_a_null_client_rather_than_omitting_the_column(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An unassigned add must bind NULL positionally - not drop the column (which
    # would shift every subsequent value into the wrong slot).
    repo.add_keywords(
        client_id=None, client_name="", geo=None, keywords=["plumber"], created_by=_CALLER
    )
    assert cur.last_params == [None, "", None, "plumber", _CALLER]


def test_stats_coalesces_an_empty_bank_to_zero_not_null(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # avg() over zero rows is NULL in SQL; the coalesce keeps the tile honest.
    cur.rows = []
    assert repo.keyword_stats() == {"saved": 0, "clusters": 0, "avg_difficulty": 0}
    assert "coalesce(avg(difficulty), 0)" in cur.last_query


def test_stats_counts_distinct_clusters_ignoring_unclustered_rows(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.keyword_stats()
    query = cur.last_query
    assert "count(distinct cluster_id) filter (where cluster_id is not null)" in query


# --------------------------------------------------------------------------- #
# 3. SQL safety: values bound, identifiers quoted, nothing interpolated.
# --------------------------------------------------------------------------- #
_INJECTION = "'; drop table public.keywords; --"


@pytest.mark.parametrize(
    ("kwarg", "column"),
    [
        ("client_id", "k.client_id = %s"),
        ("cluster_id", "k.cluster_id = %s"),
        ("intent", "k.intent = %s"),
        ("geo", "k.geo = %s"),
        ("source", "k.source = %s"),
    ],
)
def test_every_list_filter_is_a_bound_param_never_interpolated(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam, kwarg: str, column: str
) -> None:
    """Drive an injection payload through each filter: the SQL must carry a ``%s``
    placeholder and the payload must appear ONLY in the params."""
    repo.list_keywords(**{kwarg: _INJECTION})
    query, params = cur.calls[-1]
    text = _as_text(query)
    assert column in text
    assert _INJECTION not in text  # never spliced into the statement
    assert _INJECTION in params  # ... it stays inert data


def test_boolean_and_pagination_filters_are_bound_too(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.list_keywords(winnable=True, limit=5, offset=10)
    assert "k.winnable = %s" in cur.last_query
    assert "limit %s offset %s" in cur.last_query
    assert cur.last_params == [True, 5, 10]


def test_omitted_filters_add_no_clause_at_all(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A None filter must not become "= NULL" (which matches nothing) nor a literal.
    repo.list_keywords(client_id=None, intent=None, winnable=None)
    assert "where" not in cur.last_query.lower()
    assert cur.last_params == []


def test_list_orders_by_opportunity_with_a_stable_tiebreak(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Best opportunities first; volume + code keep paging deterministic across ties
    # (an unstable sort would duplicate/skip rows between pages).
    repo.list_keywords()
    assert "order by k.opportunity desc, k.volume desc, k.code" in cur.last_query


def test_list_left_joins_the_cluster_name(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An inner join would silently DROP every unclustered keyword from the bank.
    repo.list_keywords()
    assert "left join public.keyword_clusters c on c.id = k.cluster_id" in cur.last_query


def test_update_quotes_column_identifiers_and_binds_values(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The UPDATE's column list is the only dynamic identifier in the module: it must
    be composed with ``sql.Identifier`` (double-quoted), never f-stringed."""
    cur.row_queue = [[{"id": "kw-1"}], [{"code": "KW-00001"}]]
    repo.update_keyword("KW-00001", {"target_url": "/x", "intent": "Local"})
    update_sql = cur.queries[0]
    assert '"target_url" = %s' in update_sql  # quoted identifier
    assert '"intent" = %s' in update_sql
    assert "/x" not in update_sql and "Local" not in update_sql  # values not spliced
    assert cur.calls[0][1] == ["/x", "Local", "KW-00001"]


def test_update_binds_the_code_rather_than_formatting_it(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The code comes straight off the URL path - the one caller-controlled string.
    cur.row_queue = [[{"id": "kw-1"}], [{"code": _INJECTION}]]
    repo.update_keyword(_INJECTION, {"target_url": "/x"})
    assert _INJECTION not in cur.queries[0]
    assert _INJECTION in cur.calls[0][1]


def test_update_of_an_invisible_row_returns_none_without_a_reread(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """RLS makes an unauthorised/unknown row simply invisible: the UPDATE matches 0
    rows and the repo reports ``None`` (the router turns that into a clean 404)."""
    cur.rows = []  # the `returning id` found nothing
    assert repo.update_keyword("KW-NOPE", {"target_url": "/x"}) is None
    assert len(cur.calls) == 1  # no pointless re-read


def test_update_with_no_changes_degrades_to_a_plain_read(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"code": "KW-00001"}]
    assert repo.update_keyword("KW-00001", {}) == {"code": "KW-00001"}
    assert len(cur.calls) == 1
    assert "update" not in cur.last_query.lower()  # never an empty SET clause


def test_update_rereads_through_the_join_so_the_cluster_name_is_fresh(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.row_queue = [[{"id": "kw-1"}], [{"code": "KW-00001", "cluster_name": "invisalign"}]]
    row = repo.update_keyword("KW-00001", {"cluster_id": "cu-9"})
    assert row is not None and row["cluster_name"] == "invisalign"
    assert "left join" in cur.queries[1]


def test_add_keywords_binds_every_row_and_defers_dedupe_to_the_unique_index(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Every add dedupes at the DB via ``on conflict do nothing``.

    The reach is exactly the router docstring's "Duplicates (client, keyword, geo)
    are skipped" - for BANK rows too, because 0035's unique index is ``nulls not
    distinct`` (pinned by ``test_bank_rows_dedupe_via_nulls_not_distinct_index``).
    """
    repo.add_keywords(
        client_id="cl-1", client_name="Acme", geo="us",
        keywords=["roof repair", "roofer"], created_by=_CALLER,
    )
    query, params = cur.calls[-1]
    text = _as_text(query)
    assert "on conflict (client_id, keyword, geo) do nothing" in text
    assert "roof repair" not in text  # values bound, not spliced
    assert params == [
        "cl-1", "Acme", "us", "roof repair", _CALLER,
        "cl-1", "Acme", "us", "roofer", _CALLER,
    ]


def test_bank_rows_dedupe_via_nulls_not_distinct_index(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An UNASSIGNED bank add (client_id NULL, geo NULL) still dedupes at the DB.

    ``add_keywords`` leans entirely on ``on conflict (client_id, keyword, geo) do
    nothing``, so the dedupe is only as good as the index it resolves against. Under
    DEFAULT SQL NULL semantics two NULLs are DISTINCT, which would mean the constraint
    never fires for a bank row (client_id NULL) or a geo-less row - re-adding the same
    bank keyword would silently insert a SECOND row, contradicting the router's
    "Duplicates (client, keyword, geo) are skipped".

    0035 therefore declares the index ``unique nulls not distinct`` (PG15+; we deploy
    PG16), making NULL = NULL for uniqueness so the conflict fires for bank rows too.
    This test pins BOTH halves - the repo's conflict clause and the index semantics it
    depends on - because either alone is silently insufficient.
    """
    repo.add_keywords(
        client_id=None, client_name="", geo=None, keywords=["plumber"], created_by=_CALLER
    )
    text = _as_text(cur.calls[-1][0])
    assert "on conflict (client_id, keyword, geo) do nothing" in text
    assert len(cur.calls) == 1  # one INSERT; the DB (not app code) resolves the dedupe

    # The other half of the contract: the index MUST be NULL-safe, or the clause above
    # is a no-op for every bank row.
    migration = (
        Path(__file__).resolve().parents[4] / "db" / "migrations" / "0035_keyword_research.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())
    assert "unique nulls not distinct (client_id, keyword, geo)" in normalized, (
        "0035 must declare the keywords unique index as `nulls not distinct`, else "
        "`on conflict (client_id, keyword, geo)` never fires for NULL-client bank rows"
    )


def test_add_keywords_trims_and_drops_blanks_before_touching_the_db(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.add_keywords(
        client_id=None, client_name="", geo=None,
        keywords=["  plumber  ", "", "   "], created_by=_CALLER,
    )
    assert cur.last_params == [None, "", None, "plumber", _CALLER]


def test_add_keywords_with_nothing_usable_never_opens_a_connection(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An all-blank batch must be a no-op, not an INSERT with an empty VALUES list.
    assert repo.add_keywords(
        client_id=None, client_name="", geo=None, keywords=["", "   "], created_by=_CALLER
    ) == []
    assert cur.calls == [] and seam.rls_ids == []


def test_cannibalization_rows_preselect_only_actionable_rows(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A keyword with no landing URL or no intent cannot cannibalise anything; the
    # filter belongs in SQL so the service never folds dead rows.
    repo.cannibalization_rows(client_id="cl-1")
    assert "target_url <> ''" in cur.last_query
    assert "intent is not null" in cur.last_query
    assert "and client_id = %s" in cur.last_query
    assert cur.last_params == ["cl-1"]


def test_client_name_for_returns_none_when_rls_hides_the_client(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An invisible client is indistinguishable from a missing one - the router turns
    both into 404, so a caller cannot probe for the existence of another tenant."""
    cur.rows = []
    assert repo.client_name_for("cl-someone-elses") is None
    assert cur.last_params == ("cl-someone-elses",)


def test_client_name_for_returns_the_display_snapshot(
    repo: KeywordRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"name": "NorthPeak Dental"}]
    assert repo.client_name_for("cl-1") == "NorthPeak Dental"


# --------------------------------------------------------------------------- #
# 4. The privileged worker store (BYPASSRLS) - idempotent by construction.
# --------------------------------------------------------------------------- #
def test_service_store_uses_the_privileged_seam_only(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The research worker holds no user JWT, so its ingest MUST run on
    ``privileged_connection`` (service_role). It must never open an RLS connection -
    there is no identity to bind."""
    # Row per statement: the client lookup reads `name`, the cluster lookup reads `id`.
    cur.row_queue = [[{"name": "Acme"}], [{"id": "cu-1"}], [{"id": "cu-1"}]]
    store = ServiceKeywordStore()
    store.get_client_name("cl-1")
    store.upsert_cluster(
        client_id=None, client_name="", name="plumber", pillar_keyword="plumber",
        dominant_intent="Commercial", size=1, total_volume=10, avg_difficulty=5.0,
    )
    assert seam.rls_ids == []
    assert seam.privileged_opens >= 2


def test_upsert_cluster_updates_in_place_when_it_already_exists(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The idempotency that makes a redelivery safe: an existing cluster is REFRESHED,
    never duplicated."""
    cur.rows = [{"id": "cu-1"}]  # the lookup finds it
    cluster_id = ServiceKeywordStore().upsert_cluster(
        client_id="cl-1", client_name="Acme", name="plumber", pillar_keyword="plumber",
        dominant_intent="Commercial", size=3, total_volume=900, avg_difficulty=42.0,
    )
    assert cluster_id == "cu-1"
    assert "update public.keyword_clusters" in cur.last_query
    assert "insert" not in cur.last_query.lower()


def test_upsert_cluster_inserts_when_absent(cur: _FakeCursor, seam: _Seam) -> None:
    cur.row_queue = [[], [{"id": "cu-new"}]]  # lookup misses, insert returns
    assert ServiceKeywordStore().upsert_cluster(
        client_id=None, client_name="", name="plumber", pillar_keyword="plumber",
        dominant_intent=None, size=1, total_volume=10, avg_difficulty=5.0,
    ) == "cu-new"
    assert "insert into public.keyword_clusters" in cur.queries[1]


def test_cluster_lookup_is_null_safe_for_a_bank_cluster(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """``client_id = NULL`` is never true in SQL, so a plain ``=`` would MISS every
    unassigned cluster and insert a duplicate on every run. ``is not distinct from``
    is what makes the bank path idempotent."""
    cur.row_queue = [[], [{"id": "cu-new"}]]
    ServiceKeywordStore().upsert_cluster(
        client_id=None, client_name="", name="plumber", pillar_keyword="plumber",
        dominant_intent=None, size=1, total_volume=1, avg_difficulty=1.0,
    )
    lookup = cur.queries[0]
    assert "client_id is not distinct from %s" in lookup
    assert cur.calls[0][1] == ("plumber", None)


def test_upsert_keyword_reports_insert_vs_refresh(cur: _FakeCursor, seam: _Seam) -> None:
    """The return value is the worker's "saved" counter: True only for a NEW row, so a
    re-run reports 0 new saves rather than inflating the count."""
    store = ServiceKeywordStore()
    kwargs: dict[str, Any] = {
        "client_id": None, "client_name": "", "keyword": "plumber", "geo": None,
        "volume": 100, "difficulty": 40.0, "cpc": 2.0, "competition": 0.5,
        "intent": "Commercial", "intent_source": "provider", "intent_confidence": 0.9,
        "cluster_id": "cu-1", "opportunity": 60.0, "winnable": True,
        "source": "research", "metrics_confidence": "high", "provider": "fake",
        "fetched_at": None,
    }
    cur.rows = [{"id": "kw-1"}]  # already banked
    assert store.upsert_keyword(**kwargs) is False
    assert "update public.keywords" in cur.last_query

    cur.calls.clear()
    cur.row_queue = [[], []]  # not banked yet
    assert store.upsert_keyword(**kwargs) is True
    assert "insert into public.keywords" in cur.queries[1]


def test_keyword_lookup_is_null_safe_on_both_client_and_geo(
    cur: _FakeCursor, seam: _Seam
) -> None:
    # The (client, keyword, geo) key is nullable on TWO columns; a plain `=` on
    # either would re-insert the same bank keyword on every research run.
    cur.row_queue = [[], []]
    ServiceKeywordStore().upsert_keyword(
        client_id=None, client_name="", keyword="plumber", geo=None, volume=1,
        difficulty=1.0, cpc=0.0, competition=0.0, intent=None, intent_source=None,
        intent_confidence=0.0, cluster_id=None, opportunity=0.0, winnable=None,
        source="research", metrics_confidence="high", provider="fake", fetched_at=None,
    )
    lookup = cur.queries[0]
    assert "client_id is not distinct from %s" in lookup
    assert "geo is not distinct from %s" in lookup
    assert cur.calls[0][1] == ("plumber", None, None)


def test_service_store_binds_every_value(cur: _FakeCursor, seam: _Seam) -> None:
    # The worker's payload is provider-derived text - it must be bound like any
    # other untrusted value.
    cur.row_queue = [[], []]
    ServiceKeywordStore().upsert_keyword(
        client_id=None, client_name="", keyword=_INJECTION, geo=None, volume=1,
        difficulty=1.0, cpc=0.0, competition=0.0, intent=None, intent_source=None,
        intent_confidence=0.0, cluster_id=None, opportunity=0.0, winnable=None,
        source="research", metrics_confidence="high", provider="fake", fetched_at=None,
    )
    for query, params in cur.calls:
        assert _INJECTION not in _as_text(query)
        assert params is not None and _INJECTION in params


def test_service_store_factory_is_stateless(seam: _Seam) -> None:
    # Each method opens its own connection, so instances hold no handle and are
    # safe to build per call from the task.
    assert isinstance(service_keyword_store(), ServiceKeywordStore)
    assert service_keyword_store() is not service_keyword_store()
