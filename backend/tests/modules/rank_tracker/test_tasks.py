"""Rank-tracker workers: the never-re-raise / gate-first / idempotent contract, and the
one rule this whole module exists to protect.

NO DB, NO network, NO broker: the store is in-memory, the cost gate runs on a fake
``CostStore``, and the provider is the sha256-seeded fake (or a deliberately failing
stub). The Celery tasks are invoked as plain functions - ``.delay`` is never called.

THE SINGLE MOST IMPORTANT TEST IN THIS MODULE is
``test_a_provider_error_writes_no_row_and_never_fabricates_unranked``. ``position=NULL``
means "successfully checked, not in the top-N" (unranked). A provider outage is NOT
that. If a failed fetch were recorded as unranked, the client's board would show the
keyword falling off the map, the change column would read "lost", and the alerting
would fire - all because a vendor returned a 503. Everything else in this file exists
to keep that distinction, and the money, honest:

1. **Never re-raise.** ``task_acks_late=True`` means a raised exception REDELIVERS the
   job - which here means a second PAID rank check, i.e. double-billing the client.
2. **Cost pre-check BEFORE the provider call (R5).** A gate decision taken after the
   fetch has already spent the money it was meant to prevent, so the ORDERING is
   asserted, not just the outcome.
3. **Idempotent.** ``on conflict (keyword_id, checked_on) do nothing`` + the today
   pre-check make a redelivery a no-op rather than a second charge.
4. **A gate block DEGRADES and EMITS THE STALENESS SIGNAL** - the stall must be
   visible, never silent.
5. **The beat takes the R6 overlap lock** before it fans anything out.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.config import Settings
from app.modules.rank_tracker import tasks as wk
from app.modules.rank_tracker.provider import FakeRankProvider, SerpSnapshot
from app.modules.rank_tracker.tasks import (
    check_keyword_rank,
    dispatch_due,
    dispatch_rank_checks,
    execute_rank_check,
    execute_rollup,
    rollup_rank_history,
)
from app.services.cost_gate import CostGate, DialMode, GateContext

pytestmark = pytest.mark.unit

_TODAY = date(2026, 7, 17)
_DOMAIN = "northpeak.example"


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeRankStore:
    """In-memory stand-in for the privileged ServiceRankStore.

    ``rankings`` is keyed exactly like the real ``unique (keyword_id, checked_on)``
    index, so "did a redelivery write a second snapshot?" is answerable by counting it.
    """

    def __init__(self, rows: dict[str, dict[str, Any]] | None = None) -> None:
        self.keywords: dict[str, dict[str, Any]] = rows or {"kw-1": _keyword_row()}
        self.rankings: dict[tuple[str, date], dict[str, Any]] = {}
        self.stalls: list[tuple[str, date]] = []
        self.calls: list[str] = []
        self.claimed: list[dict[str, Any]] = []
        self.lock_taken = False
        self.rollups: list[tuple[date, date]] = []

    # --- dispatcher ---
    def claim_due_keywords(self, limit: int) -> list[dict[str, Any]]:
        self.calls.append("claim_due_keywords")
        self.lock_taken = True  # the real store takes pg_try_advisory_xact_lock here
        return list(self.claimed[:limit])

    # --- check ---
    def get_keyword(self, keyword_id: str) -> dict[str, Any] | None:
        self.calls.append("get_keyword")
        return self.keywords.get(keyword_id)

    def has_ranking_on(self, keyword_id: str, checked_on: date) -> bool:
        self.calls.append("has_ranking_on")
        return (keyword_id, checked_on) in self.rankings

    def record_check(self, keyword_id: str, *, checked_on: date, **kw: Any) -> bool:
        self.calls.append("record_check")
        key = (keyword_id, checked_on)
        if key in self.rankings:
            return False  # the real `on conflict do nothing`
        self.rankings[key] = {"keyword_id": keyword_id, "checked_on": checked_on, **kw}
        row = self.keywords.get(keyword_id)
        if row is not None:  # mirror the roll-forward the real UPDATE does
            row["previous_position"] = kw["previous_position"]
            row["latest_position"] = kw["position"]
            row["latest_checked_at"] = kw["checked_at"]
            row["next_check_on"] = kw["next_check_on"]
        return True

    def replace_check(self, keyword_id: str, *, checked_on: date, **kw: Any) -> None:
        self.calls.append("replace_check")
        key = (keyword_id, checked_on)
        # Mirror the real UPDATE: correct the day's row, keep the client_id it was
        # written with, and NEVER touch previous_position.
        existing = self.rankings.get(key, {})
        self.rankings[key] = {**existing, "keyword_id": keyword_id, "checked_on": checked_on, **kw}
        row = self.keywords.get(keyword_id)
        if row is not None:
            row["latest_position"] = kw["position"]
            row["latest_checked_at"] = kw["checked_at"]
            row["next_check_on"] = kw["next_check_on"]

    def record_stall(self, keyword_id: str, *, next_check_on: date) -> None:
        self.calls.append("record_stall")
        self.stalls.append((keyword_id, next_check_on))

    def rollup_history(self, *, rollup_before: date, purge_before: date) -> dict[str, int]:
        self.calls.append("rollup_history")
        self.rollups.append((rollup_before, purge_before))
        return {"rolled_up": 3, "purged": 2}


class FakeCostStore:
    """Minimal CostStore: a settable dial + a recorder for what was actually spent."""

    def __init__(self, *, mode: DialMode = "api", halted: bool = False,
                 budget: tuple[float, float] | None = None) -> None:
        self._mode = mode
        self._halted = halted
        self._budget = budget
        self.recorded: list[tuple[str, float, str | None]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 100.0

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx.feature_key, cost, ctx.client_id))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class FailingProvider:
    """A provider whose fetch FAILS the way the real ones do - by RETURNING a snapshot
    with ``error`` set, never by raising. This is the seam's failure contract."""

    provider = "serper"
    enabled = True

    def __init__(self, error: str = "TimeoutError") -> None:
        self._error = error
        self.calls = 0

    def estimated_cost(self, depth: int = 100) -> float:
        return 0.01

    def fetch_serp(self, keyword: str, **kw: Any) -> SerpSnapshot:
        self.calls += 1
        return SerpSnapshot(keyword=keyword, provider=self.provider, error=self._error)


