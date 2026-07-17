"""Competitor-intel data access: the RLS seam, the SQL shape, and the reuse rules.

No DB: ``rls_connection`` / ``privileged_connection`` are swapped for a recording fake
cursor, so these tests assert WHICH seam each method opens and WHAT SQL it sends -
which is exactly the pair a live-DB integration test cannot check cheaply and a mocked
repo would never catch.

Two mandates are pinned here:

* the impersonation-review SQL rule - every VALUE is a bound param, never
  string-formatted into the statement;
* the Phase 2C reuse rules - the client's positions come from the Rank Tracker's
  ``tracked_keywords``, and the backlink gap reads the EXISTING 0018 ledger with ZERO
  provider involvement.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import app.modules.competitor_intel.repo as repo_mod
from app.modules.competitor_intel.repo import CompetitorRepo, ServiceCompetitorStore

pytestmark = pytest.mark.unit


class FakeCursor:
    """Records every (sql, params) pair and serves canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._rows = rows if rows is not None else []
        self.rowcount = len(self._rows)

    def execute(self, sql: Any, params: Any = None) -> None:
        self.calls.append((str(sql), params))

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    @property
    def sql(self) -> str:
        return self.calls[-1][0]

    @property
    def params(self) -> Any:
        return self.calls[-1][1]


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Swap BOTH DB seams for a recorder; report which one was opened."""
    state: dict[str, Any] = {"opened": [], "cursor": FakeCursor()}

    @contextmanager
    def _rls(user_id: str) -> Any:
        state["opened"].append(("rls", user_id))
        yield state["cursor"]

    @contextmanager
    def _privileged() -> Any:
        state["opened"].append(("privileged", None))
        yield state["cursor"]

    monkeypatch.setattr(repo_mod, "rls_connection", _rls)
    monkeypatch.setattr(repo_mod, "privileged_connection", _privileged)
    return state


def _rows(seams: dict[str, Any], rows: list[dict[str, Any]]) -> FakeCursor:
    cursor = FakeCursor(rows)
    seams["cursor"] = cursor
    return cursor


# --------------------------------------------------------------------------- #
# 1. The RLS seam.
# --------------------------------------------------------------------------- #
def test_every_repo_read_opens_the_rls_seam_on_the_callers_id(seams: dict[str, Any]) -> None:
    """Tenant scoping is Postgres's job, not the repo's - so every read must arrive on
    the caller's own RLS identity rather than on the privileged connection."""
    repo = CompetitorRepo("user-42")
    repo.list_competitors()
    repo.competitor_stats()
    repo.get_by_code("CI-0001")
    repo.list_gaps("c-1")
    repo.client_positions("cl-1")
    repo.backlink_gaps("cl-1", limit=10)
    assert seams["opened"] == [("rls", "user-42")] * 6


def test_the_worker_store_uses_the_privileged_seam(seams: dict[str, Any]) -> None:
    """The analysis worker holds no user JWT, so it writes on service_role (BYPASSRLS)."""
    store = ServiceCompetitorStore()
    store.get_competitor("c-1")
    store.client_positions("cl-1")
    store.existing_domains("cl-1")
    assert [s for s, _ in seams["opened"]] == ["privileged"] * 3


# --------------------------------------------------------------------------- #
# 2. The SQL rule: values are BOUND, never formatted.
# --------------------------------------------------------------------------- #
def test_filters_are_bound_params_never_string_formatted(seams: dict[str, Any]) -> None:
    """The impersonation-review mandate. A formatted value is an injection; a bound one
    cannot be. The literal must NOT appear in the statement text."""
    repo = CompetitorRepo("u-1")
    evil = "'; drop table public.competitors; --"
    repo.list_competitors(client_id=evil, source="manual", tracked=True, limit=10, offset=5)

    cursor: FakeCursor = seams["cursor"]
    assert evil not in cursor.sql
    assert "drop table" not in cursor.sql.lower()
    assert cursor.sql.count("%s") == 5
    assert cursor.params == [evil, "manual", True, 10, 5]


def test_the_gap_filter_and_promote_bind_their_values(seams: dict[str, Any]) -> None:
    repo = CompetitorRepo("u-1")
    repo.list_gaps("c-1", gap_type="missing", limit=20, offset=0)
    cursor: FakeCursor = seams["cursor"]
    assert cursor.params == ["c-1", "missing", 20, 0]
    assert "c-1" not in cursor.sql


