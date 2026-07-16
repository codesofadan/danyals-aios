"""Keyword-research worker: the never-re-raise / idempotent / gate-first contract.

NO DB, NO network, NO broker: the store is in-memory, the cost gate runs on a fake
``CostStore``, and the provider is the sha256-seeded fake (or a deliberately
exploding stub). The Celery task is invoked as a plain function - ``.delay`` is
never called, so no broker is needed.

The three properties pinned here are the ones that cost real money when they break
(cf. ``workers.tasks.audit`` / ``workers.tasks.offpage``, and invariant #8):

1. **Never re-raise.** ``task_acks_late=True`` means a raised exception REDELIVERS
   the job - which would re-run a PAID DataForSEO pull. Every failure must come back
   as a result dict instead.
2. **Cost pre-check BEFORE the provider call (R5).** A gate decision taken after the
   fetch would already have spent the money it was meant to prevent, so the ORDERING
   is asserted, not just the outcome.
3. **Idempotent.** The bank upsert is keyed by (client, keyword, geo), so a
   redelivery refreshes rows instead of duplicating them.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.keyword_research import tasks as wk
from app.modules.keyword_research.tasks import execute_research, research_keywords
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.keyword_data import FakeKeywordDataProvider, KeywordMetric

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeKeywordStore:
    """In-memory stand-in for the privileged ServiceKeywordStore.

    ``keywords`` is keyed exactly like the real (client_id, keyword, geo) upsert key,
    so "did a re-run duplicate anything?" is answerable by counting the dict.
    """

    def __init__(self, client_names: dict[str, str] | None = None) -> None:
        self.client_names = client_names or {}
        self.clusters: dict[tuple[str | None, str], dict[str, Any]] = {}
        self.keywords: dict[tuple[str | None, str, str | None], dict[str, Any]] = {}
        self.calls: list[str] = []

    def get_client_name(self, client_id: str) -> str | None:
        self.calls.append("get_client_name")
        return self.client_names.get(client_id)

    def upsert_cluster(self, *, client_id: str | None, name: str, **kw: Any) -> str:
        self.calls.append("upsert_cluster")
        key = (client_id, name)
        self.clusters[key] = {"client_id": client_id, "name": name, **kw}
        return f"cu-{abs(hash(key)) % 1000}"

    def upsert_keyword(
        self, *, client_id: str | None, keyword: str, geo: str | None, **kw: Any
    ) -> bool:
        self.calls.append("upsert_keyword")
        key = (client_id, keyword, geo)
        fresh = key not in self.keywords
        self.keywords[key] = {"client_id": client_id, "keyword": keyword, "geo": geo, **kw}
        return fresh


class FakeCostStore:
    """Minimal CostStore: a settable dial + a recorder for what was actually spent."""

    def __init__(self, *, mode: DialMode = "api", halted: bool = False) -> None:
        self._mode = mode
        self._halted = halted
        self.recorded: list[tuple[str, float]] = []

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
        self.recorded.append((ctx.feature_key, cost))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class ExplodingProvider:
    """A provider whose every door raises - the "DataForSEO is down" case."""

    provider = "dataforseo_keywords"

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RuntimeError("dataforseo 500")

    def keyword_ideas(self, seed: str, **kw: Any) -> list[KeywordMetric]:
        raise self._exc

    def related_keywords(self, keyword: str, **kw: Any) -> list[KeywordMetric]:
        raise self._exc

    def keyword_metrics_bulk(self, keywords: list[str], **kw: Any) -> list[KeywordMetric]:
        raise self._exc

    def search_intent(self, keyword: str) -> str | None:
        raise self._exc


class RecordingProvider:
    """Wraps the deterministic fake and logs the ORDER of its calls."""

    provider = "recording"

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self._inner = FakeKeywordDataProvider()

    def keyword_ideas(self, seed: str, **kw: Any) -> list[KeywordMetric]:
        self._log.append("provider.keyword_ideas")
        return self._inner.keyword_ideas(seed, **kw)

    def related_keywords(self, keyword: str, **kw: Any) -> list[KeywordMetric]:
        self._log.append("provider.related_keywords")
        return self._inner.related_keywords(keyword, **kw)

    def keyword_metrics_bulk(self, keywords: list[str], **kw: Any) -> list[KeywordMetric]:
        return self._inner.keyword_metrics_bulk(keywords, **kw)

    def search_intent(self, keyword: str) -> str | None:
        self._log.append("provider.search_intent")
        return self._inner.search_intent(keyword)


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev")


def _gate(store: FakeCostStore) -> CostGate:
    return CostGate(store, _NullCache())


def _run(
    *,
    store: FakeKeywordStore | None = None,
    provider: Any = None,
    cost: FakeCostStore | None = None,
    seed: str = "plumber",
    geo: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    return execute_research(
        store or FakeKeywordStore(),  # type: ignore[arg-type]
        provider or FakeKeywordDataProvider(),
        _gate(cost or FakeCostStore()),
        _settings(),
        seed=seed,
        geo=geo,
        client_id=client_id,
    )


# --------------------------------------------------------------------------- #
# 1. The happy path.
# --------------------------------------------------------------------------- #
def test_a_research_run_banks_the_cluster_and_its_keywords() -> None:
    store = FakeKeywordStore()
    result = _run(store=store)
    assert result["state"] == "ok"
    assert result["seed"] == "plumber"
    assert result["cluster"] == "plumber"
    assert result["keywords"] == len(store.keywords) > 0
    assert result["saved"] == len(store.keywords)  # every row was new
    assert len(store.clusters) == 1


def test_the_run_is_deterministic_on_the_sha256_seeded_fake() -> None:
    # Same seed -> same plan, so a re-run is verifiable and a diff is meaningful.
    assert _run(store=FakeKeywordStore()) == _run(store=FakeKeywordStore())


def test_every_banked_keyword_is_stamped_as_research_sourced() -> None:
    store = FakeKeywordStore()
    _run(store=store)
    for row in store.keywords.values():
        assert row["source"] == "research"
        assert row["provider"] == "fake"  # the seam's label, not a hardcoded string
        assert row["fetched_at"] is not None
        assert row["cluster_id"]  # every researched keyword joins the run's cluster


def test_a_client_scoped_run_snapshots_the_client_name() -> None:
    store = FakeKeywordStore(client_names={"cl-1": "Acme Roofing"})
    _run(store=store, client_id="cl-1", geo="us")
    for row in store.keywords.values():
        assert row["client_id"] == "cl-1"
        assert row["client_name"] == "Acme Roofing"  # the display snapshot travels
        assert row["geo"] == "us"


def test_an_unknown_client_degrades_to_a_blank_snapshot_not_a_crash() -> None:
    # The router 404s an unknown client, so reaching the worker means the client was
    # deleted mid-flight: bank the keywords rather than lose the paid pull.
    store = FakeKeywordStore()
    result = _run(store=store, client_id="cl-gone")
    assert result["state"] == "ok"
    assert all(r["client_name"] == "" for r in store.keywords.values())


def test_the_provider_intent_reaches_the_seed_via_the_cascade() -> None:
    store = FakeKeywordStore()
    _run(store=store, seed="plumber")
    seed_row = next(r for r in store.keywords.values() if r["keyword"] == "plumber")
    # The fake returns a deterministic label for the seed -> the provider step wins.
    assert seed_row["intent_source"] == "provider"
    assert seed_row["intent"] == FakeKeywordDataProvider().search_intent("plumber")


# --------------------------------------------------------------------------- #
# 2. R5 - the cost pre-check runs BEFORE any provider call.
# --------------------------------------------------------------------------- #
def test_the_cost_gate_is_consulted_before_the_provider_is_touched() -> None:
    """The ORDERING is the whole point of a pre-check: gate-then-fetch spends nothing
    on a blocked run, fetch-then-gate has already spent it."""
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
    assert log[1].startswith("provider.")  # ...then the paid pull happens...
    assert log[-1] == "gate.record_cost"  # ...and the spend is committed after.


@pytest.mark.parametrize(
    ("cost_store", "reason"),
    [
        (FakeCostStore(mode="off"), "skip"),
        (FakeCostStore(mode="byhand"), "manual"),
        (FakeCostStore(halted=True), "blocked_daily"),
    ],
)
def test_a_blocked_dial_degrades_with_zero_spend_and_raises_nothing(
    cost_store: FakeCostStore, reason: str
) -> None:
    """A block DEGRADES: an honest partial result, no exception, no provider call, and
    provably no money recorded."""
    store = FakeKeywordStore()
    result = _run(store=store, cost=cost_store, provider=ExplodingProvider())

    assert result == {"state": "blocked", "reason": reason, "saved": 0}
    assert cost_store.recorded == []  # nothing was charged
    assert store.keywords == {} and store.clusters == {}  # nothing was written
    # The provider would have raised if it had been called at all - it was not.


def test_a_blocked_run_never_calls_the_provider() -> None:
    # Belt-and-braces on the ordering: an exploding provider is inert behind an
    # off dial, which is only true if the gate short-circuits first.
    result = _run(cost=FakeCostStore(mode="off"), provider=ExplodingProvider())
    assert result["state"] == "blocked"  # not "error" - the fetch never happened


def test_an_allowed_run_commits_exactly_the_configured_estimate() -> None:
    cost = FakeCostStore()
    _run(cost=cost)
    assert cost.recorded == [("keyword_research", _settings().keyword_research_cost_estimate)]


def test_the_spend_rides_its_own_money_dial() -> None:
    # A dedicated dial lets ops throttle keyword spend without touching content/audit.
    cost = FakeCostStore()
    _run(cost=cost)
    assert cost.recorded[0][0] == "keyword_research"


# --------------------------------------------------------------------------- #
# 3. Failure modes - the core never raises.
# --------------------------------------------------------------------------- #
def test_a_provider_blowup_returns_an_error_result_instead_of_raising() -> None:
    store = FakeKeywordStore()
    result = _run(store=store, provider=ExplodingProvider())  # must not raise
    assert result == {"state": "error", "reason": "provider fetch failed", "saved": 0}
    assert store.keywords == {}  # a half-fetched run banks nothing


def test_a_failed_fetch_is_never_charged() -> None:
    """The commit sits AFTER the fetch, so a provider failure costs $0 - the client is
    not billed for a pull that returned nothing."""
    cost = FakeCostStore()
    _run(cost=cost, provider=ExplodingProvider())
    assert cost.recorded == []


@pytest.mark.parametrize(
    "exc", [RuntimeError("boom"), ValueError("bad json"), TimeoutError("slow"), KeyError("k")]
)
def test_any_provider_exception_type_is_absorbed(exc: Exception) -> None:
    # A bare `except Exception` is only as good as its breadth - prove it.
    assert _run(provider=ExplodingProvider(exc))["state"] == "error"


@pytest.mark.parametrize("seed", ["", "   ", "\t\n"])
def test_an_empty_seed_is_rejected_before_any_spend(seed: str) -> None:
    cost = FakeCostStore()
    result = execute_research(
        FakeKeywordStore(),  # type: ignore[arg-type]
        ExplodingProvider(),
        _gate(cost),
        _settings(),
        seed=seed,
        geo=None,
        client_id=None,
    )
    assert result == {"state": "error", "reason": "empty seed", "saved": 0}
    assert cost.recorded == []  # not even a gate evaluation was charged


def test_the_seed_is_trimmed_before_use() -> None:
    store = FakeKeywordStore()
    result = _run(store=store, seed="  plumber  ")
    assert result["seed"] == "plumber"
    assert ("plumber" in [k[1] for k in store.keywords])


def test_the_pure_core_lets_a_store_failure_propagate_to_its_caller() -> None:
    """Deliberate division of labour: the CORE does not swallow a DB error (a caller
    testing the core must see it), and the TASK wrapper is the layer that guarantees
    no re-raise - pinned in ``test_the_task_never_re_raises_a_store_failure`` below.
    """

    class _BrokenStore(FakeKeywordStore):
        def upsert_keyword(self, **kw: Any) -> bool:
            raise RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        _run(store=_BrokenStore())


# --------------------------------------------------------------------------- #
# 4. Idempotency - a redelivery must not duplicate or double-count.
# --------------------------------------------------------------------------- #
def test_running_twice_upserts_and_never_duplicates() -> None:
    """The property that makes ``task_acks_late`` redelivery safe."""
    store = FakeKeywordStore()
    first = _run(store=store)
    banked = len(store.keywords)

    second = _run(store=store)  # the redelivery
    assert len(store.keywords) == banked  # not one extra row
    assert len(store.clusters) == 1  # nor an extra cluster
    assert second["keywords"] == first["keywords"]
    assert second["saved"] == 0  # ... and no phantom "new saves"
    assert first["saved"] == banked


def test_a_rerun_refreshes_the_metrics_in_place() -> None:
    """A re-run rewrites the SAME row: every derived metric is stable (the provider is
    deterministic), and only ``fetched_at`` moves - which is the point of a refresh.
    """
    store = FakeKeywordStore()
    _run(store=store)
    before = dict(next(iter(store.keywords.values())))
    _run(store=store)
    after = dict(next(iter(store.keywords.values())))

    assert {k: v for k, v in after.items() if k != "fetched_at"} == {
        k: v for k, v in before.items() if k != "fetched_at"
    }
    # The freshness stamp advances, so a stale bank row is always identifiable.
    assert after["fetched_at"] >= before["fetched_at"]


def test_the_same_keyword_for_two_clients_is_two_bank_rows() -> None:
    # The upsert key includes client_id: the SAME term researched for two clients
    # must not collapse into one row.
    store = FakeKeywordStore(client_names={"cl-1": "Acme", "cl-2": "Verde"})
    _run(store=store, client_id="cl-1")
    banked_one = len(store.keywords)
    _run(store=store, client_id="cl-2")
    assert len(store.keywords) == banked_one * 2


def test_the_same_keyword_at_two_geos_is_two_bank_rows() -> None:
    # ... and geo is the third part of the key (demand differs per market).
    store = FakeKeywordStore()
    _run(store=store, geo="us")
    banked_us = len(store.keywords)
    _run(store=store, geo="gb")
    assert len(store.keywords) == banked_us * 2


# --------------------------------------------------------------------------- #
# 5. The Celery entry point - the never-re-raise guarantee.
# --------------------------------------------------------------------------- #
def test_the_task_returns_a_result_dict_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``task_acks_late``, a raise redelivers the job -> a second PAID pull. The
    task must swallow ANY failure, including one from its own wiring."""

    def _boom(_settings: Any) -> Any:
        raise RuntimeError("provider construction failed")

    monkeypatch.setattr(wk, "keyword_data_provider_from_settings", _boom)
    result = research_keywords("plumber")  # called directly - no broker
    assert result == {"state": "error", "reason": "task failed", "saved": 0}