class ExplodingProvider:
    """A provider that breaks its contract and RAISES. The task wrapper must still
    never re-raise (a redelivery = a second paid check)."""

    provider = "serper"
    enabled = True

    def estimated_cost(self, depth: int = 100) -> float:
        return 0.01

    def fetch_serp(self, keyword: str, **kw: Any) -> SerpSnapshot:
        raise RuntimeError("serper client blew up")


class RecordingProvider:
    """Wraps the deterministic fake and logs WHEN it was called."""

    provider = "recording"
    enabled = True

    def __init__(self, log: list[str], *, domain: str | None = _DOMAIN) -> None:
        self._log = log
        self._inner = FakeRankProvider(domain=domain)

    def estimated_cost(self, depth: int = 100) -> float:
        return 0.01

    def fetch_serp(self, keyword: str, **kw: Any) -> SerpSnapshot:
        self._log.append("provider.fetch_serp")
        return self._inner.fetch_serp(keyword, **kw)


class RankedProvider:
    """Returns a snapshot placing ``domain`` at a chosen position (or nowhere)."""

    provider = "serper"
    enabled = True

    def __init__(self, *, position: int | None, extra_own: int | None = None) -> None:
        self._position = position
        self._extra_own = extra_own

    def estimated_cost(self, depth: int = 100) -> float:
        return 0.01

    def fetch_serp(self, keyword: str, **kw: Any) -> SerpSnapshot:
        from app.modules.rank_tracker.provider import OrganicHit

        organic = [
            OrganicHit(position=i, url=f"https://other{i}.example/p", title=f"r{i}")
            for i in range(1, 11)
        ]
        if self._position is not None:
            organic[self._position - 1] = OrganicHit(
                position=self._position, url=f"https://{_DOMAIN}/best", title="ours"
            )
        if self._extra_own is not None:
            organic[self._extra_own - 1] = OrganicHit(
                position=self._extra_own, url=f"https://{_DOMAIN}/other", title="ours too"
            )
        return SerpSnapshot(
            keyword=keyword, organic=organic, features=["local_pack"],
            provider=self.provider, fetched_at=datetime(2026, 7, 17, 3, 20, tzinfo=UTC),
        )


