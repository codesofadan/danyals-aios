"""P6B-7 gate: the CONTEXT COMPACTION WORKER's pure core, with a FAKE store +
fake/gated providers - no Celery, no DB, no network.

Proves the exactly-once-ish, never-block, never-double-spend contract:

* N events on one entity => EXACTLY ONE compaction; watermark advances to max seq;
  facts + summary reflect the events; the dirty claim is cleared.
* redelivery (watermark already caught up) => no-op, version NOT bumped, no
  provider calls, dirty cleared.
* an event lands mid-fold (dirty.last_seq > the folded watermark) => the dirty row
  is left PENDING (re-armed), NOT cleared.
* degraded (providers=None) => status='degraded', watermark HELD, dirty re-armed
  with a positive backoff, and the provider is never touched.
* ContextSpendBlocked from the gated providers => SAME degraded handling, no crash,
  provider inner never reached.
* an unexpected error => status='error', NOT re-raised, no half-write (the summary
  is never written).
* the dispatch_due claim/fan-out (SKIP LOCKED batch) drives one enqueue per claim.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.context_cost import ContextSpendBlocked, GatedEmbedder, GatedSummarizer
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.context_providers import ContextProviders, providers_for_tests
from workers.tasks.context import (
    CompactionOutcome,
    ContextStore,
    dispatch_due,
    execute_compaction,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# A fake ContextStore: an in-memory entity_context row + activity events +
# a single-entity context_dirty row, plus the vector ledger (for sync_vectors).
# --------------------------------------------------------------------------- #
class FakeContextStore:
    """In-memory ``ContextStore`` for the pure core (mirrors the repo's semantics)."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.context: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = events or []
        # context_dirty: last_seq + a flag for whether the row exists.
        self.dirty_last: int | None = max((e["seq"] for e in self.events), default=0) or None
        self.dirty_exists = True
        self.rearms: list[dict[str, Any]] = []
        self.cleared = 0
        self.upserts: list[dict[str, Any]] = []
        self.ledger: dict[str, dict[str, Any]] = {}

    # --- entity_context ---
    def get_context_for_update(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return self.context

    def upsert_context(
        self,
        entity_type: str,
        entity_id: str,
        *,
        summary: str = "",
        facts: dict[str, Any] | None = None,
        token_budget: int = 1200,
        token_count: int = 0,
        event_watermark: int = 0,
        status: str = "summarized",
        model: str = "",
        checksum: str = "",
    ) -> dict[str, Any]:
        prior_version = int(self.context["version"]) if self.context else 0
        prior_watermark = int(self.context["event_watermark"]) if self.context else 0
        is_insert = self.context is None
        row = {
            "id": "ctx-1",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "summary": summary,
            "facts": dict(facts or {}),
            "token_budget": token_budget,
            "token_count": token_count,
            "event_watermark": max(prior_watermark, event_watermark),  # greatest()
            "status": status,
            "model": model,
            "checksum": checksum,
            "version": prior_version if is_insert else prior_version + 1,
        }
        self.context = row
        self.upserts.append(dict(row))
        return dict(row)

    # --- activity events ---
    def events_after(self, entity_type: str, entity_id: str, watermark: int) -> list[dict[str, Any]]:
        return [e for e in self.events if int(e["seq"]) > watermark]

    # --- context_dirty ---
    def dirty_last_seq(self, entity_type: str, entity_id: str) -> int | None:
        return self.dirty_last if self.dirty_exists else None

    def clear_dirty(self, entity_type: str, entity_id: str) -> None:
        self.dirty_exists = False
        self.cleared += 1

    def rearm_dirty(
        self, entity_type: str, entity_id: str, *, last_seq: int, backoff_seconds: int
    ) -> None:
        self.dirty_exists = True
        self.dirty_last = max(self.dirty_last or 0, last_seq)
        self.rearms.append({"last_seq": last_seq, "backoff_seconds": backoff_seconds})

    def claim_due_dirty(self, limit: int) -> list[dict[str, Any]]:  # not exercised by the core
        return []

    # --- vector ledger (sync_vectors writes through here) ---
    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return list(self.ledger.values())

    def record_vector(
        self,
        entity_type: str,
        entity_id: str,
        *,
        chunk_key: str,
        pinecone_id: str,
        content_checksum: str,
        version: int,
        dim: int,
        model: str,
    ) -> dict[str, Any]:
        row = {
            "chunk_key": chunk_key,
            "pinecone_id": pinecone_id,
            "content_checksum": content_checksum,
            "version": version,
            "dim": dim,
            "model": model,
        }
        self.ledger[chunk_key] = row
        return dict(row)

    def delete_vector(
        self, entity_type: str, entity_id: str, chunk_key: str
    ) -> dict[str, Any] | None:
        return self.ledger.pop(chunk_key, None)


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "context_summary_token_budget": 1200,
        "context_max_facts": 64,
        "context_backoff_seconds": 300,
        "context_dispatch_batch": 100,
    }
    base.update(over)
    return Settings(_env_file=None, app_env="dev", **base)


def _event(seq: int, *, kind: str = "client", action: str = "updated", target: str = "acme") -> dict[str, Any]:
    return {"seq": seq, "kind": kind, "action": action, "target": target, "meta": None, "created_at": None}


ENTITY = ("client", "11111111-1111-1111-1111-111111111111")


# --------------------------------------------------------------------------- #
# 1. N events => exactly one compaction; watermark = max seq; facts populated
# --------------------------------------------------------------------------- #
def test_n_events_one_compaction_advances_watermark() -> None:
    events = [
        _event(10, kind="audit", action="ran audit", target="https://acme.com"),
        _event(11, kind="client", action="set tier", target="acme", ),
        _event(12, kind="task", action="closed", target="onboarding"),
    ]
    events[1]["meta"] = "Growth"  # tier value
    store = FakeContextStore(events)
    providers = providers_for_tests()

    out = execute_compaction(store, providers, *ENTITY, settings=_settings())

    assert out.state == "summarized"
    assert out.events_folded == 3
    assert out.watermark == 12  # advanced to the max seq
    assert store.context is not None
    assert int(store.context["event_watermark"]) == 12
    assert store.context["status"] == "summarized"
    # facts reflect the events (deterministic fold: last-writer-wins keyed facts).
    facts = store.context["facts"]
    assert facts["last_audit"] == "https://acme.com"
    assert facts["tier"] == "Growth"
    assert facts["last_task"] == "closed onboarding"
    assert store.context["summary"]  # bounded prose written
    # EXACTLY ONE summarizing upsert (the pre-create + the fold => 2 upserts total,
    # but only one carries status='summarized').
    summarized = [u for u in store.upserts if u["status"] == "summarized"]
    assert len(summarized) == 1
    # dirty claim drained (no new events arrived mid-fold).
    assert store.cleared == 1 and store.dirty_exists is False
    assert out.redirtied is False
    # vectors were synced (summary chunk + fact-group chunks).
    assert store.ledger and "summary" in store.ledger


# --------------------------------------------------------------------------- #
# 2. Redelivery (watermark already caught up) => no-op, no version bump
# --------------------------------------------------------------------------- #
def test_redelivery_is_a_noop_no_version_bump() -> None:
    store = FakeContextStore([_event(5)])
    # Seed an already-summarized context whose watermark >= the only event.
    store.context = {
        "id": "ctx-1", "entity_type": ENTITY[0], "entity_id": ENTITY[1],
        "summary": "prior", "facts": {"tier": "Growth"}, "token_budget": 1200,
        "token_count": 3, "event_watermark": 5, "status": "summarized",
        "model": "fake-summary", "checksum": "abc", "version": 4,
    }
    providers = providers_for_tests()

    out = execute_compaction(store, providers, *ENTITY, settings=_settings())

    assert out.state == "unchanged"
    assert out.version == 4  # NOT bumped
    assert store.upserts == []  # no write at all
    assert store.cleared == 1  # the claim is drained
    assert store.ledger == {}  # no embedding


# --------------------------------------------------------------------------- #
# 3. Event arrives mid-fold => dirty row left PENDING (re-armed), not cleared
# --------------------------------------------------------------------------- #
def test_event_mid_fold_leaves_dirty_pending() -> None:
    store = FakeContextStore([_event(7)])
    providers = providers_for_tests()

    # now_seq_source simulates the trigger bumping context_dirty.last_seq to 9
    # (a new event) while we were folding up to seq 7.
    out = execute_compaction(
        store, providers, *ENTITY, settings=_settings(), now_seq_source=lambda: 9
    )

    assert out.state == "summarized"
    assert out.watermark == 7
    assert out.redirtied is True
    assert store.cleared == 0  # NOT cleared
    assert store.dirty_exists is True
    # re-armed pending + immediately eligible (backoff 0) so the next tick re-folds.
    assert store.rearms[-1] == {"last_seq": 9, "backoff_seconds": 0}


# --------------------------------------------------------------------------- #
# 4. Degraded (providers=None) => status='degraded', watermark HELD, backoff re-arm
# --------------------------------------------------------------------------- #
def test_degraded_holds_watermark_and_rearms_with_backoff() -> None:
    store = FakeContextStore([_event(3), _event(4)])
    store.context = {
        "id": "ctx-1", "entity_type": ENTITY[0], "entity_id": ENTITY[1],
        "summary": "prior prose", "facts": {"tier": "Free"}, "token_budget": 1200,
        "token_count": 2, "event_watermark": 0, "status": "pending",
        "model": "", "checksum": "", "version": 1,
    }

    out = execute_compaction(store, None, *ENTITY, settings=_settings())

    assert out.state == "degraded"
    assert out.watermark == 0  # HELD (not advanced to 4)
    assert store.context["status"] == "degraded"
    assert int(store.context["event_watermark"]) == 0  # greatest kept it at 0
    assert store.context["summary"] == "prior prose"  # prior carried forward
    # re-armed pending with the configured POSITIVE backoff (no hot spin).
    assert store.rearms[-1] == {"last_seq": 4, "backoff_seconds": 300}
    assert store.cleared == 0


def test_degraded_does_not_churn_version_when_already_degraded() -> None:
    store = FakeContextStore([_event(4)])
    store.context = {
        "id": "ctx-1", "entity_type": ENTITY[0], "entity_id": ENTITY[1],
        "summary": "p", "facts": {}, "token_budget": 1200, "token_count": 0,
        "event_watermark": 0, "status": "degraded", "model": "", "checksum": "",
        "version": 2,
    }

    out = execute_compaction(store, None, *ENTITY, settings=_settings())

    assert out.state == "degraded"
    assert store.upserts == []  # already degraded => no re-write, version untouched
    assert store.context["version"] == 2
    assert store.rearms[-1]["backoff_seconds"] == 300  # still re-armed for retry


# --------------------------------------------------------------------------- #
# 5. ContextSpendBlocked => same degraded handling, provider never reached
# --------------------------------------------------------------------------- #
class _CountingCostStore:
    """A gate store whose dial is 'off' => every evaluate blocks (no spend)."""

    def __init__(self, mode: DialMode = "off") -> None:
        self._mode = mode

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
        return None


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class _SpySummarizer:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> Any:
        self.calls += 1
        raise AssertionError("provider must never be reached when the gate blocks")


class _SpyEmbedder:
    dim = 1024

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        raise AssertionError("embedder must never be reached when the gate blocks")


def _gated_blocking_bundle() -> tuple[ContextProviders, _SpySummarizer, _SpyEmbedder]:
    base = providers_for_tests()
    gate = CostGate(_CountingCostStore(mode="off"), _NullCache())
    settings = _settings()
    sum_spy = _SpySummarizer()
    emb_spy = _SpyEmbedder()
    from dataclasses import replace

    gated = replace(
        base,
        summarizer=GatedSummarizer(sum_spy, gate, settings=settings, client_id=None),
        embedder=GatedEmbedder(emb_spy, gate, settings=settings, client_id=None),
    )
    return gated, sum_spy, emb_spy


def test_spend_blocked_degrades_without_crashing() -> None:
    store = FakeContextStore([_event(8)])
    gated, sum_spy, emb_spy = _gated_blocking_bundle()

    out = execute_compaction(store, gated, *ENTITY, settings=_settings())

    assert out.state == "degraded"
    assert out.watermark == 0  # held (no prior row => watermark 0)
    assert sum_spy.calls == 0  # ContextSpendBlocked raised BEFORE the provider call
    assert emb_spy.calls == 0
    assert store.rearms[-1]["backoff_seconds"] == 300
    # No summarized write happened -> no half-write.
    assert all(u["status"] != "summarized" for u in store.upserts)


def test_spend_blocked_raises_context_spend_blocked_directly() -> None:
    """Sanity: the gated summarizer really does raise the typed signal we catch."""
    gated, _, _ = _gated_blocking_bundle()
    with pytest.raises(ContextSpendBlocked):
        gated.summarizer.summarize("x", model="m", max_tokens=10)


# --------------------------------------------------------------------------- #
# 6. Unexpected error => status='error', not re-raised, no half-write
# --------------------------------------------------------------------------- #
class _ExplodingProviders:
    """A providers bundle whose summarizer raises a NON-spend error mid-fold."""

    model_summary = "boom-model"

    class _Boom:
        def summarize(self, prompt: str, *, model: str, max_tokens: int) -> Any:
            raise RuntimeError("summarizer exploded")

    def __init__(self) -> None:
        self.summarizer = self._Boom()


def test_unexpected_error_marks_error_and_never_reraises() -> None:
    store = FakeContextStore([_event(6)])
    # A providers object that will explode inside compact() (unexpected, not a
    # ContextSpendBlocked). We only need .summarizer + .model_summary before it blows.
    bad = _ExplodingProviders()

    out = execute_compaction(store, bad, *ENTITY, settings=_settings())  # must NOT raise

    assert out.state == "error"
    assert "summarizer exploded" in out.reason
    # status flipped to 'error'; the summary was NEVER written (no half-write).
    assert store.context is not None and store.context["status"] == "error"
    assert all(u["status"] != "summarized" for u in store.upserts)
    # re-armed with backoff for a later retry.
    assert store.rearms[-1]["backoff_seconds"] == 300


# --------------------------------------------------------------------------- #
# 7. dispatch_due: claim (SKIP LOCKED batch) => one enqueue per claim
# --------------------------------------------------------------------------- #
class _ClaimStore:
    def __init__(self, rows: list[dict[str, Any]], *, limit_seen: list[int]) -> None:
        self._rows = rows
        self._limit_seen = limit_seen

    def claim_due_dirty(self, limit: int) -> list[dict[str, Any]]:
        self._limit_seen.append(limit)
        return self._rows[:limit]


def test_dispatch_due_enqueues_one_per_claimed_row() -> None:
    rows = [
        {"entity_type": "client", "entity_id": "c-1", "last_seq": 3},
        {"entity_type": "site", "entity_id": "s-2", "last_seq": 9},
    ]
    limit_seen: list[int] = []
    store = _ClaimStore(rows, limit_seen=limit_seen)
    enqueued: list[tuple[str, str]] = []

    dispatched = dispatch_due(
        store, batch=50, enqueue=lambda et, eid: enqueued.append((et, eid))  # type: ignore[arg-type]
    )

    assert limit_seen == [50]  # the batch cap is passed straight to the claim
    assert dispatched == [("client", "c-1"), ("site", "s-2")]
    assert enqueued == [("client", "c-1"), ("site", "s-2")]  # exactly one per claim


def test_dispatch_due_empty_claim_enqueues_nothing() -> None:
    store = _ClaimStore([], limit_seen=[])
    enqueued: list[tuple[str, str]] = []
    dispatched = dispatch_due(store, batch=10, enqueue=lambda et, eid: enqueued.append((et, eid)))  # type: ignore[arg-type]
    assert dispatched == []
    assert enqueued == []


# --------------------------------------------------------------------------- #
# The outcome is JSON-serializable (the Celery task returns as_dict()).
# --------------------------------------------------------------------------- #
def test_outcome_as_dict_is_serializable() -> None:
    out = CompactionOutcome("client", "c-1", "summarized", version=2, watermark=9, events_folded=3)
    d = out.as_dict()
    assert d["state"] == "summarized" and d["watermark"] == 9 and d["events_folded"] == 3


# The fake structurally satisfies the ContextStore Protocol (compile-time-ish check).
def test_fake_store_satisfies_protocol() -> None:
    store: ContextStore = FakeContextStore()
    assert store is not None
