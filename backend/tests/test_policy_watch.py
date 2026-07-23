"""Unit gate for the LIVE Policy-Radar change-detection WATCHER's pure cores, with a
FAKE fetcher + an in-memory fake store + a FakeSummarizer - NO network, NO DB, NO
Celery, NO real provider.

Proves the contract:

* ``detect_change`` is a pure sha256 diff: unchanged text -> False + a stable hash;
  changed text -> True + a different hash.
* the watcher core (``watch_sources`` / ``_watch_one``):
  - no change  -> ONLY ``last_checked`` is touched (``mark_unchanged``); no change_event.
  - empty anchor -> the baseline hash is captured, no change_event.
  - a real diff -> ``record_change`` advances the anchor + flips status='change' and
    appends EXACTLY one change_event.
* the analysis (``analyze_and_store``) with a FakeSummarizer + a real cost gate over a
  spy store:
  - allowed  -> a kb_entry + a recommendation are inserted, the change_event's
    triggered_job is stamped, and gate.commit is called (cost logged, not cached).
  - blocked (dial off) -> NO insert, NO crash, NO spend (degrade); the change_event
    (already recorded) stands alone.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.policy_watch import detect_change, finding_hash
from integrations.llm import FakeSummarizer
from workers.tasks.policy import PolicyWatchStore, analyze_and_store, watch_sources

pytestmark = pytest.mark.unit

SOURCE_ID = "11111111-1111-1111-1111-111111111111"
SOURCE_URL = "https://developers.google.com/search/docs/essentials/spam-policies"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakePolicyStore:
    """In-memory ``PolicyWatchStore`` that records every call for assertions."""

    def __init__(self, sources: list[dict[str, Any]] | None = None) -> None:
        self._sources = sources or []
        self.marked_unchanged: list[str] = []
        self.baselined: list[tuple[str, str]] = []
        self.changes: list[dict[str, Any]] = []
        self.kb_entries: list[dict[str, Any]] = []
        self.recommendations: list[dict[str, Any]] = []
        self.triggered: list[tuple[str, str]] = []

    def claim_due_sources(self, limit: int) -> list[dict[str, Any]]:
        return [dict(s) for s in self._sources[:limit]]

    def mark_unchanged(self, source_id: str) -> None:
        self.marked_unchanged.append(source_id)

    def capture_baseline(self, source_id: str, new_hash: str) -> None:
        self.baselined.append((source_id, new_hash))

    def record_change(
        self, source_id: str, name: str, new_hash: str, summary: str, severity: str, diff_ref: str
    ) -> str:
        cid = f"chg-{len(self.changes) + 1}"
        self.changes.append(
            {
                "id": cid,
                "source_id": source_id,
                "name": name,
                "new_hash": new_hash,
                "summary": summary,
                "severity": severity,
                "diff_ref": diff_ref,
            }
        )
        return cid

    def insert_kb_entry(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {**row, "id": f"kb-{len(self.kb_entries) + 1}"}
        self.kb_entries.append(stored)
        return stored

    def insert_recommendation(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {**row, "id": f"rec-{len(self.recommendations) + 1}"}
        self.recommendations.append(stored)
        return stored

    def set_triggered_job(self, change_event_id: str, kb_job: str) -> None:
        self.triggered.append((change_event_id, kb_job))


class FakeFetcher:
    """A ``PolicyFetcher`` backed by a url -> text mapping (missing url -> None)."""

    def __init__(self, mapping: dict[str, str | None]) -> None:
        self._mapping = mapping

    def fetch(self, url: str) -> str | None:
        return self._mapping.get(url)


class SpyCostStore:
    """A ``CostStore`` whose dial mode is fixed; records every ``record_cost`` (commit)."""

    def __init__(self, mode: DialMode = "api") -> None:
        self._mode = mode
        self.commits: list[tuple[str, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 75.0

    def is_halted(self) -> bool:
        return False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.commits.append((ctx.feature_key, cost, cached))


class NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(mode: DialMode = "api") -> tuple[CostGate, SpyCostStore]:
    store = SpyCostStore(mode=mode)
    return CostGate(store, NullCache()), store


# --------------------------------------------------------------------------- #
# (a) detect_change: pure sha256 changed / unchanged
# --------------------------------------------------------------------------- #
def test_detect_change_unchanged_is_false_with_stable_hash() -> None:
    _, first = detect_change("stable policy text", "")
    changed, again = detect_change("stable policy text", first)
    assert changed is False
    assert again == first  # sha256 is deterministic


def test_detect_change_changed_is_true_with_new_hash() -> None:
    _, old_hash = detect_change("v1 policy content", "")
    changed, new_hash = detect_change("v2 policy content", old_hash)
    assert changed is True
    assert new_hash != old_hash


# --------------------------------------------------------------------------- #
# (b) the watcher core: no-change / baseline / change
# --------------------------------------------------------------------------- #
def test_no_change_only_touches_last_checked() -> None:
    text = "the spam policies, unchanged since last poll"
    _, anchor = detect_change(text, "")
    store = FakePolicyStore(
        [{"id": SOURCE_ID, "name": "Spam Policies", "url": SOURCE_URL, "last_hash": anchor}]
    )
    gate, _ = _gate("api")

    out = watch_sources(
        store,
        fetcher=FakeFetcher({SOURCE_URL: text}),
        settings=_settings(),
        summarizer=None,
        gate=gate,
    )

    assert store.marked_unchanged == [SOURCE_ID]  # only last_checked touched
    assert store.changes == []  # no change_event
    assert store.kb_entries == [] and store.recommendations == []
    assert out.unchanged == 1 and out.changed == 0


def test_empty_anchor_captures_baseline_without_a_change_event() -> None:
    store = FakePolicyStore(
        [{"id": SOURCE_ID, "name": "Spam Policies", "url": SOURCE_URL, "last_hash": ""}]
    )
    gate, _ = _gate("api")

    out = watch_sources(
        store,
        fetcher=FakeFetcher({SOURCE_URL: "first observation of this source"}),
        settings=_settings(),
        summarizer=None,
        gate=gate,
    )

    assert len(store.baselined) == 1
    assert store.baselined[0][0] == SOURCE_ID
    assert store.changes == []  # baseline is NOT a change
    assert out.baselined == 1 and out.changed == 0


def test_change_records_one_change_event_and_advances_anchor() -> None:
    old_text = "old spam policy language"
    new_text = "NEW spam policy language about scaled AI content"
    _, old_anchor = detect_change(old_text, "")
    _, new_anchor = detect_change(new_text, "")
    store = FakePolicyStore(
        [{"id": SOURCE_ID, "name": "Spam Policies", "url": SOURCE_URL, "last_hash": old_anchor}]
    )
    gate, _ = _gate("api")

    out = watch_sources(
        store,
        fetcher=FakeFetcher({SOURCE_URL: new_text}),
        settings=_settings(),
        summarizer=None,  # no key -> analysis degrades; the change_event still stands
        gate=gate,
    )

    assert len(store.changes) == 1  # EXACTLY one change_event
    change = store.changes[0]
    assert change["source_id"] == SOURCE_ID
    assert change["new_hash"] == new_anchor  # anchor advanced to the new content hash
    assert change["severity"] == "info"  # neutral default before analysis
    assert store.marked_unchanged == []  # a change is NOT a mark_unchanged
    assert out.changed == 1
    # summarizer None -> analysis degraded, no KB / rec written.
    assert store.kb_entries == [] and store.recommendations == []
    assert out.degraded == 1


def test_unreachable_source_marks_unchanged_and_never_crashes() -> None:
    store = FakePolicyStore(
        [{"id": SOURCE_ID, "name": "Spam Policies", "url": SOURCE_URL, "last_hash": "abc"}]
    )
    gate, _ = _gate("api")

    out = watch_sources(
        store,
        fetcher=FakeFetcher({SOURCE_URL: None}),  # fetch failed / non-200
        settings=_settings(),
        summarizer=None,
        gate=gate,
    )

    assert store.marked_unchanged == [SOURCE_ID]  # retried next tick, no change
    assert store.changes == []
    assert out.unchanged == 1


# --------------------------------------------------------------------------- #
# (c) analysis: allowed inserts KB + rec + commits; blocked degrades (no insert)
# --------------------------------------------------------------------------- #
def test_analysis_allowed_inserts_kb_and_rec_and_commits() -> None:
    store = FakePolicyStore()
    gate, cost = _gate("api")

    out = analyze_and_store(
        store,
        summarizer=FakeSummarizer(),
        gate=gate,
        settings=_settings(),
        source_id=SOURCE_ID,
        source_name="Spam Policies",
        source_url=SOURCE_URL,
        change_event_id="chg-1",
        summary="Detected an update to Spam Policies.",
        text="Some changed policy content about spam and scaled AI content.",
    )

    assert out.state == "analyzed"
    assert len(store.kb_entries) == 1
    assert len(store.recommendations) == 1
    kb = store.kb_entries[0]
    rec = store.recommendations[0]
    # the KB entry carries a clamped-to-vocabulary severity/category/region.
    assert kb["severity"] in {"critical", "major", "minor", "info"}
    assert kb["category"] in {"algorithm", "policy", "technical", "content", "local", "geo"}
    # the recommendation links back to the KB entry + carries a live kb_ref.
    assert rec["kb_entry_id"] == kb["id"]
    assert rec["kb_ref"].startswith("kb-live-")
    assert rec["kb_ref"] == f"kb-live-{finding_hash(SOURCE_URL, kb['title'], kb['summary'])[:8]}"
    assert rec["status"] == "new"
    # the change_event was stamped with the KB job (the triggered_job hook).
    assert store.triggered == [("chg-1", rec["kb_ref"])]
    # gate.commit fired exactly once: the policy feature, the estimate, NOT cached.
    assert cost.commits == [("policy", pytest.approx(0.01), False)]


def test_analysis_blocked_by_dial_off_degrades_without_insert() -> None:
    store = FakePolicyStore()
    gate, cost = _gate("off")  # dial off -> gate returns skip, no spend

    out = analyze_and_store(
        store,
        summarizer=FakeSummarizer(),
        gate=gate,
        settings=_settings(),
        source_id=SOURCE_ID,
        source_name="Spam Policies",
        source_url=SOURCE_URL,
        change_event_id="chg-1",
        summary="Detected an update to Spam Policies.",
        text="content that will never reach the provider",
    )

    assert out.state == "degraded"
    assert store.kb_entries == [] and store.recommendations == []  # NO insert
    assert store.triggered == []  # nothing stamped
    assert cost.commits == []  # NO spend logged (blocked before the call)


def test_analysis_no_key_degrades_without_insert_or_spend() -> None:
    store = FakePolicyStore()
    gate, cost = _gate("api")

    out = analyze_and_store(
        store,
        summarizer=None,  # no Anthropic key -> degrade
        gate=gate,
        settings=_settings(),
        source_id=SOURCE_ID,
        source_name="Spam Policies",
        source_url=SOURCE_URL,
        change_event_id="chg-1",
        summary="Detected an update.",
        text="content",
    )

    assert out.state == "degraded"
    assert store.kb_entries == [] and store.recommendations == []
    assert cost.commits == []  # the gate was never even consulted


# --------------------------------------------------------------------------- #
# The fakes structurally satisfy the store Protocol (compile-time-ish check).
# --------------------------------------------------------------------------- #
def test_fake_store_satisfies_protocol() -> None:
    store: PolicyWatchStore = FakePolicyStore()
    assert store is not None
