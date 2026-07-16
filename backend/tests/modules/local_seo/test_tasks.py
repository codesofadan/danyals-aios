"""Local-SEO workers: the error-vs-absence contract, never-re-raise, gate-first.

NO DB, NO network, NO broker: the store is in-memory, the cost gate runs on a fake
``CostStore``, and the provider is the sha256-seeded fake (or a deliberately failing
stub). The Celery tasks are invoked as plain functions - ``.delay`` is never called.

**THE MOST IMPORTANT TEST IN THIS MODULE** is
``test_a_provider_error_writes_nothing_and_never_fabricates_a_null_rank``.

In this schema ``rank IS NULL`` means "checked successfully, NOT in the local pack" -
a real, chartable observation. A provider ERROR means "we do not know". If a failed
check were persisted as NULL, the two become indistinguishable: an API timeout would
render on the client's monthly report as the business DROPPING OUT of the map pack,
and the appended history point would make the fabricated loss permanent. So a failure
must write NOTHING - no rank, no history row - and the last known good rank stands.

The other properties pinned here are the ones that cost real money when they break
(cf. ``workers.tasks.audit`` / ``keyword_research.tasks``, and invariant #8):

* Never re-raise (``task_acks_late`` would redeliver -> a second PAID check).
* The R5 cost pre-check runs BEFORE the provider call, billed to the ROW's client.
* The R6 beat-overlap lock stops a slow tick from double-spending.
* ``sync_gbp_profile`` HOLDS (never crashes) with no key / no token - the EXPECTED
  state, since the GBP API is approval-gated.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.local_seo import tasks as wk
from app.modules.local_seo.provider import FakeLocalPackProvider, LocalRankResult
from app.modules.local_seo.tasks import (
    check_one_ranking,
    execute_gbp_sync,
    execute_refresh,
    refresh_local_ranks,
    sync_gbp_profile,
)
from app.services.cost_gate import CostGate, DialMode, GateContext

pytestmark = pytest.mark.unit

_CLIENT = "cl-1"
_PROFILE = "gp-1"


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeLocalStore:
    """In-memory stand-in for the privileged ServiceLocalStore.

    ``checks`` records every ``record_check`` call and ``history`` every appended
    point, so "did a failed check write anything?" is answerable by counting them.
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else [_row()]
        self.profiles: dict[str, dict[str, Any]] = {_PROFILE: _profile()}
        self.checks: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.profile_syncs: list[dict[str, Any]] = []
        self.claimed_with: list[int] = []

    def claim_due_rankings(self, limit: int) -> list[dict[str, Any]]:
        self.claimed_with.append(limit)
        return list(self.rows)

    def profile_for_ranking(self, profile_id: str) -> dict[str, Any] | None:
        return self.profiles.get(profile_id)

    def record_check(self, ranking_id: str, **kw: Any) -> None:
        self.checks.append({"ranking_id": ranking_id, **kw})
        self.history.append({"ranking_id": ranking_id, "rank": kw["rank"]})

    def update_profile_sync(self, profile_id: str, **kw: Any) -> None:
        self.profile_syncs.append({"profile_id": profile_id, **kw})


class FakeCostStore:
    """Minimal CostStore: a settable dial + a recorder for what was actually spent."""

    def __init__(self, *, mode: DialMode = "api", halted: bool = False) -> None:
        self._mode = mode
        self._halted = halted
        self.recorded: list[tuple[str, str | None, float]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 100.0

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx.feature_key, ctx.client_id, cost))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class ErrorProvider:
    """A provider whose check FAILS - the "Serper is down" case.

    Returns an error-bearing result (the Protocol's contract) rather than raising.
    """

    provider = "serper_places"
    enabled = True

    def estimated_cost(self) -> float:
        return 0.003

    def rank(self, **kw: Any) -> LocalRankResult:
        return LocalRankResult(provider=self.provider, error="TimeoutException")