def _keyword_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "kw-1", "code": "RK-00001", "client_id": "cl-1",
        "client_name": "NorthPeak Dental", "keyword": "dental implants karachi",
        "site_domain": _DOMAIN, "target_url": "", "engine": "google", "device": "desktop",
        "location": "Karachi,Pakistan", "language": "en", "country": "pk",
        "cadence": "weekly", "status": "active", "latest_position": 7,
        "previous_position": 9, "best_position": 5, "latest_checked_at": None,
    }
    row.update(over)
    return row


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(store: FakeCostStore) -> CostGate:
    return CostGate(store, _NullCache())


def _run(
    *,
    store: FakeRankStore | None = None,
    provider: Any = None,
    cost: FakeCostStore | None = None,
    keyword_id: str = "kw-1",
    force: bool = False,
    today: date | None = _TODAY,
) -> dict[str, Any]:
    return execute_rank_check(
        store or FakeRankStore(),  # type: ignore[arg-type]
        provider or FakeRankProvider(domain=_DOMAIN),
        _gate(cost or FakeCostStore()),
        _settings(),
        keyword_id=keyword_id,
        force=force,
        today=today,
    )


# --------------------------------------------------------------------------- #
# 1. THE CRITICAL RULE: a provider error never fabricates an unranked reading.
# --------------------------------------------------------------------------- #
def test_a_provider_error_writes_no_row_and_never_fabricates_unranked() -> None:
    """THE most important test in this module.

    ``position=NULL`` means "checked, not in the top-N". A vendor outage is a different
    fact entirely. If an error were written as a snapshot, the board would show a
    phantom LOST RANKING and fire a false alert off a 503.
    """
    store = FakeRankStore()
    before = dict(store.keywords["kw-1"])

    result = _run(store=store, provider=FailingProvider())

    assert result["state"] == "error"
    assert result["reason"] == "provider fetch failed"
    # 1. NO history row at all - not even one with position=None.
    assert store.rankings == {}
    assert "record_check" not in store.calls
    # 2. Every position column is untouched: the last GOOD reading still stands.
    assert store.keywords["kw-1"]["latest_position"] == before["latest_position"] == 7
    assert store.keywords["kw-1"]["previous_position"] == before["previous_position"] == 9


def test_a_provider_error_leaves_the_movement_reading_unchanged() -> None:
    """The user-visible consequence of the rule above: the change column must NOT flip
    to 'lost' because a vendor had a bad night."""
    from app.modules.rank_tracker.service import change_for_row

    store = FakeRankStore()
    _run(store=store, provider=FailingProvider())
    change = change_for_row(store.keywords["kw-1"])
    assert change.direction != "lost"
    assert change.direction == "up" and change.value == "2"  # 9 -> 7, exactly as before


def test_a_genuinely_unranked_check_does_write_a_null_position_row() -> None:
    """The other half of the distinction: a SUCCESSFUL check that finds nothing is a
    real datum and must be recorded - otherwise the module could never report a drop
    out of the top 100 at all."""
    store = FakeRankStore()
    result = _run(store=store, provider=RankedProvider(position=None))

    assert result["state"] == "ok"
    assert result["position"] is None
    snapshot = store.rankings[("kw-1", _TODAY)]
    assert snapshot["position"] is None  # recorded, honestly, as unranked
    assert store.keywords["kw-1"]["latest_position"] is None


def test_the_two_paths_are_distinguishable_by_their_effects() -> None:
    # Side by side: same absence of a position, opposite treatment.
    failed = FakeRankStore()
    _run(store=failed, provider=FailingProvider())
    unranked = FakeRankStore()
    _run(store=unranked, provider=RankedProvider(position=None))

    assert failed.rankings == {}  # an outage records nothing
    assert len(unranked.rankings) == 1  # an unranked reading records a fact


def test_a_failed_fetch_is_never_charged() -> None:
    """The commit sits AFTER a successful fetch, so a vendor failure costs the client
    $0 - they are not billed for a pull that returned nothing."""
    cost = FakeCostStore()
    _run(cost=cost, provider=FailingProvider())
    assert cost.recorded == []