def test_the_task_never_re_raises_a_store_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenStore(FakeKeywordStore):
        def upsert_keyword(self, **kw: Any) -> bool:
            raise RuntimeError("connection reset")

    monkeypatch.setattr(wk, "service_keyword_store", _BrokenStore)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(
        wk, "keyword_data_provider_from_settings", lambda _s: FakeKeywordDataProvider()
    )
    assert research_keywords("plumber")["state"] == "error"  # not a raise


def test_the_task_passes_its_arguments_through_to_the_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeKeywordStore(client_names={"cl-1": "Acme"})
    monkeypatch.setattr(wk, "service_keyword_store", lambda: store)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(
        wk, "keyword_data_provider_from_settings", lambda _s: FakeKeywordDataProvider()
    )
    result = research_keywords("plumber", "us", "cl-1")
    assert result["state"] == "ok"
    row = next(iter(store.keywords.values()))
    assert row["geo"] == "us" and row["client_id"] == "cl-1"


def test_the_task_defaults_geo_and_client_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeKeywordStore()
    monkeypatch.setattr(wk, "service_keyword_store", lambda: store)
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    monkeypatch.setattr(
        wk, "keyword_data_provider_from_settings", lambda _s: FakeKeywordDataProvider()
    )
    assert research_keywords("plumber")["state"] == "ok"  # a bank run needs no client
    row = next(iter(store.keywords.values()))
    assert row["client_id"] is None and row["geo"] is None


