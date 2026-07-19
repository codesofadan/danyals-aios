"""Site-analytics workers: the hold ladder, never-re-raise, gate-first.

NO DB, NO network, NO broker: the store is in-memory, the cost gate runs on a fake
``CostStore``, and the reader is an injected fake (mirrors
``local_seo.tasks``'s ``execute_gbp_sync`` / ``reader`` pattern exactly). The Celery
tasks are invoked as plain functions - ``.delay`` is never called.

Unlike ``sync_gbp_profile`` (approval-gated - a token-less deploy is the EXPECTED
long-term state), GSC/GA4 are standard OAuth: no key is the expected state ONLY until
Danyal loads a Google Cloud OAuth client, and a connected-but-failing property is a
real problem (ERROR, never HELD). Both properties pinned here:

* no OAuth client configured -> HELD (``no_oauth_client``), nothing written.
* configured but the property never connected -> HELD (``no_oauth_token``).
* connected but the reader reports a dangling vault ref (``None``) -> HELD
  (``no_oauth_token``) - a hold, not a crash.
* the reader raises -> ERROR, never HELD, and nothing written.
* a gate block DEGRADES (``blocked``), never calls the reader.
* Never re-raise (``task_acks_late`` would redeliver -> a second paid-adjacent pull).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.site_analytics import tasks as wk
from app.modules.site_analytics.repo import ServiceSiteAnalyticsStore
from app.modules.site_analytics.tasks import (
    execute_ga4_sync,
    execute_gsc_sync,
    sync_ga4_property,
    sync_gsc_property,
)
from app.schemas.cost import DIAL_KEYS
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.ga4 import GA4Summary
from integrations.gsc import SearchConsoleSummary

pytestmark = pytest.mark.unit

_CLIENT = "cl-1"
_PROP = "prop-1"


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeSiteAnalyticsStore:
    """In-memory stand-in for the privileged ServiceSiteAnalyticsStore.

    ``gsc_syncs``/``ga4_syncs`` record every write, so "did a HELD/ERROR path write
    anything?" is answerable by counting them.
    """

    def __init__(self, *, gsc_row: dict[str, Any] | None = None, ga4_row: dict[str, Any] | None = None) -> None:
        self.gsc_row = _gsc_row() if gsc_row is None else gsc_row
        self.ga4_row = _ga4_row() if ga4_row is None else ga4_row
        self.gsc_syncs: list[dict[str, Any]] = []
        self.ga4_syncs: list[dict[str, Any]] = []

    def gsc_for_sync(self, property_id: str) -> dict[str, Any] | None:
        return self.gsc_row if property_id == _PROP and self.gsc_row is not None else None

    def ga4_for_sync(self, property_id: str) -> dict[str, Any] | None:
        return self.ga4_row if property_id == _PROP and self.ga4_row is not None else None

    def update_gsc_sync(self, property_id: str, **kw: Any) -> None:
        self.gsc_syncs.append({"property_id": property_id, **kw})

    def update_ga4_sync(self, property_id: str, **kw: Any) -> None:
        self.ga4_syncs.append({"property_id": property_id, **kw})


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


def _gsc_row(**over: Any) -> dict[str, Any]:
    row = {
        "id": _PROP, "client_id": _CLIENT, "site_url": "https://verde.example/",
        "oauth_connected": False, "oauth_vault_ref": None,
    }
    row.update(over)
    return row


def _ga4_row(**over: Any) -> dict[str, Any]:
    row = {
        "id": _PROP, "client_id": _CLIENT, "property_id": "properties/123",
        "oauth_connected": False, "oauth_vault_ref": None,
    }
    row.update(over)
    return row


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(store: FakeCostStore | None = None) -> CostGate:
    return CostGate(store or FakeCostStore(), _NullCache())


def _connected_gsc_row() -> dict[str, Any]:
    return _gsc_row(oauth_connected=True, oauth_vault_ref="vault-key-1")


def _connected_ga4_row() -> dict[str, Any]:
    return _ga4_row(oauth_connected=True, oauth_vault_ref="vault-key-1")


_SUMMARY = SearchConsoleSummary(clicks=120, impressions=4000, ctr=0.03, avg_position=8.2, top_queries=[])
_GA4_SUMMARY = GA4Summary(sessions=500, users=350, conversions=12)


# --------------------------------------------------------------------------- #
# 1. GSC hold ladder.
# --------------------------------------------------------------------------- #
def test_gsc_sync_holds_with_no_oauth_client() -> None:
    """The EXPECTED baseline: a keyless deploy holds cleanly rather than crashing,
    and the module stays connectable the moment Danyal loads one Google OAuth
    client (unlike GBP, this is not approval-gated)."""
    store = FakeSiteAnalyticsStore()
    settings = _settings()
    assert settings.google_oauth_client_id is None  # the keyless baseline

    result = execute_gsc_sync(store, settings, _gate(), property_id=_PROP)  # type: ignore[arg-type]
    assert result == {"state": "held", "reason": "no_oauth_client", "held": True}
    assert store.gsc_syncs == []  # a hold writes nothing


def test_gsc_sync_holds_when_the_property_was_never_connected() -> None:
    """OAuth client configured, but this PROPERTY never completed the consent
    flow: the row's oauth_connected/oauth_vault_ref are absent, so it HOLDS
    rather than reaching for a reader at all."""
    store = FakeSiteAnalyticsStore()  # default row: oauth_connected=False
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_gsc_sync(store, settings, _gate(), property_id=_PROP)  # type: ignore[arg-type]
    assert result == {"state": "held", "reason": "no_oauth_token", "held": True}
    assert store.gsc_syncs == []


def test_gsc_sync_holds_when_the_reader_reports_a_dangling_vault_ref() -> None:
    """Connected in the DB, but the sealed token itself is gone (reveal_secret finds
    nothing) - the reader signals this by returning None, and it is a HOLD, not an
    error, mirroring sync_gbp_profile's reader contract."""
    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_gsc_sync(
        store, settings, _gate(), property_id=_PROP, reader=lambda _row, _s: None
    )
    assert result == {"state": "held", "reason": "no_oauth_token", "held": True}
    assert store.gsc_syncs == []