def test_a_failed_fetch_emits_the_staleness_signal() -> None:
    # The stall must be VISIBLE: record_stall re-arms the schedule while HOLDING
    # latest_checked_at, which is what the read side computes `stale` from.
    store = FakeRankStore()
    result = _run(store=store, provider=FailingProvider())
    assert result["stale"] is True
    assert store.stalls == [("kw-1", _TODAY + timedelta(days=7))]
    assert store.keywords["kw-1"]["latest_checked_at"] is None  # freshness stamp HELD


# --------------------------------------------------------------------------- #
# 2. R5 - the cost pre-check runs BEFORE any provider call.
# --------------------------------------------------------------------------- #
def test_the_cost_gate_is_consulted_before_the_provider_is_touched() -> None:
    """The ORDERING is the whole point of a pre-check: gate-then-fetch spends nothing on
    a blocked check; fetch-then-gate has already spent it."""
    log: list[str] = []

    class _LoggingStore(FakeCostStore):
        def dial_mode(self, feature_key: str) -> DialMode:
            log.append("gate.dial_mode")
            return "api"

        def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
            log.append("gate.record_cost")
            super().record_cost(ctx, cost, cached=cached)

    _run(cost=_LoggingStore(), provider=RecordingProvider(log))
    assert log[0] == "gate.dial_mode"  # the gate decides first...
    assert log[1] == "provider.fetch_serp"  # ...then the paid pull happens...
    assert log[2] == "gate.record_cost"  # ...and the spend is committed after.


def test_the_today_dedupe_runs_before_the_gate_so_a_repeat_costs_nothing() -> None:
    # The unique index makes the WRITE idempotent, but a redelivery would already have
    # paid the vendor - so the day guard must come first of all.
    store = FakeRankStore()
    store.rankings[("kw-1", _TODAY)] = {"position": 3}
    cost = FakeCostStore()
    result = _run(store=store, cost=cost, provider=ExplodingProvider())

    assert result["state"] == "skipped"  # not "error": the provider was never called
    assert cost.recorded == []
    assert store.calls.index("has_ranking_on") < len(store.calls)
    assert "record_check" not in store.calls


@pytest.mark.parametrize(
    ("cost_store", "reason"),
    [
        (FakeCostStore(mode="off"), "skip"),
        (FakeCostStore(mode="byhand"), "manual"),
        (FakeCostStore(halted=True), "blocked_daily"),
        (FakeCostStore(budget=(10.0, 10.0)), "blocked_cap"),
    ],
)
def test_a_blocked_dial_degrades_with_zero_spend_and_raises_nothing(
    cost_store: FakeCostStore, reason: str
) -> None:
    """A block DEGRADES: no exception, no provider call, provably no money recorded,
    and the ranks simply stay put."""
    store = FakeRankStore()
    result = _run(store=store, cost=cost_store, provider=ExplodingProvider())

    assert result["state"] == "blocked"
    assert result["reason"] == reason
    assert cost_store.recorded == []  # nothing was charged
    assert store.rankings == {}  # nothing was written
    assert store.keywords["kw-1"]["latest_position"] == 7  # ranks untouched
    # The exploding provider would have raised if it had been called at all - it was not.


def test_a_gate_block_emits_the_staleness_signal_so_the_stall_is_never_silent() -> None:
    """Degrading correctly is only half the job: on its own the board would keep showing
    last week's position as though it were today's."""
    store = FakeRankStore()
    result = _run(store=store, cost=FakeCostStore(mode="off"), provider=ExplodingProvider())

    assert result["stale"] is True
    assert store.stalls == [("kw-1", _TODAY + timedelta(days=7))]
    assert store.keywords["kw-1"]["latest_checked_at"] is None  # freshness lag preserved


def test_a_blocked_daily_cadence_keyword_is_rearmed_for_tomorrow_not_hot_spun() -> None:
    store = FakeRankStore({"kw-1": _keyword_row(cadence="daily")})
    _run(store=store, cost=FakeCostStore(mode="off"))
    assert store.stalls == [("kw-1", _TODAY + timedelta(days=1))]


def test_an_allowed_check_commits_exactly_the_providers_price() -> None:
    cost = FakeCostStore()
    _run(cost=cost, provider=RankedProvider(position=3))
    assert cost.recorded == [("rank_tracker", 0.01, "cl-1")]


