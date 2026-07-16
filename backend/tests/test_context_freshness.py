"""P6B-9: the FRESHNESS VERIFICATION SUITE - the single authoritative artifact
that PROVES context freshness is a measured, tested property (the user's explicit
"how do you CHECK freshness" question), plus the scheduled reconcile sweep.

Everything a caller must be able to trust about "the AI layer is never silently
stale" is proven here, deterministically, with the offline fakes (``FakeSummarizer``
+ ``FakeEmbedder`` (dim 1024) + ``InMemoryVectorStore``) - no keys, no network:

* **The freshness INVARIANT.** For a ``status='summarized'`` entity,
  ``event_watermark >= latest_seq`` (lag 0). ``pending`` / ``degraded`` / ``error``
  are honestly reported stale. Proven by ``_assert_invariant``.
* **After-action.** An activity event enqueues a dirty row; one ``execute_compaction``
  advances the watermark PAST that seq and the new fact + summary reflect the action.
* **Supersession gone from BOTH stores.** Changing a fact A->B removes the old value
  from ``facts`` AND from the vector chunk that embedded it - the old content's
  checksum is absent from BOTH the vector store namespace AND the ``context_vectors``
  ledger. Folded in one pass, the superseded value never enters the living prose.
* **Golden-set retrieval.** With the deterministic ``FakeEmbedder``, a query that IS
  a stored fact retrieves that chunk at cosine ~1.0 (top rank); a query about a
  SUPERSEDED fact never surfaces the stale value (it is in no current chunk).
* **No gate bypass.** Dial ``off`` => a full compaction makes ZERO provider calls and
  writes ZERO non-cached cost rows; a normal run commits exactly one cost row per
  gated provider call (nothing bypasses the money-dial).
* **Pinecone<->Postgres consistency.** ``reconcile`` reports empty for a healthy
  entity; an injected orphan + missing are each flagged; ``repair`` heals them. The
  scheduled ``run_reconcile_sweep`` walks every entity and aggregates the drift.

HONESTY NOTE (deliberate, not a weakening): the ``FakeSummarizer`` is a naive
truncating digest that carries the PRIOR summary forward verbatim - it does not
obey the real summarizer's "drop contradicted facts" instruction. So across TWO
separate folds a superseded value can linger in the carried prose (the real Claude
summarizer is instructed to drop it, which is not deterministically testable). The
deterministic supersession guarantee therefore lives in the FACTS + VECTOR layers
(proven exhaustively below); the "gone from the summary" claim is proven in the
single-fold path where it is deterministically true.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from app.config import Settings
from app.services.context_compactor import build_context_chunks
from app.services.context_cost import GatedEmbedder, GatedSummarizer
from app.services.context_service import context_health, get_context
from app.services.context_vectorsync import (
    namespace_for,
    pinecone_id_for,
    reconcile,
    sync_vectors,
)
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.context_providers import ContextProviders, providers_for_tests
from integrations.embeddings import FakeEmbedder
from integrations.llm import FakeSummarizer, LLMResult
from integrations.vectorstore import InMemoryVectorStore, VectorItem, VectorStore
from workers.tasks.context import execute_compaction
from workers.tasks.context_reconcile import _context_resolver, run_reconcile_sweep

pytestmark = pytest.mark.unit

ENTITY = ("client", "11111111-1111-1111-1111-111111111111")


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "context_summary_token_budget": 1200,
        "context_max_facts": 64,
        "context_backoff_seconds": 300,
        "context_dispatch_batch": 100,
        "context_topk": 6,
    }
    base.update(over)
    return Settings(_env_file=None, app_env="dev", **base)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event(
    seq: int, *, kind: str = "client", action: str = "set tier", target: str = "acme",
    meta: str | None = None,
) -> dict[str, Any]:
    return {"seq": seq, "kind": kind, "action": action, "target": target, "meta": meta, "created_at": None}


# --------------------------------------------------------------------------- #
# A single-entity fake that satisfies BOTH the ContextStore surface
# (execute_compaction) and the RLS-read surface (get_context / context_health).
# Mirrors the repo's semantics; the ledger doubles as the VectorLedger.
# --------------------------------------------------------------------------- #
class FakeStore:
    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.context: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = list(events or [])
        self.dirty_last: int | None = max((e["seq"] for e in self.events), default=0) or None
        self.dirty_exists = bool(self.events)
        self.rearms: list[dict[str, Any]] = []
        self.cleared = 0
        self.upserts: list[dict[str, Any]] = []
        self.ledger: dict[str, dict[str, Any]] = {}

    def add_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.dirty_exists = True
        self.dirty_last = max(self.dirty_last or 0, int(event["seq"]))

    # --- RLS reads (get_context / context_health) ---
    def get_entity_context(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return dict(self.context) if self.context is not None else None

    def latest_seq(self, entity_type: str, entity_id: str) -> int:
        return max((int(e["seq"]) for e in self.events), default=0)

    # --- ContextStore surface (execute_compaction) ---
    def get_context_for_update(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return self.context

    def upsert_context(
        self, entity_type: str, entity_id: str, *, summary: str = "",
        facts: dict[str, Any] | None = None, token_budget: int = 1200, token_count: int = 0,
        event_watermark: int = 0, status: str = "summarized", model: str = "", checksum: str = "",
    ) -> dict[str, Any]:
        prior_version = int(self.context["version"]) if self.context else 0
        prior_watermark = int(self.context["event_watermark"]) if self.context else 0
        is_insert = self.context is None
        row = {
            "id": "ctx-1", "entity_type": entity_type, "entity_id": entity_id, "summary": summary,
            "facts": dict(facts or {}), "token_budget": token_budget, "token_count": token_count,
            "event_watermark": max(prior_watermark, event_watermark), "status": status,
            "model": model, "checksum": checksum,
            "version": prior_version if is_insert else prior_version + 1, "updated_at": None,
        }
        self.context = row
        self.upserts.append(dict(row))
        return dict(row)

    def events_after(self, entity_type: str, entity_id: str, watermark: int) -> list[dict[str, Any]]:
        return [e for e in self.events if int(e["seq"]) > watermark]

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

    def claim_due_dirty(self, limit: int) -> list[dict[str, Any]]:
        return []

    # --- VectorLedger surface ---
    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.ledger.values()]

    def record_vector(
        self, entity_type: str, entity_id: str, *, chunk_key: str, pinecone_id: str,
        content_checksum: str, version: int, dim: int, model: str,
    ) -> dict[str, Any]:
        row = {"chunk_key": chunk_key, "pinecone_id": pinecone_id, "content_checksum": content_checksum,
               "version": version, "dim": dim, "model": model}
        self.ledger[chunk_key] = row
        return dict(row)

    def delete_vector(self, entity_type: str, entity_id: str, chunk_key: str) -> dict[str, Any] | None:
        return self.ledger.pop(chunk_key, None)


def _assert_invariant(store: FakeStore) -> None:
    """THE freshness invariant: for a summarized entity, watermark >= latest_seq (lag 0)."""
    assert store.context is not None
    if store.context["status"] == "summarized":
        latest = store.latest_seq(*ENTITY)
        assert int(store.context["event_watermark"]) >= latest, "summarized => lag must be 0"


# =========================================================================== #
# 1. AFTER-ACTION: an event folds into context; the watermark absorbs its seq
# =========================================================================== #
def test_after_action_event_folds_and_invariant_holds() -> None:
    # An audit + a tier change land as activity for the entity (the trigger would
    # enqueue a dirty row; here we drive the fold directly with the injected fakes).
    store = FakeStore([
        _event(40, kind="audit", action="ran audit", target="https://acme.test/seo-report", meta="91"),
        _event(41, kind="client", action="set tier", target="acme", meta="Growth"),
    ])

    out = execute_compaction(store, providers_for_tests(), *ENTITY, settings=_settings())

    assert out.state == "summarized"
    # (after-action) the watermark advanced PAST the newest event seq...
    assert out.watermark == 41
    assert store.context is not None and int(store.context["event_watermark"]) >= 41
    # ...and the new fact + the living summary REFLECT the action within N events.
    assert store.context["facts"]["last_audit"] == "https://acme.test/seo-report"
    assert store.context["facts"]["last_audit_score"] == 91
    assert store.context["facts"]["tier"] == "Growth"
    assert "seo-report" in store.context["summary"] and "Growth" in store.context["summary"]
    # THE INVARIANT: a summarized entity has event_watermark >= latest_seq (lag 0).
    assert store.context["status"] == "summarized"
    _assert_invariant(store)
    health = context_health(*ENTITY, repo=store)
    assert health.stale is False and health.lag == 0


def test_pending_and_degraded_are_reported_stale() -> None:
    # An entity with events but no fold yet reads stale (pending, honestly behind).
    pending = FakeStore([_event(7)])
    assert context_health(*ENTITY, repo=pending).stale is True
    # A degraded fold (no providers) HOLDS the watermark => still stale, never a lie.
    degraded = FakeStore([_event(3), _event(4)])
    out = execute_compaction(degraded, None, *ENTITY, settings=_settings())
    assert out.state == "degraded"
    assert degraded.context is not None and degraded.context["status"] == "degraded"
    assert context_health(*ENTITY, repo=degraded).stale is True  # lag stays visible


# =========================================================================== #
# 2. SUPERSESSION gone from BOTH stores (facts + vectorstore + ledger)
# =========================================================================== #
def test_supersession_value_gone_from_facts_and_both_vector_stores() -> None:
    providers = providers_for_tests()
    store = FakeStore()
    namespace = namespace_for(*ENTITY)
    old_checksum = _sha("tier: Starter")
    new_checksum = _sha("tier: Enterprise")

    # Fold 1: tier=Starter -> the facts:client chunk embeds the OLD content.
    store.add_event(_event(10, kind="client", action="set tier", target="acme", meta="Starter"))
    execute_compaction(store, providers, *ENTITY, settings=_settings())
    assert store.context is not None and store.context["facts"]["tier"] == "Starter"
    assert old_checksum in {r["content_checksum"] for r in store.list_vectors(*ENTITY)}
    assert old_checksum in {
        i.metadata.get("content_checksum") for i in providers.vector_store.list_items(namespace)
    }

    # Fold 2 (RECOMPACT): tier=Enterprise supersedes Starter (deterministic LWW).
    store.add_event(_event(11, kind="client", action="set tier", target="acme", meta="Enterprise"))
    execute_compaction(store, providers, *ENTITY, settings=_settings())

    # (a) the superseded VALUE is gone from entity_context.facts.
    assert store.context["facts"]["tier"] == "Enterprise"
    assert "Starter" not in str(store.context["facts"])

    # (b) the OLD vector chunk (embedding "tier: Starter") is gone from the LEDGER...
    ledger_checksums = {r["content_checksum"] for r in store.list_vectors(*ENTITY)}
    assert old_checksum not in ledger_checksums
    assert new_checksum in ledger_checksums  # the chunk now embeds the CURRENT value
    # ...AND from the vector STORE namespace (no item carries the old content checksum).
    store_checksums = {i.metadata.get("content_checksum") for i in providers.vector_store.list_items(namespace)}
    assert old_checksum not in store_checksums
    assert new_checksum in store_checksums

    # (c) retrieval for the stale content can NEVER surface the old value: the facts
    # chunk's current content maps to "tier: Enterprise".
    current = {c.chunk_key: c.content for c in build_context_chunks(store.context["summary"], store.context["facts"])}
    assert current["facts:client"] == "tier: Enterprise"
    assert "Starter" not in current["facts:client"]


def test_supersession_within_a_fold_keeps_stale_value_out_of_the_summary() -> None:
    # When the A->B change is folded in ONE pass, the living prose never contains the
    # superseded value: events render action+target (NOT meta), and only the folded
    # (current) facts carry values - so "Starter" appears nowhere in facts OR summary.
    store = FakeStore([
        _event(10, kind="client", action="set tier", target="acme", meta="Starter"),
        _event(11, kind="client", action="set tier", target="acme", meta="Enterprise"),
    ])
    execute_compaction(store, providers_for_tests(), *ENTITY, settings=_settings())

    assert store.context is not None
    assert store.context["facts"]["tier"] == "Enterprise"
    assert "Starter" not in str(store.context["facts"])
    assert "Starter" not in store.context["summary"]  # the superseded value is not in the prose
    assert "Enterprise" in store.context["summary"]


# =========================================================================== #
# 3. GOLDEN-SET retrieval with the deterministic FakeEmbedder
# =========================================================================== #
# A tiny golden table: query -> (expected substring, present?). A PRESENT query is
# the exact stored fact chunk content, so the deterministic FakeEmbedder scores it
# ~1.0 (top rank). The SUPERSEDED query names a value folded away, which is in NO
# current chunk, so it can never be surfaced.
_GOLDEN_PRESENT: list[tuple[str, str]] = [
    ("tier: Enterprise", "Enterprise"),
    ("last_task: closed onboarding", "onboarding"),
    ("last_content: published blog-post", "blog-post"),
]
_SUPERSEDED_QUERY = "tier: Starter"  # the superseded plan; must never surface


def _golden_corpus_repo() -> tuple[FakeStore, ContextProviders]:
    # A fixed corpus folded in ONE clean pass (so no stale value lingers anywhere):
    # Starter is superseded by Enterprise within the fold.
    store = FakeStore([
        _event(1, kind="audit", action="ran audit", target="https://acme.test/seo-report", meta="91"),
        _event(2, kind="client", action="set tier", target="acme", meta="Starter"),
        _event(3, kind="client", action="set tier", target="acme", meta="Enterprise"),
        _event(4, kind="task", action="closed", target="onboarding"),
        _event(5, kind="content", action="published", target="blog-post"),
    ])
    providers = providers_for_tests()
    # fresh=True populates the vector store for this entity via the real fold path.
    get_context(*ENTITY, query=None, fresh=True, providers=providers, repo=store, settings=_settings())
    return store, providers


def test_golden_set_present_fact_is_retrieved_top_rank() -> None:
    store, providers = _golden_corpus_repo()
    for query, expected in _GOLDEN_PRESENT:
        view = get_context(*ENTITY, query=query, fresh=False, providers=providers, repo=store, settings=_settings())
        # the expected fact IS retrieved, at the top (exact-content match => cosine ~1.0).
        exact = [c for c in view.chunks if c.content == query]
        assert exact, f"golden query {query!r} did not retrieve its fact chunk"
        assert exact[0].score == pytest.approx(1.0, abs=1e-6)
        assert expected in exact[0].content
        # the checksum never rides the retrieval wire.
        assert all("content_checksum" not in c.model_dump() for c in view.chunks)


def test_golden_set_superseded_fact_never_surfaces() -> None:
    store, providers = _golden_corpus_repo()
    view = get_context(*ENTITY, query=_SUPERSEDED_QUERY, fresh=False, providers=providers, repo=store, settings=_settings())
    assert view.chunks  # retrieval returned something...
    # ...but the superseded value is in NONE of the current chunks (nor facts/summary).
    assert all("Starter" not in c.content for c in view.chunks)
    assert "Starter" not in str(view.facts)
    assert "Starter" not in view.summary


# =========================================================================== #
# 4. NO GATE BYPASS: dial off => 0 calls / 0 cost; normal => calls == cost rows
# =========================================================================== #
class _RecordingCostStore:
    """A ``CostStore`` whose dial is fixed and which records every cost write."""

    def __init__(self, mode: DialMode) -> None:
        self._mode: DialMode = mode
        self.records: list[tuple[str, float, bool]] = []  # (feature_key, cost, cached)

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 1000.0

    def is_halted(self) -> bool:
        return False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.records.append((ctx.feature_key, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class _SpySummarizer(FakeSummarizer):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        return super().summarize(prompt, model=model, max_tokens=max_tokens)


class _SpyEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__(dim=1024)
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return super().embed(texts)


def _gated_bundle(mode: DialMode) -> tuple[ContextProviders, _RecordingCostStore, _SpySummarizer, _SpyEmbedder]:
    base = providers_for_tests()
    cost = _RecordingCostStore(mode)
    gate = CostGate(cost, _NullCache())
    settings = _settings()
    sum_spy = _SpySummarizer()
    emb_spy = _SpyEmbedder()
    gated = replace(
        base,
        summarizer=GatedSummarizer(sum_spy, gate, settings=settings, client_id=None),
        embedder=GatedEmbedder(emb_spy, gate, settings=settings, client_id=None),
    )
    return gated, cost, sum_spy, emb_spy


def test_dial_off_makes_zero_provider_calls_and_zero_cost_rows() -> None:
    store = FakeStore([_event(9, kind="client", action="set tier", target="acme", meta="Growth")])
    gated, cost, sum_spy, emb_spy = _gated_bundle("off")

    out = execute_compaction(store, gated, *ENTITY, settings=_settings())

    assert out.state == "degraded"  # the gate blocked the spend -> degrade, don't crash
    assert sum_spy.calls == 0  # the summarizer provider was NEVER reached
    assert emb_spy.embedded == []  # the embedder provider was NEVER reached
    assert [r for r in cost.records if not r[2]] == []  # ZERO non-cached cost rows
    # No summarized half-write happened.
    assert all(u["status"] != "summarized" for u in store.upserts)


def test_normal_run_gates_every_ai_call_calls_equal_cost_rows() -> None:
    store = FakeStore([
        _event(20, kind="audit", action="ran audit", target="https://x.test", meta="88"),
        _event(21, kind="client", action="set tier", target="acme", meta="Growth"),
    ])
    gated, cost, sum_spy, emb_spy = _gated_bundle("api")

    out = execute_compaction(store, gated, *ENTITY, settings=_settings())

    assert out.state == "summarized"
    non_cached = [r for r in cost.records if not r[2]]
    summary_rows = [r for r in non_cached if r[0] == "context"]
    embed_rows = [r for r in non_cached if r[0] == "context_embed"]
    # every gated provider call committed EXACTLY one cost row (nothing bypassed).
    assert sum_spy.calls == len(summary_rows) == 1
    assert len(emb_spy.embedded) == len(embed_rows)
    assert len(emb_spy.embedded) == len(set(emb_spy.embedded))  # each unique text embedded once
    # provider-call-count == committed cost records.
    assert sum_spy.calls + len(emb_spy.embedded) == len(non_cached)


# =========================================================================== #
# 5. Pinecone<->Postgres CONSISTENCY: reconcile + the scheduled sweep
# =========================================================================== #
def test_reconcile_pipeline_healthy_then_orphan_missing_then_repair() -> None:
    # Build an entity's vectors through the real fold path, then reconcile the
    # InMemory store against the ledger the fold wrote.
    providers = providers_for_tests()
    store = FakeStore([
        _event(30, kind="client", action="set tier", target="acme", meta="Growth"),
        _event(31, kind="audit", action="ran audit", target="https://x.test", meta="80"),
    ])
    execute_compaction(store, providers, *ENTITY, settings=_settings())
    vstore = providers.vector_store
    namespace = namespace_for(*ENTITY)

    # Healthy: the ledger and the store agree exactly.
    report = reconcile(*ENTITY, store=vstore, ledger=store)
    assert report.healthy and report.drift_count == 0

    # Inject an ORPHAN (store-only) + a MISSING (ledger-only, vector deleted).
    vstore.upsert(
        namespace,
        [VectorItem(id=f"client:{ENTITY[1]}#ghost", vector=providers.embedder.embed(["x"])[0],
                    metadata={"chunk_key": "ghost"})],
    )
    vstore.delete(namespace, [pinecone_id_for(*ENTITY, "facts:audit")])
    drifted = reconcile(*ENTITY, store=vstore, ledger=store)
    assert not drifted.healthy
    assert [d.chunk_key for d in drifted.orphans] == ["ghost"]
    assert [d.chunk_key for d in drifted.missing] == ["facts:audit"]

    # Repair heals both (orphan deleted; missing re-embedded from the current chunks).
    chunks = build_context_chunks(store.context["summary"], store.context["facts"])  # type: ignore[index]
    healed = reconcile(
        *ENTITY, store=vstore, ledger=store, repair=True,
        chunks=chunks, embedder=providers.embedder, version=int(store.context["version"]),  # type: ignore[index]
    )
    assert healed.orphans_deleted == 1 and healed.missing_repaired == 1
    assert reconcile(*ENTITY, store=vstore, ledger=store).healthy  # a follow-up sweep is clean


# --- the scheduled sweep core (multi-entity, aggregate drift) --------------- #
class _FakeReconcileRepo:
    """A multi-entity ledger + context store the reconcile sweep walks."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.contexts: dict[tuple[str, str], dict[str, Any]] = {}

    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return [dict(r) for k, r in sorted(self.rows.items()) if k[0] == entity_type and k[1] == entity_id]

    def record_vector(
        self, entity_type: str, entity_id: str, *, chunk_key: str, pinecone_id: str,
        content_checksum: str, version: int, dim: int, model: str,
    ) -> dict[str, Any]:
        row = {"entity_type": entity_type, "entity_id": entity_id, "chunk_key": chunk_key,
               "pinecone_id": pinecone_id, "content_checksum": content_checksum,
               "version": version, "dim": dim, "model": model}
        self.rows[(entity_type, entity_id, chunk_key)] = row
        return dict(row)

    def delete_vector(self, entity_type: str, entity_id: str, chunk_key: str) -> dict[str, Any] | None:
        return self.rows.pop((entity_type, entity_id, chunk_key), None)

    def distinct_vector_entities(self) -> list[tuple[str, str]]:
        return sorted({(k[0], k[1]) for k in self.rows})

    def get_context_admin(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return self.contexts.get((entity_type, entity_id))


def _seed_entity(repo: _FakeReconcileRepo, store: VectorStore, embedder: FakeEmbedder, eid: str) -> None:
    summary = f"living summary for {eid}"
    facts = {"tier": "Growth"}
    chunks = build_context_chunks(summary, facts)
    sync_vectors("client", eid, chunks, version=1, embedder=embedder, store=store, ledger=repo)
    repo.contexts[("client", eid)] = {
        "entity_type": "client", "entity_id": eid, "summary": summary, "facts": facts, "version": 1,
    }


def test_reconcile_sweep_detects_and_repairs_drift_across_entities() -> None:
    store = InMemoryVectorStore()
    repo = _FakeReconcileRepo()
    embedder = FakeEmbedder(dim=64)
    for eid in ("cl-A", "cl-B"):
        _seed_entity(repo, store, embedder, eid)

    # Healthy sweep: two entities walked, no drift.
    healthy = run_reconcile_sweep(repo, store)
    assert healthy.entities == 2 and healthy.drift == 0 and healthy.drift_count == 0
    assert healthy.healthy == 2

    # Inject an orphan + a missing into ONE entity only.
    ns_a = namespace_for("client", "cl-A")
    store.upsert(ns_a, [VectorItem(id="client:cl-A#ghost", vector=embedder.embed(["x"])[0], metadata={"chunk_key": "ghost"})])
    store.delete(ns_a, [pinecone_id_for("client", "cl-A", "facts:client")])

    drifted = run_reconcile_sweep(repo, store)
    assert drifted.entities == 2 and drifted.drift == 1  # only cl-A drifted
    assert drifted.orphans == 1 and drifted.missing == 1 and drifted.drift_count == 2

    # Repair heals the drift; a follow-up sweep is clean.
    healed = run_reconcile_sweep(repo, store, repair=True, embedder=embedder, context_for=_context_resolver(repo))
    assert healed.orphans_deleted == 1 and healed.missing_repaired == 1
    assert run_reconcile_sweep(repo, store).drift == 0


class _ExplodingStore:
    """Wraps a store so ``list_items`` raises for one namespace (a Pinecone blip)."""

    def __init__(self, inner: InMemoryVectorStore, boom_namespace: str) -> None:
        self._inner = inner
        self._boom = boom_namespace

    def upsert(self, namespace: str, items: list[VectorItem]) -> None:
        self._inner.upsert(namespace, items)

    def query(self, namespace: str, vector: list[float], top_k: int) -> Any:
        return self._inner.query(namespace, vector, top_k)

    def delete(self, namespace: str, ids: list[str]) -> None:
        self._inner.delete(namespace, ids)

    def list_items(self, namespace: str) -> list[VectorItem]:
        if namespace == self._boom:
            raise RuntimeError("pinecone down")
        return self._inner.list_items(namespace)


def test_reconcile_sweep_never_raises_and_counts_a_failed_entity() -> None:
    inner = InMemoryVectorStore()
    repo = _FakeReconcileRepo()
    embedder = FakeEmbedder(dim=64)
    for eid in ("cl-A", "cl-B"):
        _seed_entity(repo, store=inner, embedder=embedder, eid=eid)
    store = _ExplodingStore(inner, boom_namespace=namespace_for("client", "cl-A"))

    report = run_reconcile_sweep(repo, store)  # must NOT raise

    assert report.entities == 2
    assert report.errors == 1  # cl-A's reconcile raised and was swallowed
    assert report.healthy == 1  # cl-B still reconciled cleanly