class ExplodingProvider:
    """A provider that RAISES instead of returning an error result - the same
    contract must hold (a failure is a failure however it arrives)."""

    provider = "exploding"
    enabled = True

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RuntimeError("serper 500")

    def estimated_cost(self) -> float:
        return 0.003

    def rank(self, **kw: Any) -> LocalRankResult:
        raise self._exc


class StubProvider:
    """Returns a canned result, logging the ORDER of its calls."""

    provider = "stub"
    enabled = True

    def __init__(self, result: LocalRankResult, log: list[str] | None = None) -> None:
        self._result = result
        self._log = log if log is not None else []
        self.calls: list[dict[str, Any]] = []

    def estimated_cost(self) -> float:
        return 0.003

    def rank(self, **kw: Any) -> LocalRankResult:
        self._log.append("provider.rank")
        self.calls.append(kw)
        return self._result


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "rk-1", "client_id": _CLIENT, "client_name": "Verde Cafe",
        "profile_id": _PROFILE, "keyword": "cafe near me", "geo": "Karachi, PK",
        "rank": 4,
    }
    row.update(over)
    return row


def _profile(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _PROFILE, "client_id": _CLIENT, "client_name": "Verde Cafe",
        "location_label": "Karachi", "place_id": "ChIJ-place", "nap_name": "Verde Cafe",
    }
    row.update(over)
    return row


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(store: FakeCostStore) -> CostGate:
    return CostGate(store, _NullCache())


def _check(
    *,
    store: FakeLocalStore | None = None,
    provider: Any = None,
    cost: FakeCostStore | None = None,
    row: dict[str, Any] | None = None,
) -> str:
    return check_one_ranking(
        store or FakeLocalStore(),  # type: ignore[arg-type]
        provider or FakeLocalPackProvider(),
        _gate(cost or FakeCostStore()),
        _settings(),
        row or _row(),
    )


# --------------------------------------------------------------------------- #
# 1. THE CRITICAL CONTRACT: an ERROR is not an ABSENCE.
# --------------------------------------------------------------------------- #
def test_a_provider_error_writes_nothing_and_never_fabricates_a_null_rank() -> None:
    """THE most important test in this module.

    ``rank=NULL`` means "checked, not in the local pack". A FAILED check does not know
    the rank. Persisting the failure as NULL would make an API timeout render as the
    business dropping out of the map pack on their monthly report - and the appended
    history point would make that fabricated loss permanent.
    """
    store = FakeLocalStore()
    outcome = _check(store=store, provider=ErrorProvider())

    assert outcome == "error"
    assert store.checks == [], "a FAILED check must not write the current row"
    assert store.history == [], "a FAILED check must not append a history point"


def test_a_raising_provider_is_also_an_error_and_writes_nothing() -> None:
    # The contract holds however the failure arrives - result-flag or exception.
    store = FakeLocalStore()
    assert _check(store=store, provider=ExplodingProvider()) == "error"
    assert store.checks == [] and store.history == []


@pytest.mark.parametrize(
    "exc", [RuntimeError("boom"), ValueError("bad json"), TimeoutError("slow"), KeyError("k")]
)
def test_any_provider_exception_type_is_absorbed_without_a_write(exc: Exception) -> None:
    # A bare `except Exception` is only as good as its breadth - prove it.
    store = FakeLocalStore()
    assert _check(store=store, provider=ExplodingProvider(exc)) == "error"
    assert store.checks == []


def test_a_failed_check_is_never_charged() -> None:
    """The commit sits AFTER the check, so a provider failure costs $0 - the client is
    not billed for a check that returned nothing."""
    cost = FakeCostStore()
    _check(cost=cost, provider=ErrorProvider())
    assert cost.recorded == []