def test_update_uses_quoted_identifiers_with_bound_values(seams: dict[str, Any]) -> None:
    """Column NAMES are static ``sql.Identifier``s (they cannot be bound); every VALUE
    is still a param.

    The statement is a ``psycopg.sql.Composed``, so it is asserted on its COMPOSITION
    rather than on rendered text: an ``Identifier`` is quoted by psycopg at render time,
    which is the property that makes a server-built column list safe. A raw f-string
    would appear here as bare SQL and fail.
    """
    _rows(seams, [{"code": "CI-0001"}])
    repo = CompetitorRepo("u-1")
    repo.update_competitor("CI-0001", {"label": "evil'; --", "tracked": False})
    cursor: FakeCursor = seams["cursor"]
    assert "Identifier('label')" in cursor.sql
    assert "Identifier('tracked')" in cursor.sql
    # The VALUE never reaches the statement - it rides in the params.
    assert "evil" not in cursor.sql
    assert cursor.params == ["evil'; --", False, "CI-0001"]


def test_an_empty_update_is_a_read_not_a_broken_statement(seams: dict[str, Any]) -> None:
    _rows(seams, [{"code": "CI-0001"}])
    repo = CompetitorRepo("u-1")
    repo.update_competitor("CI-0001", {})
    assert "update" not in seams["cursor"].sql.lower()


# --------------------------------------------------------------------------- #
# 3. Phase 2C's reuse: the client's positions are FREE from the Rank Tracker.
# --------------------------------------------------------------------------- #
def test_client_positions_read_the_rank_trackers_table(seams: dict[str, Any]) -> None:
    """The whole premise of the phase: ``tracked_keywords.latest_position`` is a fact
    the client already pays for nightly (0036), so a gap's client_position is free."""
    _rows(seams, [{"keyword": "Dental Implants", "latest_position": 3}])
    positions = CompetitorRepo("u-1").client_positions("cl-1")
    cursor: FakeCursor = seams["cursor"]
    assert "public.tracked_keywords" in cursor.sql
    assert "latest_position" in cursor.sql
    assert cursor.params == ("cl-1",)
    # Keys are folded so the provider's casing still matches (the vendors disagree).
    assert positions == {"dental implants": 3}


def test_client_positions_preserve_a_null_rather_than_coalescing_it(
    seams: dict[str, Any],
) -> None:
    """0036's ``latest_position`` NULL means "checked, not in the top-N". That meaning
    must survive the read: a ``coalesce(..., 0)`` here would silently turn every
    unranked keyword into a position-0 "win"."""
    _rows(seams, [{"keyword": "unranked", "latest_position": None}])
    assert CompetitorRepo("u-1").client_positions("cl-1") == {"unranked": None}
    assert "coalesce" not in seams["cursor"].sql.lower()


def test_only_active_subscriptions_count_as_the_clients_book(seams: dict[str, Any]) -> None:
    """A paused subscription is not being checked, so its position is stale and must
    not be presented as the client's current standing."""
    CompetitorRepo("u-1").client_positions("cl-1")
    assert "status = 'active'" in seams["cursor"].sql


def test_discovery_sample_is_bounded_and_volume_ordered(seams: dict[str, Any]) -> None:
    """Every sampled keyword costs a PAID SERP, so the sample is capped and takes the
    terms that best describe who the client competes with."""
    CompetitorRepo("u-1").tracked_keywords_sample("cl-1", limit=10)
    cursor: FakeCursor = seams["cursor"]
    assert "order by search_volume desc" in cursor.sql
    assert "limit %s" in cursor.sql
    assert cursor.params == ("cl-1", 10)


# --------------------------------------------------------------------------- #
# 4. The backlink gap: the EXISTING 0018 ledger, ZERO provider cost.
# --------------------------------------------------------------------------- #
def test_the_backlink_gap_reads_the_existing_0018_ledger(seams: dict[str, Any]) -> None:
    """It reuses ``public.backlinks`` (0018) - no new backlink table - joined to this
    client's competitors through the ``competitor_id`` dimension 0037 added."""
    CompetitorRepo("u-1").backlink_gaps("cl-1", limit=25)
    sql = seams["cursor"].sql
    assert "public.backlinks" in sql
    assert "public.competitors" in sql
    assert "b.ref_domain" in sql
    # Ranked by how many of the client's rivals each domain links to.
    assert "count(distinct b.competitor_id)" in sql
    assert "order by competitors desc" in sql
    assert seams["cursor"].params == ("cl-1", "cl-1", 25)