def test_gsc_sync_writes_back_a_successful_read() -> None:
    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_gsc_sync(
        store, settings, _gate(), property_id=_PROP, reader=lambda _row, _s: _SUMMARY
    )
    assert result == {"state": "ok", "reason": "", "held": False, "clicks": 120}
    written = store.gsc_syncs[0]
    assert written["clicks"] == 120 and written["impressions"] == 4000
    assert written["avg_position"] == 8.2


def test_a_failing_gsc_reader_is_an_error_that_never_raises_and_writes_nothing() -> None:
    def _boom(_row: dict[str, Any], _s: Settings) -> SearchConsoleSummary:
        raise RuntimeError("gsc 500")

    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_gsc_sync(store, settings, _gate(), property_id=_PROP, reader=_boom)
    assert result == {"state": "error", "reason": "gsc read failed", "held": False}
    assert store.gsc_syncs == []


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("bad json"), TimeoutError("slow"), KeyError("k")])
def test_any_gsc_reader_exception_type_is_absorbed_without_a_write(exc: Exception) -> None:
    def _boom(_row: dict[str, Any], _s: Settings) -> SearchConsoleSummary:
        raise exc

    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_gsc_sync(store, settings, _gate(), property_id=_PROP, reader=_boom)
    assert result["state"] == "error" and store.gsc_syncs == []


def test_gsc_sync_reports_unknown_property_as_an_error_not_a_crash() -> None:
    store = FakeSiteAnalyticsStore()
    store.gsc_row = None  # simulate "no such property" (mirrors FakeLocalStore.profiles.clear())
    result = execute_gsc_sync(store, _settings(), _gate(), property_id=_PROP)  # type: ignore[arg-type]
    assert result == {"state": "error", "reason": "unknown property", "held": False}


def test_gsc_sync_is_gated_before_any_reader_call() -> None:
    """A dial block DEGRADES - the reader must never even run, and nothing is spent
    or written."""
    called = False

    def _reader(_row: dict[str, Any], _s: Settings) -> SearchConsoleSummary:
        nonlocal called
        called = True
        return _SUMMARY

    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_gsc_sync(
        store, settings, _gate(FakeCostStore(mode="off")), property_id=_PROP, reader=_reader
    )
    assert result["state"] == "blocked"
    assert called is False
    assert store.gsc_syncs == []


def test_gsc_sync_commits_cost_to_the_rows_client() -> None:
    cost = FakeCostStore()
    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    execute_gsc_sync(store, settings, _gate(cost), property_id=_PROP, reader=lambda _r, _s: _SUMMARY)
    assert cost.recorded == [("site_analytics", _CLIENT, settings.site_analytics_cost_estimate)]


def test_a_failed_gsc_read_is_never_charged() -> None:
    cost = FakeCostStore()
    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")

    def _boom(_row: dict[str, Any], _s: Settings) -> SearchConsoleSummary:
        raise RuntimeError("boom")

    execute_gsc_sync(store, settings, _gate(cost), property_id=_PROP, reader=_boom)
    assert cost.recorded == []