def test_a_failed_check_leaves_the_last_known_good_rank_standing() -> None:
    """The row already holds rank=4. A failure must not touch it - the board keeps
    showing the last VERIFIED position rather than a hole."""
    store = FakeLocalStore()
    _check(store=store, provider=ErrorProvider(), row=_row(rank=4))
    assert store.checks == []  # nothing overwrote the stored 4


def test_a_successful_not_found_check_is_written_as_a_null_rank() -> None:
    """The other half of the contract - and the reason the distinction matters.

    A SUCCESSFUL check that did not find the business is real information ("you are
    not in the pack"): it must be recorded, as NULL, with a history point. If this
    were dropped too, a genuine drop-out would be invisible.
    """
    store = FakeLocalStore()
    result = LocalRankResult(rank=None, in_map_pack=False, provider="stub",
                             top_competitors=["A", "B"])
    outcome = _check(store=store, provider=StubProvider(result), row=_row(rank=2))

    assert outcome == "unranked"
    assert len(store.checks) == 1
    check = store.checks[0]
    assert check["rank"] is None  # the honest absence IS persisted
    assert check["in_map_pack"] is False
    assert check["previous_rank"] == 2  # ... and the fall from #2 is preserved
    assert len(store.history) == 1 and store.history[0]["rank"] is None


def test_the_error_and_absence_paths_are_provably_different() -> None:
    """Pin the DISTINCTION itself: same store, same row - one writes, one does not."""
    absent_store = FakeLocalStore()
    _check(
        store=absent_store,
        provider=StubProvider(LocalRankResult(rank=None, provider="stub")),
    )
    error_store = FakeLocalStore()
    _check(store=error_store, provider=ErrorProvider())

    assert len(absent_store.checks) == 1 and absent_store.checks[0]["rank"] is None
    assert error_store.checks == []


# --------------------------------------------------------------------------- #
# 2. The happy path.
# --------------------------------------------------------------------------- #
def test_a_ranked_check_records_the_position_and_its_movement() -> None:
    store = FakeLocalStore()
    result = LocalRankResult(
        rank=2, in_map_pack=True, found_url="https://verde.example",
        top_competitors=["Bean There", "Verde Cafe"], provider="serper_places",
    )
    outcome = _check(store=store, provider=StubProvider(result), row=_row(rank=4))

    assert outcome == "ranked"
    check = store.checks[0]
    assert check["rank"] == 2
    assert check["previous_rank"] == 4
    assert check["rank_change"] == 2  # 4 -> 2 is a GAIN of 2 (inverted scale)
    assert check["in_map_pack"] is True
    assert check["top_competitors"] == ["Bean There", "Verde Cafe"]
    assert check["provider"] == "serper_places"


def test_a_first_ever_check_reports_no_movement() -> None:
    store = FakeLocalStore()
    _check(store=store, provider=StubProvider(LocalRankResult(rank=3, provider="s")),
           row=_row(rank=None))
    assert store.checks[0]["previous_rank"] is None
    assert store.checks[0]["rank_change"] == 0  # no honest magnitude to report


def test_the_provider_is_asked_about_the_profiles_own_listing() -> None:
    """The business identity comes from the PROFILE's NAP name + place id, not from
    the client's billing name (which may legitimately differ)."""
    provider = StubProvider(LocalRankResult(rank=1, provider="stub"))
    _check(provider=provider, row=_row())
    call = provider.calls[0]
    assert call["keyword"] == "cafe near me"
    assert call["geo"] == "Karachi, PK"
    assert call["place_id"] == "ChIJ-place"
    assert call["business_name"] == "Verde Cafe"


def test_a_profile_without_a_place_id_matches_by_name_alone() -> None:
    store = FakeLocalStore()
    store.profiles[_PROFILE] = _profile(place_id=None)
    provider = StubProvider(LocalRankResult(rank=1, provider="stub"))
    _check(store=store, provider=provider)
    assert provider.calls[0]["place_id"] is None
    assert provider.calls[0]["business_name"] == "Verde Cafe"