def test_the_spend_rides_its_own_money_dial() -> None:
    # A dedicated dial lets ops throttle STANDING rank spend without touching
    # audits/content - which matters precisely because this cost recurs unasked.
    cost = FakeCostStore()
    _run(cost=cost, provider=RankedProvider(position=3))
    assert cost.recorded[0][0] == "rank_tracker"


def test_the_bill_is_charged_to_the_keywords_client_never_the_agency() -> None:
    """The contract: the rank-check API cost is the CLIENT's."""
    cost = FakeCostStore()
    _run(cost=cost, provider=RankedProvider(position=3))
    assert cost.recorded[0][2] == "cl-1"  # GateContext.client_id = the keyword's client


def test_the_gate_context_carries_the_client_name_and_the_keyword_code() -> None:
    seen: list[GateContext] = []

    class _CapturingStore(FakeCostStore):
        def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
            seen.append(ctx)
            super().record_cost(ctx, cost, cached=cached)

    _run(cost=_CapturingStore(), provider=RankedProvider(position=3))
    assert seen[0].client_name == "NorthPeak Dental"
    assert seen[0].job_id == "RK-00001"  # the cost log names the keyword
    assert seen[0].job_type == "rank_check"


# --------------------------------------------------------------------------- #
# 3. The happy path.
# --------------------------------------------------------------------------- #
def test_a_successful_check_records_the_snapshot_and_rolls_the_read_model() -> None:
    store = FakeRankStore()
    result = _run(store=store, provider=RankedProvider(position=3))

    assert result["state"] == "ok"
    assert result["position"] == 3 and result["previous"] == 7
    snapshot = store.rankings[("kw-1", _TODAY)]
    assert snapshot["position"] == 3
    assert snapshot["delta"] == 4  # 7 -> 3 = FOUR PLACES BETTER (the inverted scale)
    assert snapshot["ranking_url"] == f"https://{_DOMAIN}/best"
    assert snapshot["serp_features"] == ["local_pack"]
    assert snapshot["provider"] == "serper"
    assert snapshot["cost"] == 0.01
    # The roll-forward: today's reading becomes latest, yesterday's becomes previous.
    assert store.keywords["kw-1"]["latest_position"] == 3
    assert store.keywords["kw-1"]["previous_position"] == 7


def test_the_next_check_is_scheduled_by_the_keywords_cadence() -> None:
    for cadence, days in (("daily", 1), ("weekly", 7)):
        store = FakeRankStore({"kw-1": _keyword_row(cadence=cadence)})
        _run(store=store, provider=RankedProvider(position=3))
        assert store.rankings[("kw-1", _TODAY)]["next_check_on"] == _TODAY + timedelta(days=days)


def test_every_own_domain_hit_is_recorded_so_cannibalization_is_visible() -> None:
    """Two of the client's own pages competing for one term IS the signal. Keeping only
    the winner would erase the evidence."""
    store = FakeRankStore()
    result = _run(store=store, provider=RankedProvider(position=3, extra_own=8))

    assert result["own_hits"] == 2
    assert result["cannibalized"] is True
    own = store.rankings[("kw-1", _TODAY)]["own_urls"]
    assert '"position": 3' in own and '"position": 8' in own
    # The reported position is the BEST of them.
    assert result["position"] == 3


def test_a_single_hit_is_not_reported_as_cannibalized() -> None:
    assert _run(provider=RankedProvider(position=3))["cannibalized"] is False


def test_delta_is_none_when_there_is_nothing_to_compare() -> None:
    # First-ever ranking: no previous, so no numeric delta to record.
    store = FakeRankStore({"kw-1": _keyword_row(latest_position=None)})
    _run(store=store, provider=RankedProvider(position=3))
    assert store.rankings[("kw-1", _TODAY)]["delta"] is None


def test_the_check_is_deterministic_on_the_sha256_seeded_fake() -> None:
    assert _run(store=FakeRankStore()) == _run(store=FakeRankStore())


def test_a_keyword_with_no_domain_is_refused_before_any_spend() -> None:
    """Without a site domain or target URL there is nothing to look FOR - do not pay to
    learn nothing."""
    cost = FakeCostStore()
    store = FakeRankStore({"kw-1": _keyword_row(site_domain=None, target_url="")})
    result = _run(store=store, cost=cost, provider=ExplodingProvider())
    assert result == {"state": "error", "reason": "no domain to match", "keyword_id": "kw-1"}
    assert cost.recorded == []