# --------------------------------------------------------------------------- #
# 2. GA4 hold ladder - mirrors GSC exactly.
# --------------------------------------------------------------------------- #
def test_ga4_sync_holds_with_no_oauth_client() -> None:
    store = FakeSiteAnalyticsStore()
    result = execute_ga4_sync(store, _settings(), _gate(), property_id=_PROP)  # type: ignore[arg-type]
    assert result == {"state": "held", "reason": "no_oauth_client", "held": True}
    assert store.ga4_syncs == []


def test_ga4_sync_holds_when_the_property_was_never_connected() -> None:
    store = FakeSiteAnalyticsStore()
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_ga4_sync(store, settings, _gate(), property_id=_PROP)  # type: ignore[arg-type]
    assert result == {"state": "held", "reason": "no_oauth_token", "held": True}


def test_ga4_sync_holds_when_the_reader_reports_a_dangling_vault_ref() -> None:
    store = FakeSiteAnalyticsStore(ga4_row=_connected_ga4_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_ga4_sync(store, settings, _gate(), property_id=_PROP, reader=lambda _r, _s: None)
    assert result == {"state": "held", "reason": "no_oauth_token", "held": True}
    assert store.ga4_syncs == []


def test_ga4_sync_writes_back_a_successful_read() -> None:
    store = FakeSiteAnalyticsStore(ga4_row=_connected_ga4_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_ga4_sync(
        store, settings, _gate(), property_id=_PROP, reader=lambda _r, _s: _GA4_SUMMARY
    )
    assert result == {"state": "ok", "reason": "", "held": False, "sessions": 500}
    assert store.ga4_syncs[0]["users"] == 350 and store.ga4_syncs[0]["conversions"] == 12


def test_a_failing_ga4_reader_is_an_error_that_never_raises_and_writes_nothing() -> None:
    def _boom(_row: dict[str, Any], _s: Settings) -> GA4Summary:
        raise RuntimeError("ga4 500")

    store = FakeSiteAnalyticsStore(ga4_row=_connected_ga4_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")
    result = execute_ga4_sync(store, settings, _gate(), property_id=_PROP, reader=_boom)
    assert result == {"state": "error", "reason": "ga4 read failed", "held": False}
    assert store.ga4_syncs == []


def test_ga4_sync_reports_unknown_property_as_an_error_not_a_crash() -> None:
    store = FakeSiteAnalyticsStore()
    store.ga4_row = None  # simulate "no such property"
    result = execute_ga4_sync(store, _settings(), _gate(), property_id=_PROP)  # type: ignore[arg-type]
    assert result == {"state": "error", "reason": "unknown property", "held": False}


# --------------------------------------------------------------------------- #
# 3. The dial is registered - the e8964de lesson.
# --------------------------------------------------------------------------- #
def test_the_site_analytics_dial_is_registered() -> None:
    """An unregistered feature key makes dial_mode() fall back to "off" AND makes
    PATCH /cost/dials reject it - the module would be unswitchable-on. Every
    _FEATURE this module's tasks pass to a GateContext MUST be a real dial key."""
    assert wk._FEATURE in DIAL_KEYS


# --------------------------------------------------------------------------- #
# 4. The Celery entry points never re-raise.
# --------------------------------------------------------------------------- #
def test_the_gsc_sync_task_never_re_raises_even_on_store_construction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer guard (mirrors sync_gbp_profile) catches EVERYTHING, not just a
    reader failure - a store/settings/gate CONSTRUCTION failure must not escape
    either, or task_acks_late redelivers and double-processes."""

    def _boom() -> ServiceSiteAnalyticsStore:
        raise RuntimeError("store construction failed")

    monkeypatch.setattr(wk, "service_site_analytics_store", _boom)
    assert sync_gsc_property(_PROP) == {"state": "error", "reason": "task failed", "held": False}


def test_the_ga4_sync_task_never_re_raises_even_on_store_construction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> ServiceSiteAnalyticsStore:
        raise RuntimeError("store construction failed")

    monkeypatch.setattr(wk, "service_site_analytics_store", _boom)
    assert sync_ga4_property(_PROP) == {"state": "error", "reason": "task failed", "held": False}


def test_execute_gsc_sync_never_raises_on_a_boom_reader() -> None:
    store = FakeSiteAnalyticsStore(gsc_row=_connected_gsc_row())
    settings = _settings(google_oauth_client_id="id", google_oauth_client_secret="secret")

    def _boom(_row: dict[str, Any], _s: Settings) -> SearchConsoleSummary:
        raise RuntimeError("network exploded")

    # No exception escapes - task_acks_late would otherwise redeliver.
    result = execute_gsc_sync(store, settings, _gate(), property_id=_PROP, reader=_boom)
    assert result["state"] == "error"