def test_a_ranking_whose_profile_vanished_is_skipped_not_guessed() -> None:
    """Never guess a business identity: without a profile there is nothing to match
    in the pack, so the row is skipped and nothing is written or spent."""
    store = FakeLocalStore()
    store.profiles.clear()
    cost = FakeCostStore()
    assert _check(store=store, cost=cost, provider=ExplodingProvider()) == "skipped"
    assert store.checks == [] and cost.recorded == []


# --------------------------------------------------------------------------- #
# 3. R5 - the cost pre-check, billed to the ROW's client.
# --------------------------------------------------------------------------- #
def test_the_cost_gate_is_consulted_before_the_provider_is_touched() -> None:
    """The ORDERING is the whole point of a pre-check: gate-then-check spends nothing
    on a blocked row; check-then-gate has already spent it."""
    log: list[str] = []

    class _LoggingStore(FakeCostStore):
        def dial_mode(self, feature_key: str) -> DialMode:
            log.append("gate.dial_mode")
            return "api"

        def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
            log.append("gate.record_cost")
            super().record_cost(ctx, cost, cached=cached)

    _check(cost=_LoggingStore(), provider=StubProvider(LocalRankResult(rank=1), log))
    assert log[0] == "gate.dial_mode"  # the gate decides first...
    assert log[1] == "provider.rank"  # ...then the paid check happens...
    assert log[-1] == "gate.record_cost"  # ...and the spend is committed after.


def test_the_check_is_billed_to_the_rows_client() -> None:
    """A client's own tracking spend must count against THEIR monthly cap, not a house
    account - otherwise one client's keywords can exhaust everyone's budget."""
    cost = FakeCostStore()
    _check(cost=cost, provider=StubProvider(LocalRankResult(rank=1)))
    feature, client_id, _amount = cost.recorded[0]
    assert client_id == _CLIENT
    assert feature == "local_rank"  # its OWN dial, throttled independently


def test_an_allowed_check_commits_exactly_the_providers_estimate() -> None:
    cost = FakeCostStore()
    provider = StubProvider(LocalRankResult(rank=1))
    _check(cost=cost, provider=provider)
    assert cost.recorded == [("local_rank", _CLIENT, provider.estimated_cost())]


@pytest.mark.parametrize(
    ("cost_store", "_reason"),
    [
        (FakeCostStore(mode="off"), "skip"),
        (FakeCostStore(mode="byhand"), "manual"),
        (FakeCostStore(halted=True), "blocked_daily"),
    ],
)
def test_a_blocked_dial_degrades_with_zero_spend_and_no_write(
    cost_store: FakeCostStore, _reason: str
) -> None:
    """A block DEGRADES: no exception, no provider call, provably no money recorded,
    and - critically - NO row written (a block is not an absence either)."""
    store = FakeLocalStore()
    outcome = _check(store=store, cost=cost_store, provider=ExplodingProvider())

    assert outcome == "blocked"
    assert cost_store.recorded == []  # nothing was charged
    assert store.checks == [] and store.history == []  # nothing was written
    # The provider would have raised if it had been called at all - it was not.


# --------------------------------------------------------------------------- #
# 4. The sweep.
# --------------------------------------------------------------------------- #
def _refresh(
    store: FakeLocalStore, provider: Any = None, cost: FakeCostStore | None = None
) -> dict[str, Any]:
    return execute_refresh(
        store,  # type: ignore[arg-type]
        provider or FakeLocalPackProvider(),
        _gate(cost or FakeCostStore()),
        _settings(),
        batch=10,
    )


def test_the_sweep_claims_a_bounded_batch_and_counts_every_outcome() -> None:
    store = FakeLocalStore(rows=[_row(id=f"rk-{i}") for i in range(3)])
    result = _refresh(store, StubProvider(LocalRankResult(rank=2, in_map_pack=True)))
    assert result["state"] == "ok"
    assert result["claimed"] == 3 and result["ranked"] == 3
    assert store.claimed_with == [10]