def test_the_target_url_is_the_fallback_domain_when_no_site_is_linked() -> None:
    store = FakeRankStore(
        {"kw-1": _keyword_row(site_domain=None, target_url=f"https://{_DOMAIN}/page")}
    )
    assert _run(store=store, provider=RankedProvider(position=3))["position"] == 3


def test_an_unknown_keyword_is_an_error_not_a_crash() -> None:
    result = _run(store=FakeRankStore({}), keyword_id="kw-gone")
    assert result == {"state": "error", "reason": "unknown keyword", "keyword_id": "kw-gone"}


# --------------------------------------------------------------------------- #
# 4. Idempotency - a redelivery must not double-charge.
# --------------------------------------------------------------------------- #
def test_a_redelivery_is_a_no_op_and_never_charges_twice() -> None:
    """The property that makes ``task_acks_late`` redelivery safe. Without it, every
    redelivered job is a second bill on the client's account."""
    store = FakeRankStore()
    cost = FakeCostStore()
    first = _run(store=store, cost=cost, provider=RankedProvider(position=3))
    second = _run(store=store, cost=cost, provider=RankedProvider(position=3))

    assert first["state"] == "ok"
    assert second["state"] == "skipped"
    assert len(store.rankings) == 1  # not one extra snapshot
    assert len(cost.recorded) == 1  # ... and not one extra charge


def test_a_redelivery_cannot_corrupt_the_previous_position() -> None:
    """Re-applying the same day would overwrite the real previous position with today's
    and silently zero out the reported movement."""
    store = FakeRankStore()
    _run(store=store, provider=RankedProvider(position=3))
    _run(store=store, provider=RankedProvider(position=3))
    assert store.keywords["kw-1"]["previous_position"] == 7  # NOT 3


def test_the_on_conflict_race_is_reported_as_skipped_not_an_error() -> None:
    """A concurrent run won the day's slot between our pre-check and our insert. The
    snapshot stands; ours simply does not double-apply."""
    store = FakeRankStore()

    class _RacyStore(FakeRankStore):
        def has_ranking_on(self, keyword_id: str, checked_on: date) -> bool:
            return False  # the pre-check misses...

        def record_check(self, keyword_id: str, **kw: Any) -> bool:
            return False  # ...but the unique index catches it

    result = _run(store=_RacyStore(), provider=RankedProvider(position=3))
    assert result["state"] == "skipped"
    assert result["reason"] == "already checked today"
    assert store.rankings == {}


def test_force_re_checks_and_delivers_what_it_paid_for() -> None:
    """The on-demand override: an operator who KNOWS the SERP moved may pay again.

    The forced read must CORRECT today's snapshot. Letting ``on conflict do nothing``
    swallow it would bill the client and hand them back nothing - paying for a reading
    and then throwing it away.
    """
    store = FakeRankStore()
    _run(store=store, provider=RankedProvider(position=3))
    cost = FakeCostStore()

    result = _run(store=store, cost=cost, force=True, provider=RankedProvider(position=1))

    assert result["state"] == "ok" and result["rechecked"] is True
    assert cost.recorded == [("rank_tracker", 0.01, "cl-1")]  # it paid...
    assert store.rankings[("kw-1", _TODAY)]["position"] == 1  # ...and it got the reading
    assert store.keywords["kw-1"]["latest_position"] == 1
    assert len(store.rankings) == 1  # still ONE row for the day - append-only per day


def test_a_forced_recheck_measures_movement_against_yesterday_not_this_morning() -> None:
    """The subtle one. Today's first check already rolled 7 -> previous. A forced
    re-read must compare against THAT 7, not against this morning's 3 - otherwise the
    reported movement silently collapses toward zero on every re-check.
    """
    store = FakeRankStore()  # starts latest=7, previous=9
    _run(store=store, provider=RankedProvider(position=3))  # 7 -> 3, previous becomes 7
    _run(store=store, force=True, provider=RankedProvider(position=1))

    assert store.rankings[("kw-1", _TODAY)]["delta"] == 6  # 7 -> 1, NOT 3 -> 1 = 2
    assert store.keywords["kw-1"]["previous_position"] == 7  # yesterday's, untouched