def test_the_backlink_gap_excludes_links_the_client_already_has(
    seams: dict[str, Any],
) -> None:
    """A "gap" the client already holds is not a gap. The client's OWN rows are the
    ones with a NULL competitor_id (every pre-0037 row), scoped to this client."""
    CompetitorRepo("u-1").backlink_gaps("cl-1", limit=25)
    sql = seams["cursor"].sql
    assert "not exists" in sql
    assert "own.competitor_id is null" in sql


def test_the_backlink_gap_makes_no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZERO new provider cost - it is a pure ledger read.

    Proven by DETONATING both provider seams: if the read ever grows a live pull, the
    factory raises and this test names it. A mere "assert no HTTP" would not notice a
    call routed through a different client.
    """
    import app.modules.competitor_intel.provider as prov

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("the backlink gap must make NO provider call")

    monkeypatch.setattr(prov, "serp_source_from_settings", _boom)
    monkeypatch.setattr(prov, "keyword_source_from_settings", _boom)
    monkeypatch.setattr(
        "integrations.keyword_data.keyword_data_provider_from_settings", _boom
    )
    monkeypatch.setattr("integrations.content_research.SerperResearcher", _boom)

    calls: list[Any] = []

    @contextmanager
    def _rls(user_id: str) -> Any:
        calls.append(user_id)
        yield FakeCursor([{"ref_domain": "dir.com", "competitors": 3, "authority": 61, "spam": 2}])

    monkeypatch.setattr(repo_mod, "rls_connection", _rls)
    rows = CompetitorRepo("u-1").backlink_gaps("cl-1", limit=25)
    assert rows == [{"ref_domain": "dir.com", "competitors": 3, "authority": 61, "spam": 2}]
    assert calls == ["u-1"]  # one RLS read, nothing else


# --------------------------------------------------------------------------- #
# 5. Promote: into the 0035 bank, idempotently.
# --------------------------------------------------------------------------- #
def test_promote_writes_into_the_0035_bank_with_source_gap(seams: dict[str, Any]) -> None:
    cursor = _rows(
        seams,
        [{"keyword": "dental implants", "intent": "Commercial", "volume": 8100,
          "difficulty": 42.0, "opportunity": 71.5, "id": "kw-1", "code": "KW-00001"}],
    )
    result = CompetitorRepo("u-1").promote_gap(
        "g-1", client_id="cl-1", client_name="NorthPeak"
    )
    assert result == ("dental implants", "KW-00001", True)
    inserts = [c for c, _ in cursor.calls if "insert into public.keywords" in c]
    assert len(inserts) == 1
    assert "'gap'" in inserts[0]  # the bank's source column
    # Idempotent: the bank's own (client, keyword, geo) key absorbs a re-promote.
    assert "on conflict (client_id, keyword, geo) do nothing" in inserts[0]
    # ... and the gap is stamped so a second attempt is a visible no-op.
    assert any("update public.keyword_gaps set keyword_id" in c for c, _ in cursor.calls)


def test_promoting_an_unknown_gap_returns_none(seams: dict[str, Any]) -> None:
    _rows(seams, [])
    assert CompetitorRepo("u-1").promote_gap("nope", client_id="cl-1", client_name="N") is None


# --------------------------------------------------------------------------- #
# 6. The board's stats.
# --------------------------------------------------------------------------- #
def test_the_stats_tile_counts_only_tracked_rivals(seams: dict[str, Any]) -> None:
    """A parked competitor is not being tracked; counting it would contradict the
    board's own filter."""
    CompetitorRepo("u-1").competitor_stats()
    sql = seams["cursor"].sql
    assert "count(*) filter (where tracked)" in sql


def test_the_clients_share_of_voice_is_floored_at_zero(seams: dict[str, Any]) -> None:
    """The per-competitor shares are rolled forward by INDEPENDENT analyses that can
    transiently sum past 100. A negative share of voice is not a fact - it is a
    stale-data artefact - so the remainder is floored."""
    CompetitorRepo("u-1").competitor_stats()
    assert "greatest(0, 100 - " in seams["cursor"].sql


def test_add_competitor_refuses_a_duplicate_rather_than_double_analysing(
    seams: dict[str, Any],
) -> None:
    """A duplicate competitor is a duplicate PAID analysis."""
    _rows(seams, [])
    result = CompetitorRepo("u-1").add_competitor(
        client_id="cl-1", client_name="N", domain="rival.com", label="", source="manual",
        created_by="u-1",
    )
    assert result is None  # on-conflict-do-nothing returned no row
    assert "on conflict (client_id, domain) do nothing" in seams["cursor"].sql