def test_the_sweep_counts_ranked_and_unranked_separately() -> None:
    store = FakeLocalStore(rows=[_row()])
    assert _refresh(store, StubProvider(LocalRankResult(rank=None)))["unranked"] == 1
    store2 = FakeLocalStore(rows=[_row()])
    assert _refresh(store2, StubProvider(LocalRankResult(rank=1)))["ranked"] == 1


def test_one_bad_row_never_abandons_the_rest_of_the_batch() -> None:
    """A row's failure is isolated: a bad keyword or a mid-batch blip must not lose
    the rows behind it (they would wait a whole beat interval for another chance)."""
    store = FakeLocalStore(rows=[_row(id=f"rk-{i}") for i in range(3)])

    calls: list[int] = []

    class _FlakyProvider(StubProvider):
        def rank(self, **kw: Any) -> LocalRankResult:
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("transient")
            return LocalRankResult(rank=1, provider="flaky")

    result = _refresh(store, _FlakyProvider(LocalRankResult(rank=1)))
    assert result["claimed"] == 3
    assert result["ranked"] == 2 and result["error"] == 1  # the sweep carried on
    assert len(store.checks) == 2


def test_a_store_failure_on_one_row_is_absorbed_by_the_sweep() -> None:
    class _BrokenStore(FakeLocalStore):
        def record_check(self, ranking_id: str, **kw: Any) -> None:
            raise RuntimeError("connection reset")

    store = _BrokenStore(rows=[_row()])
    result = _refresh(store, StubProvider(LocalRankResult(rank=1)))
    assert result["state"] == "ok" and result["error"] == 1  # not a raise


def test_an_empty_queue_is_an_honest_no_op() -> None:
    result = _refresh(FakeLocalStore(rows=[]))
    assert result == {
        "state": "ok", "claimed": 0, "ranked": 0, "unranked": 0,
        "blocked": 0, "error": 0, "skipped": 0,
    }


def test_the_sweep_uses_the_configured_batch_size() -> None:
    store = FakeLocalStore(rows=[])
    execute_refresh(
        store,  # type: ignore[arg-type]
        FakeLocalPackProvider(), _gate(FakeCostStore()), _settings(), batch=7,
    )
    assert store.claimed_with == [7]


# --------------------------------------------------------------------------- #
# 5. R6 - the beat-overlap lock.
# --------------------------------------------------------------------------- #
def test_the_beat_returns_immediately_when_a_previous_tick_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R6: a tick arriving while the previous one is still draining must NOT pile a
    second batch of PAID checks on top - it returns and lets the next tick take them.
    """
    monkeypatch.setattr(wk, "_try_beat_lock", lambda: None)  # someone else holds it
    result = refresh_local_ranks()
    assert result == {"state": "skipped", "reason": "beat_overlap", "claimed": 0}


def test_the_beat_runs_and_releases_the_lock_when_it_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released: list[bool] = []

    class _Lock:
        def __exit__(self, *a: Any) -> None:
            released.append(True)

    store = FakeLocalStore(rows=[_row()])
    monkeypatch.setattr(wk, "_try_beat_lock", lambda: _Lock())
    monkeypatch.setattr(wk, "service_local_store", lambda: store)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(wk, "local_pack_provider_from_settings", lambda _s: FakeLocalPackProvider())

    assert refresh_local_ranks()["state"] == "ok"
    assert released == [True], "the advisory lock must be released after the sweep"


def test_the_lock_is_released_even_when_the_sweep_blows_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lock leaked on the error path would wedge the beat FOREVER (every later tick
    would see it held and skip)."""
    released: list[bool] = []

    class _Lock:
        def __exit__(self, *a: Any) -> None:
            released.append(True)

    def _boom(_settings: Any) -> Any:
        raise RuntimeError("provider construction failed")

    monkeypatch.setattr(wk, "_try_beat_lock", lambda: _Lock())
    monkeypatch.setattr(wk, "service_local_store", FakeLocalStore)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(wk, "local_pack_provider_from_settings", _boom)

    assert refresh_local_ranks()["state"] == "error"  # not a raise
    assert released == [True]