# --------------------------------------------------------------------------- #
# 5. The beat dispatcher - the R6 overlap lock + the claim.
# --------------------------------------------------------------------------- #
def test_the_dispatcher_takes_the_beat_overlap_lock_before_fanning_out() -> None:
    """R6: a tick landing while the previous night still drains must be a no-op, not a
    second fan-out (= a second bill for every keyword)."""
    store = FakeRankStore()
    store.claimed = [{"id": "kw-1"}, {"id": "kw-2"}]
    sent: list[str] = []
    dispatch_due(store, batch=10, enqueue=sent.append)  # type: ignore[arg-type]
    assert store.lock_taken is True
    assert store.calls[0] == "claim_due_keywords"  # the lock+claim precede every enqueue
    assert sent == ["kw-1", "kw-2"]


def test_a_dispatcher_that_cannot_take_the_lock_fans_out_nothing() -> None:
    class _LockedOutStore(FakeRankStore):
        def claim_due_keywords(self, limit: int) -> list[dict[str, Any]]:
            return []  # pg_try_advisory_xact_lock returned false

    sent: list[str] = []
    assert dispatch_due(_LockedOutStore(), batch=10, enqueue=sent.append) == []  # type: ignore[arg-type]
    assert sent == []


def test_the_dispatcher_honours_its_batch_bound() -> None:
    store = FakeRankStore()
    store.claimed = [{"id": f"kw-{i}"} for i in range(50)]
    sent: list[str] = []
    dispatch_due(store, batch=5, enqueue=sent.append)  # type: ignore[arg-type]
    assert len(sent) == 5


def test_the_real_store_takes_an_xact_scoped_lock_and_skips_locked_rows() -> None:
    """Pins the two guards in the real SQL: a SESSION-scoped advisory lock on a POOLED
    connection could be released onto someone else's checkout (or leak forever if the
    worker died holding it), and without SKIP LOCKED two claimers could hand out the
    same keyword twice."""
    import inspect

    from app.modules.rank_tracker.repo import ServiceRankStore

    source = inspect.getsource(ServiceRankStore.claim_due_keywords)
    assert "pg_try_advisory_xact_lock" in source
    assert "for update skip locked" in source
    assert "status = 'active'" in source and "next_check_on <= current_date" in source