def test_the_task_is_registered_under_its_stable_name() -> None:
    # The router enqueues by this name; a rename would silently orphan every job.
    assert research_keywords.name == "research_keywords"


# --------------------------------------------------------------------------- #
# 6. The keyless / degraded provider path.
# --------------------------------------------------------------------------- #
def test_a_keyless_deploy_degrades_to_the_deterministic_fake_and_still_runs() -> None:
    """No DataForSEO credentials is the CURRENT deployed reality: the factory must
    hand back the fake (never None), so the module works rather than crashing."""
    from integrations.keyword_data import keyword_data_provider_from_settings

    settings = _settings()
    assert settings.dataforseo_login is None  # the keyless baseline
    provider = keyword_data_provider_from_settings(settings)
    assert isinstance(provider, FakeKeywordDataProvider)

    store = FakeKeywordStore()
    result = _run(store=store, provider=provider)
    assert result["state"] == "ok" and result["saved"] > 0


def test_the_degraded_path_logs_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    from integrations.keyword_data import keyword_data_provider_from_settings

    settings = Settings(_env_file=None, app_env="dev", dataforseo_login="user")
    with caplog.at_level("INFO"):
        keyword_data_provider_from_settings(settings)  # password missing -> degrade
    assert "user" not in caplog.text  # only the reason is logged, never a credential


def test_a_provider_returning_nothing_yields_an_honest_empty_run() -> None:
    """A configured-but-empty provider (an unknown seed) must bank an empty cluster
    rather than divide by zero or claim saves it did not make."""

    class _EmptyProvider:
        provider = "empty"

        def keyword_ideas(self, seed: str, **kw: Any) -> list[KeywordMetric]:
            return []

        def related_keywords(self, keyword: str, **kw: Any) -> list[KeywordMetric]:
            return []

        def keyword_metrics_bulk(self, keywords: list[str], **kw: Any) -> list[KeywordMetric]:
            return []

        def search_intent(self, keyword: str) -> str | None:
            return None

    store = FakeKeywordStore()
    result = _run(store=store, provider=_EmptyProvider())
    assert result["state"] == "ok"
    assert result["keywords"] == 0 and result["saved"] == 0
    assert store.keywords == {}