# --------------------------------------------------------------------------- #
# 6. The Celery entry points - the never-re-raise guarantee.
# --------------------------------------------------------------------------- #
def test_the_refresh_task_returns_a_result_dict_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``task_acks_late``, a raise redelivers the job -> a second PAID sweep."""

    class _Lock:
        def __exit__(self, *a: Any) -> None:
            return None

    def _boom() -> Any:
        raise RuntimeError("store construction failed")

    monkeypatch.setattr(wk, "_try_beat_lock", lambda: _Lock())
    monkeypatch.setattr(wk, "service_local_store", _boom)
    result = refresh_local_ranks()
    assert result == {"state": "error", "reason": "task failed", "claimed": 0}


def test_the_tasks_are_registered_under_their_stable_names() -> None:
    # The beat schedule + the router enqueue by these names; a rename would silently
    # orphan every job.
    assert refresh_local_ranks.name == "refresh_local_ranks"
    assert sync_gbp_profile.name == "sync_gbp_profile"


def test_the_beat_task_is_wired_into_the_schedule_and_the_include_list() -> None:
    from workers.celery_app import celery_app

    assert "app.modules.local_seo.tasks" in celery_app.conf.include
    entry = celery_app.conf.beat_schedule["refresh-local-ranks"]
    assert entry["task"] == "refresh_local_ranks"
    assert entry["schedule"] == float(_settings().local_rank_refresh_seconds)


# --------------------------------------------------------------------------- #
# 7. sync_gbp_profile - the approval-gated HOLD.
# --------------------------------------------------------------------------- #
def test_the_gbp_sync_holds_cleanly_with_no_oauth_client() -> None:
    """The GBP API is APPROVAL-gated: a new project starts at 0 QPM and approval takes
    days-to-weeks, so a token-less deploy is the EXPECTED state for most of this
    module's life. It must HOLD - not crash, not error - and the module stays fully
    usable on map-pack rank + citations alone.
    """
    store = FakeLocalStore()
    settings = _settings()
    assert settings.gbp_oauth_client_id is None  # the keyless baseline

    result = execute_gbp_sync(store, settings, profile_id=_PROFILE)  # type: ignore[arg-type]
    assert result == {"state": "held", "reason": "no_oauth_client", "held": True}
    assert store.profile_syncs == []  # a hold writes nothing


def test_the_gbp_sync_holds_when_the_client_has_no_sealed_token() -> None:
    """OAuth client configured, but this CLIENT never connected their GBP account: the
    reader reports no token and the sync HOLDS rather than failing."""
    store = FakeLocalStore()
    settings = _settings(gbp_oauth_client_id="id", gbp_oauth_client_secret="secret")
    result = execute_gbp_sync(
        store, settings, profile_id=_PROFILE, reader=lambda _p: None  # type: ignore[arg-type]
    )
    assert result == {"state": "held", "reason": "no_oauth_token", "held": True}
    assert store.profile_syncs == []


def test_the_gbp_sync_holds_when_no_reader_is_wired() -> None:
    store = FakeLocalStore()
    settings = _settings(gbp_oauth_client_id="id", gbp_oauth_client_secret="secret")
    result = execute_gbp_sync(store, settings, profile_id=_PROFILE)  # type: ignore[arg-type]
    assert result["held"] is True and result["state"] == "held"


def test_a_hold_is_never_an_error() -> None:
    # The distinction matters operationally: an error pages someone, a hold does not.
    store = FakeLocalStore()
    for settings in (
        _settings(),
        _settings(gbp_oauth_client_id="id", gbp_oauth_client_secret="s"),
    ):
        assert execute_gbp_sync(store, settings, profile_id=_PROFILE)["state"] != "error"  # type: ignore[arg-type]


def test_the_gbp_sync_writes_back_a_successful_read_and_rescoring() -> None:
    store = FakeLocalStore()
    settings = _settings(gbp_oauth_client_id="id", gbp_oauth_client_secret="secret")
    fetched = {
        "primary_category": "Cafe",
        "secondary_categories": ["Coffee shop", "Bakery"],
        "nap_name": "Verde Cafe",
        "nap_address": "123 Main Street",
        "nap_phone": "+1 555 010 9999",
        "website_uri": "https://verde.example",
        "regular_hours": {"mon": "9-5"},
        "review_count": 214,
        "avg_rating": 4.6,
    }
    result = execute_gbp_sync(
        store, settings, profile_id=_PROFILE, reader=lambda _p: fetched  # type: ignore[arg-type]
    )
    assert result["state"] == "ok" and result["held"] is False
    written = store.profile_syncs[0]
    assert written["review_count"] == 214
    # The score is RE-DERIVED from what GBP actually returned, never trusted from it.
    assert written["completeness_score"] == 100
    assert result["completeness"] == 100
    assert written["audit"]["missing"] == []


def test_a_failing_gbp_read_is_an_error_that_never_raises() -> None:
    def _boom(_p: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("gbp 500")

    store = FakeLocalStore()
    settings = _settings(gbp_oauth_client_id="id", gbp_oauth_client_secret="secret")
    result = execute_gbp_sync(store, settings, profile_id=_PROFILE, reader=_boom)  # type: ignore[arg-type]
    assert result == {"state": "error", "reason": "gbp read failed", "held": False}
    assert store.profile_syncs == []  # a failed read writes nothing


def test_an_unknown_profile_is_an_error_not_a_crash() -> None:
    store = FakeLocalStore()
    store.profiles.clear()
    result = execute_gbp_sync(store, _settings(), profile_id="gp-gone")  # type: ignore[arg-type]
    assert result["state"] == "error" and result["held"] is False


def test_the_sync_task_never_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("store construction failed")

    monkeypatch.setattr(wk, "service_local_store", _boom)
    assert sync_gbp_profile(_PROFILE) == {
        "state": "error", "reason": "task failed", "held": False
    }


def test_the_sync_task_holds_on_the_real_keyless_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end on the CURRENT deployed reality (no GBP keys): the task HOLDS."""
    store = FakeLocalStore()
    monkeypatch.setattr(wk, "service_local_store", lambda: store)
    monkeypatch.setattr(wk, "get_settings", _settings)
    result = sync_gbp_profile(_PROFILE)
    assert result["state"] == "held" and result["held"] is True


# --------------------------------------------------------------------------- #
# 8. The keyless / degraded provider path.
# --------------------------------------------------------------------------- #
def test_a_keyless_deploy_degrades_to_the_deterministic_fake_and_still_checks() -> None:
    """No Serper/DataForSEO credentials is the CURRENT deployed reality: the factory
    must hand back the fake (never None), so the module works rather than crashing."""
    from app.modules.local_seo.provider import local_pack_provider_from_settings

    settings = _settings()
    assert settings.serper_api_key is None and settings.dataforseo_login is None
    provider = local_pack_provider_from_settings(settings)
    assert isinstance(provider, FakeLocalPackProvider)

    store = FakeLocalStore()
    assert _refresh(store, provider)["state"] == "ok"


def test_the_degraded_path_logs_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    from app.modules.local_seo.provider import local_pack_provider_from_settings

    settings = _settings(dataforseo_login="secret-login")  # password missing -> degrade
    with caplog.at_level("INFO"):
        local_pack_provider_from_settings(settings)
    assert "secret-login" not in caplog.text  # only the reason is logged