# --------------------------------------------------------------------------- #
# 6. The Celery entry points - the never-re-raise guarantee.
# --------------------------------------------------------------------------- #
def test_the_check_task_returns_a_result_dict_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``task_acks_late``, a raise redelivers the job -> a second PAID check. The
    task must swallow ANY failure, including one from its own wiring."""

    def _boom(_settings: Any) -> Any:
        raise RuntimeError("provider construction failed")

    monkeypatch.setattr(wk, "rank_provider_from_settings", _boom)
    result = check_keyword_rank("kw-1")  # called directly - no broker
    assert result == {"state": "error", "reason": "task failed", "keyword_id": "kw-1"}


def test_the_check_task_never_re_raises_a_provider_that_breaks_its_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The seam promises fetch_serp never raises; the task must survive it doing so anyway.
    store = FakeRankStore()
    monkeypatch.setattr(wk, "service_rank_store", lambda: store)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(wk, "rank_provider_from_settings", lambda _s: ExplodingProvider())
    assert check_keyword_rank("kw-1")["state"] == "error"  # not a raise
    assert store.rankings == {}  # and still nothing fabricated


def test_the_check_task_never_re_raises_a_store_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenStore(FakeRankStore):
        def get_keyword(self, keyword_id: str) -> dict[str, Any] | None:
            raise RuntimeError("connection reset")

    monkeypatch.setattr(wk, "service_rank_store", _BrokenStore)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(wk, "rank_provider_from_settings", lambda _s: FakeRankProvider())
    assert check_keyword_rank("kw-1")["state"] == "error"


def test_the_dispatch_task_never_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenStore(FakeRankStore):
        def claim_due_keywords(self, limit: int) -> list[dict[str, Any]]:
            raise RuntimeError("db down")

    monkeypatch.setattr(wk, "service_rank_store", _BrokenStore)
    assert dispatch_rank_checks() == {"state": "error", "claimed": 0}


def test_the_rollup_task_never_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenStore(FakeRankStore):
        def rollup_history(self, **kw: Any) -> dict[str, int]:
            raise RuntimeError("db down")

    monkeypatch.setattr(wk, "service_rank_store", _BrokenStore)
    assert rollup_rank_history() == {"state": "error", "rolled_up": 0, "purged": 0}


def test_the_dispatch_task_reports_what_it_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRankStore()
    store.claimed = [{"id": "kw-1"}, {"id": "kw-2"}]
    sent: list[str] = []
    monkeypatch.setattr(wk, "service_rank_store", lambda: store)
    monkeypatch.setattr(
        wk.check_keyword_rank, "delay", lambda kid: sent.append(kid)  # type: ignore[attr-defined]
    )
    assert dispatch_rank_checks() == {"state": "ok", "claimed": 2}
    assert sent == ["kw-1", "kw-2"]


@pytest.mark.parametrize(
    ("task", "name"),
    [
        (check_keyword_rank, "check_keyword_rank"),
        (dispatch_rank_checks, "dispatch_rank_checks"),
        (rollup_rank_history, "rollup_rank_history"),
    ],
)
def test_every_task_is_registered_under_its_stable_name(task: Any, name: str) -> None:
    # The router + beat schedule reference these names; a rename silently orphans them.
    assert task.name == name


def test_the_beat_schedule_registers_both_scheduled_tasks() -> None:
    from workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["dispatch-rank-checks"]["task"] == "dispatch_rank_checks"
    assert schedule["rollup-rank-history"]["task"] == "rollup_rank_history"


def test_the_tasks_module_is_registered_with_the_celery_app() -> None:
    from workers.celery_app import celery_app

    assert "app.modules.rank_tracker.tasks" in celery_app.conf.include


# --------------------------------------------------------------------------- #
# 7. Retention / rollup.
# --------------------------------------------------------------------------- #
def test_the_rollup_uses_the_configured_retention_windows() -> None:
    store = FakeRankStore()
    result = execute_rollup(
        store,  # type: ignore[arg-type]
        _settings(rank_tracker_rollup_after_days=90, rank_tracker_history_retention_days=730),
        today=_TODAY,
    )
    assert result == {"state": "ok", "rolled_up": 3, "purged": 2}
    assert store.rollups == [(_TODAY - timedelta(days=90), _TODAY - timedelta(days=730))]


def test_the_rollup_window_always_precedes_the_purge_window() -> None:
    # Thinning must happen BEFORE the purge horizon, or it would only ever touch rows
    # that were about to be deleted anyway.
    store = FakeRankStore()
    execute_rollup(store, _settings(), today=_TODAY)  # type: ignore[arg-type]
    rollup_before, purge_before = store.rollups[0]
    assert purge_before < rollup_before


def test_the_real_rollup_keeps_one_snapshot_per_iso_week() -> None:
    import inspect

    from app.modules.rank_tracker.repo import ServiceRankStore

    source = inspect.getsource(ServiceRankStore.rollup_history)
    assert "distinct on (keyword_id, date_trunc('week', checked_on))" in source
    assert "order by keyword_id, date_trunc('week', checked_on), checked_on desc" in source


# --------------------------------------------------------------------------- #
# 8. The keyless / degraded provider path.
# --------------------------------------------------------------------------- #
def test_a_keyless_deploy_degrades_to_the_deterministic_fake_and_still_runs() -> None:
    """No SERPER key is the CURRENT deployed reality: the factory must hand back the
    fake (never None), so the module works rather than crashing."""
    from app.modules.rank_tracker.provider import rank_provider_from_settings

    settings = _settings()
    assert settings.serper_api_key is None  # the keyless baseline
    provider = rank_provider_from_settings(settings)
    assert isinstance(provider, FakeRankProvider)
    assert provider.enabled is False  # ... and it says so: this is NOT live rank data

    store = FakeRankStore()
    assert _run(store=store, provider=FakeRankProvider(domain=_DOMAIN))["state"] == "ok"


def test_a_degraded_check_is_logged_as_costing_nothing() -> None:
    # The fake bills $0, so the cost log stays honest on a keyless deploy.
    cost = FakeCostStore()
    _run(cost=cost, provider=FakeRankProvider(domain=_DOMAIN))
    assert cost.recorded == [("rank_tracker", 0.0, "cl-1")]
