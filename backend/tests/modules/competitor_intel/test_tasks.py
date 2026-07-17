"""Competitor-intel workers: the cost-gate ORDERING, the never-re-raise contract, the
degrade paths, and idempotency on redelivery.

No DB, no network, no broker: the store is an in-memory fake, the providers are
recorders over the deterministic fakes, and the cost gate runs its REAL logic over a
fake store.

The rules under test are the ones that cost money if they break:

* the R5 pre-check happens BEFORE the provider call (a blocked run spends nothing);
* ``gate.commit`` happens only AFTER a successful fetch (a failed pull costs $0);
* the task NEVER re-raises (``task_acks_late`` would redeliver -> a second PAID pull);
* a redelivery converges on the same rows rather than duplicating them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.config import Settings
from app.modules.competitor_intel.tasks import execute_discovery, execute_gap_analysis
from app.services.cost_gate import CostGate, GateContext
from integrations.content_research import OrganicResult, SerpResult
from integrations.keyword_data import RankedKeyword

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeCostStore:
    """An in-memory ``CostStore`` so the REAL gate logic runs unstubbed."""

    def __init__(
        self,
        *,
        mode: str = "api",
        budget: tuple[float, float] | None = None,
        daily: float = 0.0,
        stop: float = 1_000.0,
        halted: bool = False,
    ) -> None:
        self.mode = mode
        self.budget = budget
        self.daily = daily
        self.stop = stop
        self.halted = halted
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> Any:
        return self.mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self.budget

    def daily_spent(self) -> float:
        return self.daily

    def daily_stop(self) -> float:
        return self.stop

    def is_halted(self) -> bool:
        return self.halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class FakeCompetitorStore:
    """In-memory stand-in for the privileged ServiceCompetitorStore."""

    def __init__(self, **over: Any) -> None:
        self.competitor: dict[str, Any] | None = {
            "id": "c-1", "code": "CI-0001", "client_id": "cl-1",
            "client_name": "NorthPeak Dental", "domain": "rival.com", "tracked": True,
        }
        self.competitor = {**self.competitor, **over} if over else self.competitor
        self.positions: dict[str, int | None] = {}
        self.sample: list[dict[str, Any]] = []
        self.domains: set[str] = set()
        self.client_site = "client.com"
        self.analyses: list[dict[str, Any]] = []
        self.discovered: list[str] = []
        # Every gap row ever written, keyed like the DB's unique(competitor_id, keyword).
        self.gap_rows: dict[tuple[str, str], dict[str, Any]] = {}

    def get_competitor(self, competitor_id: str) -> dict[str, Any] | None:
        return self.competitor

    def get_client_name(self, client_id: str) -> str | None:
        return "NorthPeak Dental"

    def client_domain(self, client_id: str) -> str:
        return self.client_site

    def client_positions(self, client_id: str) -> dict[str, int | None]:
        return dict(self.positions)

    def tracked_keywords_sample(self, client_id: str, *, limit: int) -> list[dict[str, Any]]:
        return list(self.sample[:limit])

    def existing_domains(self, client_id: str) -> set[str]:
        return set(self.domains)

    def add_discovered(self, *, client_id: str, client_name: str, domain: str, label: str) -> bool:
        if domain in self.domains:
            return False  # the DB's on-conflict-do-nothing
        self.domains.add(domain)
        self.discovered.append(domain)
        return True

    def record_analysis(
        self, competitor_id: str, *, client_id: str, gaps: list[dict[str, Any]], **kw: Any
    ) -> int:
        self.analyses.append({"competitor_id": competitor_id, "gaps": gaps, **kw})
        for gap in gaps:  # mirror the DB's upsert keyed by (competitor_id, keyword)
            self.gap_rows[(competitor_id, gap["keyword"])] = gap
        return len(gaps)


class RecordingKeywordProvider:
    """Logs the ORDER of its calls; serves a fixed ranked set."""

    provider = "recording"

    def __init__(self, log: list[str], ranked: list[RankedKeyword] | None = None) -> None:
        self._log = log
        self._ranked = ranked if ranked is not None else [
            RankedKeyword("shared term", position=2, volume=1_000, difficulty=40.0),
            RankedKeyword("their term", position=4, volume=900, difficulty=30.0),
        ]

    def ranked_keywords(self, domain: str, **kw: Any) -> list[RankedKeyword]:
        self._log.append("provider.ranked_keywords")
        return list(self._ranked)


class BoomKeywordProvider:
    provider = "boom"

    def __init__(self, log: list[str] | None = None) -> None:
        self._log = log if log is not None else []

    def ranked_keywords(self, domain: str, **kw: Any) -> list[RankedKeyword]:
        self._log.append("provider.ranked_keywords")
        raise RuntimeError("vendor down")


class RecordingSerpResearcher:
    provider = "recording"

    def __init__(self, log: list[str], urls: list[str] | None = None) -> None:
        self._log = log
        self._urls = urls if urls is not None else ["https://rival.com/a", "https://other.com/b"]

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        self._log.append("provider.serp")
        return SerpResult(
            keyword=keyword,
            geo=geo,
            organic=[
                OrganicResult(position=i + 1, title="t", link=url)
                for i, url in enumerate(self._urls)
            ],
        )


class BoomSerpResearcher:
    provider = "boom"

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        raise RuntimeError("vendor down")


def _settings(**over: Any) -> Settings:
    # A LIVE keyword vendor by default so the gate has a real price to check; without
    # credentials the module degrades to $0 and the cost assertions would be vacuous.
    base: dict[str, Any] = {
        "_env_file": None, "app_env": "dev",
        "dataforseo_login": "u", "dataforseo_password": "p",
        "serper_api_key": "k",
        "competitor_intel_cost_estimate": 0.05,
        "competitor_intel_serp_cost_estimate": 0.001,
    }
    base.update(over)
    return Settings(**base)


def _gate(store: FakeCostStore) -> CostGate:
    return CostGate(store, _NullCache())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. The happy path.
# --------------------------------------------------------------------------- #
def test_a_gap_analysis_stores_the_verdicts_and_rolls_the_read_model() -> None:
    store = FakeCompetitorStore()
    store.positions = {"shared term": 7}  # the client ranks, but behind -> weak
    result = execute_gap_analysis(
        store,  # type: ignore[arg-type]
        RecordingKeywordProvider([]),
        _gate(FakeCostStore()),
        _settings(),
        competitor_id="c-1",
    )
    assert result["state"] == "ok"
    assert result["analyzed"] == 2
    # 'their term' is a pure gap; 'shared term' is weak -> both are opportunities.
    assert result["gaps"] == 2
    assert result["common"] == 1  # only 'shared term' is ranked by both

    written = store.analyses[0]["gaps"]
    verdicts = {g["keyword"]: g["gap_type"] for g in written}
    # 'their term' is a pure gap carrying 900 searches, i.e. above the settings'
    # 500 untapped threshold -> the actionable subset, not merely 'missing'.
    assert verdicts == {"shared term": "weak", "their term": "untapped"}
    assert isinstance(store.analyses[0]["analyzed_at"], datetime)


def test_the_client_position_comes_free_from_the_rank_tracker_never_a_second_pull() -> None:
    """Phase 2C's whole premise: the client's side of the comparison is a fact they
    already pay for nightly (0036). The provider is asked for the RIVAL's domain and
    nothing else - a second pull for the client's own domain would bill them twice for
    a number already on the read model."""
    log: list[str] = []
    store = FakeCompetitorStore()
    store.positions = {"shared term": 3}

    class _DomainRecorder(RecordingKeywordProvider):
        def __init__(self, log: list[str]) -> None:
            super().__init__(log)
            self.domains: list[str] = []

        def ranked_keywords(self, domain: str, **kw: Any) -> list[RankedKeyword]:
            self.domains.append(domain)
            return super().ranked_keywords(domain, **kw)

    provider = _DomainRecorder(log)
    execute_gap_analysis(
        store, provider, _gate(FakeCostStore()), _settings(), competitor_id="c-1"  # type: ignore[arg-type]
    )
    assert provider.domains == ["rival.com"]  # the rival's domain ONLY
    assert "client.com" not in provider.domains
    assert log.count("provider.ranked_keywords") == 1
    # ... and the free client position actually landed on the verdict.
    assert store.analyses[0]["gaps"][0]["client_position"] == 3


def test_the_competitors_domain_is_normalised_before_the_paid_pull() -> None:
    """One competitor, one bill: a row stored (or hand-typed) as a URL must not buy a
    different analysis than the same rival as a bare host."""
    store = FakeCompetitorStore(domain="https://WWW.Rival.com/path")
    provider = RecordingKeywordProvider([])
    captured: list[str] = []
    provider.ranked_keywords = lambda domain, **kw: (  # type: ignore[method-assign]
        captured.append(domain) or []  # type: ignore[func-returns-value]
    )
    execute_gap_analysis(
        store, provider, _gate(FakeCostStore()), _settings(), competitor_id="c-1"  # type: ignore[arg-type]
    )
    assert captured == ["rival.com"]


# --------------------------------------------------------------------------- #
# 2. R5 - the cost pre-check ORDERING.
# --------------------------------------------------------------------------- #
def test_the_cost_precheck_runs_before_the_provider_call() -> None:
    """R5's whole point. If the gate were consulted after the pull, a blocked run would
    already have spent the money it was blocked to save."""
    log: list[str] = []
    cost = FakeCostStore()

    class _LoggingGate(CostGate):
        def evaluate(self, ctx: GateContext) -> Any:
            log.append("gate.evaluate")
            return super().evaluate(ctx)

        def commit(self, ctx: GateContext, cost_: float, **kw: Any) -> None:
            log.append("gate.commit")
            super().commit(ctx, cost_, **kw)

    execute_gap_analysis(
        FakeCompetitorStore(),  # type: ignore[arg-type]
        RecordingKeywordProvider(log),
        _LoggingGate(cost, _NullCache()),  # type: ignore[arg-type]
        _settings(),
        competitor_id="c-1",
    )
    assert log == ["gate.evaluate", "provider.ranked_keywords", "gate.commit"]


def test_a_gate_block_degrades_with_no_call_no_spend_and_no_write() -> None:
    """A block DEGRADES: no provider call, an honest $0, and CRUCIALLY no write.

    Writing an empty gap set here would read as "this rival has no advantage over us" -
    a lie. The previous analysis stands: old, but true.
    """
    log: list[str] = []
    cost = FakeCostStore(mode="off")
    store = FakeCompetitorStore()
    result = execute_gap_analysis(
        store,  # type: ignore[arg-type]
        RecordingKeywordProvider(log),
        _gate(cost),
        _settings(),
        competitor_id="c-1",
    )
    assert result["state"] == "blocked"
    assert result["reason"] == "skip"
    assert log == []  # the provider was never called
    assert cost.recorded == []  # nothing was billed
    assert store.analyses == []  # nothing was overwritten


@pytest.mark.parametrize(
    ("store_kwargs", "expected"),
    [
        ({"mode": "off"}, "skip"),
        ({"mode": "byhand"}, "manual"),
        ({"budget": (1.0, 0.99)}, "blocked_cap"),
        ({"halted": True}, "blocked_daily"),
        ({"daily": 999.99, "stop": 1000.0}, "blocked_daily"),
    ],
)
def test_every_gate_outcome_degrades_rather_than_crashing(
    store_kwargs: dict[str, Any], expected: str
) -> None:
    log: list[str] = []
    result = execute_gap_analysis(
        FakeCompetitorStore(),  # type: ignore[arg-type]
        RecordingKeywordProvider(log),
        _gate(FakeCostStore(**store_kwargs)),
        _settings(),
        competitor_id="c-1",
    )
    assert result["state"] == "blocked"
    assert result["reason"] == expected
    assert log == []


def test_the_analysis_is_billed_to_the_client_never_the_agency() -> None:
    cost = FakeCostStore()
    execute_gap_analysis(
        FakeCompetitorStore(),  # type: ignore[arg-type]
        RecordingKeywordProvider([]),
        _gate(cost),
        _settings(),
        competitor_id="c-1",
    )
    ctx, billed, cached = cost.recorded[0]
    assert ctx.client_id == "cl-1"  # the competitor's client, never None
    assert ctx.feature_key == "competitor_intel"  # its OWN money dial
    assert ctx.job_type == "gap_analysis"
    assert billed == 0.05
    assert not cached


def test_a_failed_pull_costs_the_client_nothing_and_writes_nothing() -> None:
    """``gate.commit`` sits AFTER a successful fetch, so a vendor outage is free."""
    cost = FakeCostStore()
    store = FakeCompetitorStore()
    result = execute_gap_analysis(
        store,  # type: ignore[arg-type]
        BoomKeywordProvider(),
        _gate(cost),
        _settings(),
        competitor_id="c-1",
    )
    assert result["state"] == "error"
    assert result["reason"] == "provider fetch failed"
    assert cost.recorded == []  # never billed
    assert store.analyses == []  # the previous analysis stands


def test_a_keyless_deploy_prices_at_zero_rather_than_quoting_a_real_bill() -> None:
    """The degrade must be legible in the MONEY too: simulated data costs $0."""
    cost = FakeCostStore()
    execute_gap_analysis(
        FakeCompetitorStore(),  # type: ignore[arg-type]
        RecordingKeywordProvider([]),
        _gate(cost),
        _settings(dataforseo_login=None, dataforseo_password=None),
        competitor_id="c-1",
    )
    ctx, billed, _cached = cost.recorded[0]
    assert billed == 0.0
    assert ctx.provider == "fake"


def test_an_unknown_or_domainless_competitor_never_spends() -> None:
    cost = FakeCostStore()
    log: list[str] = []
    missing = FakeCompetitorStore()
    missing.competitor = None
    assert execute_gap_analysis(
        missing, RecordingKeywordProvider(log), _gate(cost), _settings(), competitor_id="c-1"  # type: ignore[arg-type]
    )["reason"] == "unknown competitor"

    blank = FakeCompetitorStore(domain="")
    assert execute_gap_analysis(
        blank, RecordingKeywordProvider(log), _gate(cost), _settings(), competitor_id="c-1"  # type: ignore[arg-type]
    )["reason"] == "no domain to analyze"

    assert log == []  # do not pay to learn nothing
    assert cost.recorded == []


# --------------------------------------------------------------------------- #
# 3. Idempotency on redelivery.
# --------------------------------------------------------------------------- #
def test_a_redelivered_analysis_converges_rather_than_duplicating() -> None:
    """``task_acks_late`` means a redelivery WILL happen. The gap upsert is keyed by
    ``(competitor_id, keyword)`` (0037), so the second run refreshes the same rows."""
    store = FakeCompetitorStore()
    args = (RecordingKeywordProvider([]), _gate(FakeCostStore()), _settings())
    first = execute_gap_analysis(store, *args, competitor_id="c-1")  # type: ignore[arg-type]
    second = execute_gap_analysis(store, *args, competitor_id="c-1")  # type: ignore[arg-type]

    assert first["state"] == second["state"] == "ok"
    assert first["gaps"] == second["gaps"]
    # Two runs, but the keyed row set is unchanged - no duplicate gaps.
    assert len(store.gap_rows) == 2
    assert {k[1] for k in store.gap_rows} == {"shared term", "their term"}


def test_a_redelivered_discovery_adds_nothing_the_second_time() -> None:
    store = FakeCompetitorStore()
    store.sample = [
        {"keyword": "k1", "search_volume": 100},
        {"keyword": "k2", "search_volume": 100},
    ]
    args = (RecordingSerpResearcher([]), _gate(FakeCostStore()), _settings())
    first = execute_discovery(store, *args, client_id="cl-1")  # type: ignore[arg-type]
    second = execute_discovery(store, *args, client_id="cl-1")  # type: ignore[arg-type]
    assert first["added"] >= 1
    assert second["added"] == 0  # on-conflict-do-nothing
    assert len(store.discovered) == len(set(store.discovered))


# --------------------------------------------------------------------------- #
# 4. Discovery specifics.
# --------------------------------------------------------------------------- #
def test_discovery_prices_the_whole_sweep_as_one_unit() -> None:
    """One press is N paid SERPs. Gating each separately would let a sweep walk past a
    cap that the one true charge would have been refused for."""
    cost = FakeCostStore()
    store = FakeCompetitorStore()
    store.sample = [{"keyword": f"k{i}", "search_volume": 100} for i in range(4)]
    execute_discovery(
        store, RecordingSerpResearcher([]), _gate(cost), _settings(), client_id="cl-1"  # type: ignore[arg-type]
    )
    ctx, billed, _cached = cost.recorded[0]
    assert ctx.estimated_cost == pytest.approx(0.004)  # 4 keywords x $0.001
    assert billed == pytest.approx(0.004)  # all four delivered
    assert ctx.client_id == "cl-1"
    assert ctx.job_type == "competitor_discovery"


def test_an_empty_tracking_book_is_a_no_op_never_a_paid_call() -> None:
    """Discovery mines the client's tracked SERPs; with none there is nothing to mine -
    and emphatically nothing to pay for."""
    cost = FakeCostStore()
    log: list[str] = []
    result = execute_discovery(
        FakeCompetitorStore(), RecordingSerpResearcher(log), _gate(cost), _settings(), client_id="cl-1"  # type: ignore[arg-type]
    )
    assert result["state"] == "skipped"
    assert result["reason"] == "no tracked keywords"
    assert log == []
    assert cost.recorded == []


def test_a_partial_sweep_bills_only_what_was_delivered() -> None:
    """One bad SERP must not sink the sweep (the other pulls are still useful) - but the
    client is charged for what actually arrived, never for the whole authorised sweep."""
    cost = FakeCostStore()
    store = FakeCompetitorStore()
    store.sample = [{"keyword": f"k{i}", "search_volume": 100} for i in range(4)]

    class _FlakySerp(RecordingSerpResearcher):
        def __init__(self) -> None:
            super().__init__([])
            self.calls = 0

        def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("one bad SERP")
            return super().serp(keyword, geo)

    result = execute_discovery(
        store, _FlakySerp(), _gate(cost), _settings(), client_id="cl-1"  # type: ignore[arg-type]
    )
    assert result["state"] == "ok"
    assert result["serps"] == 3
    assert result["failures"] == 1
    _ctx, billed, _cached = cost.recorded[0]
    assert billed == pytest.approx(0.003)  # 3 of 4 delivered, not 0.004


def test_a_totally_failed_sweep_bills_nothing() -> None:
    cost = FakeCostStore()
    store = FakeCompetitorStore()
    store.sample = [{"keyword": "k1", "search_volume": 100}]
    result = execute_discovery(
        store, BoomSerpResearcher(), _gate(cost), _settings(), client_id="cl-1"  # type: ignore[arg-type]
    )
    assert result["state"] == "error"
    assert cost.recorded == []


def test_a_blocked_discovery_degrades_with_no_call_and_no_spend() -> None:
    cost = FakeCostStore(mode="off")
    log: list[str] = []
    store = FakeCompetitorStore()
    store.sample = [{"keyword": "k1", "search_volume": 100}]
    result = execute_discovery(
        store, RecordingSerpResearcher(log), _gate(cost), _settings(), client_id="cl-1"  # type: ignore[arg-type]
    )
    assert result["state"] == "blocked"
    assert log == []
    assert cost.recorded == []
    assert store.discovered == []


# --------------------------------------------------------------------------- #
# 5. The never-re-raise contract (the Celery entry points).
# --------------------------------------------------------------------------- #
def test_the_analysis_task_never_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``task_acks_late`` a raised exception REDELIVERS the job - and a redelivered
    PAID analysis double-bills the client. So a catastrophic failure must come back as
    an error DICT, never as an exception."""
    import app.modules.competitor_intel.tasks as wk

    def _boom(_s: Any) -> Any:
        raise RuntimeError("wiring exploded")

    monkeypatch.setattr(wk, "keyword_source_from_settings", _boom)
    result = wk.run_gap_analysis("c-1")  # must NOT raise
    assert result == {"state": "error", "reason": "task failed", "competitor_id": "c-1"}


def test_the_discovery_task_never_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.competitor_intel.tasks as wk

    def _boom(_s: Any) -> Any:
        raise RuntimeError("wiring exploded")

    monkeypatch.setattr(wk, "serp_source_from_settings", _boom)
    result = wk.discover_competitors("cl-1")  # must NOT raise
    assert result == {"state": "error", "reason": "task failed", "client_id": "cl-1"}


def test_the_tasks_are_name_pinned() -> None:
    """Explicit ``name=`` pins the routing key: a rename/move must not silently orphan
    queued jobs."""
    import app.modules.competitor_intel.tasks as wk

    assert wk.run_gap_analysis.name == "run_gap_analysis"
    assert wk.discover_competitors.name == "discover_competitors"


def test_the_module_registers_its_own_money_dial() -> None:
    """The spend rides its OWN dial so ops can throttle competitive research without
    touching audits, content or rank tracking."""
    import app.modules.competitor_intel.tasks as wk

    assert wk._FEATURE == "competitor_intel"
