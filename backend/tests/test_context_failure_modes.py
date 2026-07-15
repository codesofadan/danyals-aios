"""P6B-10 failure-mode hardening (unit, fakes - no network, no keys).

The context module's promise under partial failure: **Postgres is the source of
truth, Pinecone is a derived index that never corrupts it, no context AI spend can
bypass the gate, and no secret is ever logged.** These tests prove each failure
mode holds:

* **Pinecone unavailable** - the ``PineconeVectorStore`` tenacity retry engages on a
  transient blip (N attempts, exponential backoff) and reraises on a persistent one;
  when the store fails persistently mid-fold, ``execute_compaction`` writes NO
  summarized ``entity_context`` (Postgres stays authoritative), marks the row
  recoverable ('error'), and re-arms the dirty row - and a later ``reconcile(repair=
  True)`` re-embeds the missing vectors once the store recovers (reconcile-on-recovery).
* **Namespace isolation** - entity A's vectors never appear in entity B's namespace
  (the tenant partition; the portal RLS boundary is proven live in
  ``tests/integration/test_portal_isolation.py``).
* **Secrets never logged** - the provider factory + gated wrappers never emit an API
  key, even while holding the decrypted value.
* **Degrade with no keys** - ``providers=None`` degrades: the watermark is HELD, the
  dirty row re-armed, and no provider is ever reached (the ``/context/health`` lag
  surface is proven live in ``tests/integration/test_context_freshness.py``).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
import tenacity.nap

from app.config import Settings
from app.logging_setup import configure_logging
from app.services.context_compactor import build_context_chunks
from app.services.context_cost import GatedSummarizer
from app.services.context_vectorsync import namespace_for, reconcile
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations import context_providers as cp
from integrations.context_providers import ContextProviders, providers_for_tests
from integrations.vectorstore import PineconeVectorStore, VectorItem
from workers.tasks.context import execute_compaction

pytestmark = pytest.mark.unit

ENTITY = ("client", "11111111-1111-1111-1111-111111111111")
ENTITY_B = ("client", "22222222-2222-2222-2222-222222222222")


# --------------------------------------------------------------------------- #
# A fake ContextStore (== the unit worker's, condensed): entity_context + events
# + a single dirty row + the vector ledger (so sync_vectors writes through it).
# --------------------------------------------------------------------------- #
class FakeContextStore:
    """In-memory ``ContextStore`` + ``VectorLedger`` for the pure core."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.context: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = events or []
        self.dirty_last: int | None = max((e["seq"] for e in self.events), default=0) or None
        self.dirty_exists = True
        self.rearms: list[dict[str, Any]] = []
        self.cleared = 0
        self.upserts: list[dict[str, Any]] = []
        self.ledger: dict[str, dict[str, Any]] = {}

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
            "id": "ctx-1", "entity_type": entity_type, "entity_id": entity_id,
            "summary": summary, "facts": dict(facts or {}), "token_budget": token_budget,
            "token_count": token_count, "event_watermark": max(prior_watermark, event_watermark),
            "status": status, "model": model, "checksum": checksum,
            "version": prior_version if is_insert else prior_version + 1,
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

    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return list(self.ledger.values())

    def record_vector(
        self, entity_type: str, entity_id: str, *, chunk_key: str, pinecone_id: str,
        content_checksum: str, version: int, dim: int, model: str,
    ) -> dict[str, Any]:
        row = {
            "chunk_key": chunk_key, "pinecone_id": pinecone_id,
            "content_checksum": content_checksum, "version": version, "dim": dim, "model": model,
        }
        self.ledger[chunk_key] = row
        return dict(row)

    def delete_vector(
        self, entity_type: str, entity_id: str, chunk_key: str
    ) -> dict[str, Any] | None:
        return self.ledger.pop(chunk_key, None)


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "context_summary_token_budget": 1200, "context_max_facts": 64,
        "context_backoff_seconds": 300, "context_dispatch_batch": 100,
    }
    base.update(over)
    return Settings(_env_file=None, app_env="dev", **base)


def _event(seq: int, *, kind: str = "client", action: str = "set tier", target: str = "acme",
           meta: str | None = "Growth") -> dict[str, Any]:
    return {"seq": seq, "kind": kind, "action": action, "target": target, "meta": meta, "created_at": None}


# =========================================================================== #
# 1a. Pinecone unavailable: the tenacity retry policy (N attempts + reraise).
# =========================================================================== #
class _FlakyIndex:
    """A Pinecone index double that raises a transient error the first N calls."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("pinecone transient blip")

    def upsert(self, *, vectors: list[Any], namespace: str) -> dict[str, Any]:
        self._maybe_fail()
        return {"upserted_count": len(vectors)}


def _pinecone_over(index: _FlakyIndex) -> PineconeVectorStore:
    """A ``PineconeVectorStore`` bypassing __init__ (no SDK), wired to a fake index."""
    store = PineconeVectorStore.__new__(PineconeVectorStore)
    store._index = index  # type: ignore[attr-defined]
    store._transient = (ConnectionError, TimeoutError, OSError)  # type: ignore[attr-defined]
    return store


def test_pinecone_retry_recovers_after_transient_blips(monkeypatch: pytest.MonkeyPatch) -> None:
    # Don't actually sleep the exponential backoff during the test.
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _s: None)
    index = _FlakyIndex(fail_times=2)  # fail twice, succeed on the 3rd attempt
    store = _pinecone_over(index)
    store.upsert("client:x", [VectorItem(id="a", vector=[0.1, 0.2], metadata={})])
    assert index.calls == 3  # the retry engaged: 2 failures + 1 success


def test_pinecone_retry_reraises_after_persistent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _s: None)
    index = _FlakyIndex(fail_times=99)  # never recovers
    store = _pinecone_over(index)
    with pytest.raises(ConnectionError):
        store.upsert("client:x", [VectorItem(id="a", vector=[0.1, 0.2], metadata={})])
    assert index.calls == 4  # stop_after_attempt(4): tries exactly 4 times, then reraises


# =========================================================================== #
# 1b. Persistent Pinecone failure mid-fold => Postgres stays authoritative.
# =========================================================================== #
class _DeadVectorStore:
    """A ``VectorStore`` whose writes always fail (a persistently-down Pinecone)."""

    def upsert(self, namespace: str, items: list[VectorItem]) -> None:
        raise ConnectionError("pinecone down")

    def query(self, namespace: str, vector: list[float], top_k: int) -> list[Any]:
        raise ConnectionError("pinecone down")

    def delete(self, namespace: str, ids: list[str]) -> None:
        raise ConnectionError("pinecone down")

    def list_items(self, namespace: str) -> list[VectorItem]:
        raise ConnectionError("pinecone down")


def test_persistent_pinecone_failure_leaves_postgres_authoritative() -> None:
    store = FakeContextStore([_event(3), _event(4)])
    providers = replace(providers_for_tests(), vector_store=_DeadVectorStore())

    out = execute_compaction(store, providers, *ENTITY, settings=_settings())  # must NOT raise

    # The vector-store failure is caught; the entity is marked recoverable, NOT summarized.
    assert out.state == "error"
    assert store.context is not None and store.context["status"] == "error"
    # THE INVARIANT: the summarized upsert (source of truth) never ran -> no half-write.
    assert all(u["status"] != "summarized" for u in store.upserts)
    assert int(store.context["event_watermark"]) == 0  # watermark held (lag stays visible)
    # Re-armed with backoff so a later fold / reconcile heals it.
    assert store.rearms and store.rearms[-1]["backoff_seconds"] == 300


def test_reconcile_on_recovery_reembeds_missing_vectors() -> None:
    # A clean fold populates both the ledger AND the (InMemory) store.
    store = FakeContextStore([_event(5)])
    providers = providers_for_tests()
    out = execute_compaction(store, providers, *ENTITY, settings=_settings())
    assert out.state == "summarized"
    vstore = providers.vector_store
    namespace = namespace_for(*ENTITY)

    # Simulate a Pinecone outage that lost the vectors: the ledger still has the rows
    # (Postgres = truth) but the store namespace is empty -> reconcile flags 'missing'.
    ids = [str(v["pinecone_id"]) for v in store.list_vectors(*ENTITY)]
    vstore.delete(namespace, ids)
    report = reconcile(*ENTITY, store=vstore, ledger=store)
    assert not report.healthy and report.missing

    # Recovery: reconcile(repair=True) with the current chunks + embedder re-embeds the
    # missing vectors to the ledger's truth; the entity is healthy again.
    summary = str(store.context["summary"])  # type: ignore[index]
    facts = dict(store.context["facts"])  # type: ignore[index]
    chunks = build_context_chunks(summary, facts)
    repaired = reconcile(
        *ENTITY, store=vstore, ledger=store, repair=True,
        chunks=chunks, embedder=providers.embedder, version=int(store.context["version"]),  # type: ignore[index]
    )
    assert repaired.missing_repaired == len(report.missing)
    assert reconcile(*ENTITY, store=vstore, ledger=store).healthy


# =========================================================================== #
# 2. Namespace isolation: entity A's vectors never enter entity B's namespace.
# =========================================================================== #
def test_entity_namespaces_never_cross_tenants() -> None:
    # One shared vector store, two entities folded through the SAME pipeline.
    providers = providers_for_tests()
    store_a = FakeContextStore([_event(1, meta="Growth")])
    store_b = FakeContextStore([_event(1, meta="Basic")])
    execute_compaction(store_a, providers, *ENTITY, settings=_settings())
    execute_compaction(store_b, providers, *ENTITY_B, settings=_settings())

    vstore = providers.vector_store
    ns_a, ns_b = namespace_for(*ENTITY), namespace_for(*ENTITY_B)
    ids_a = {item.id for item in vstore.list_items(ns_a)}
    ids_b = {item.id for item in vstore.list_items(ns_b)}
    assert ids_a and ids_b and ids_a.isdisjoint(ids_b)  # no shared vector id
    # Every A vector id is namespaced to A; a query on A can only ever return A ids.
    assert all(i.startswith(f"{ENTITY[0]}:{ENTITY[1]}#") for i in ids_a)
    probe = providers.embedder.embed(["subscription tier"])[0]
    assert {m.id for m in vstore.query(ns_a, probe, top_k=10)} <= ids_a
    # (The portal RLS boundary - a client can't read another tenant's context - is
    #  proven live in tests/integration/test_portal_isolation.py.)


# =========================================================================== #
# 3. Secrets never logged: the factory + gated wrappers never emit an API key.
# =========================================================================== #
def test_provider_factory_never_logs_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Prod logging => JSON to stdout, so capsys sees every emitted field.
    configure_logging(Settings(_env_file=None, app_env="prod"))
    secret_a, secret_e, secret_p = "sk-ANTHROPIC-LEAKME", "vk-VOYAGE-LEAKME", "pc-PINE-LEAKME"

    built: dict[str, object] = {}
    monkeypatch.setattr(cp, "AnthropicSummarizer", lambda **kw: built.setdefault("s", kw) or "S")
    monkeypatch.setattr(cp, "VoyageEmbedder", lambda **kw: built.setdefault("e", kw) or "E")
    monkeypatch.setattr(cp, "PineconeVectorStore", lambda **kw: built.setdefault("v", kw) or "V")

    settings = Settings(
        _env_file=None, anthropic_api_key=secret_a, embeddings_api_key=secret_e,
        pinecone_api_key=secret_p, pinecone_index="idx",
    )
    bundle = cp.context_providers_from_settings(settings)
    assert isinstance(bundle, ContextProviders)
    # The decrypted key IS handed to the SDK client (correct) ...
    assert built["s"]["api_key"] == secret_a  # type: ignore[index]
    # ... but it must NEVER reach a log line.
    out = capsys.readouterr().out
    for secret in (secret_a, secret_e, secret_p):
        assert secret not in out


def test_degraded_and_blocked_paths_never_log_secrets(
    capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(Settings(_env_file=None, app_env="prod"))
    secret = "sk-SECRET-MUST-NOT-LOG"

    # (a) Degraded factory (missing keys) logs the reason only - no secret in scope,
    #     and the log line carries none.
    degraded_settings = Settings(_env_file=None, anthropic_api_key=secret)  # other keys absent
    assert cp.context_providers_from_settings(degraded_settings) is None

    # (b) A cost-blocked context AI call: the gate denies, the worker degrades, logs fire.
    store = FakeContextStore([_event(8)])
    gated = _gated_blocking_bundle(secret)
    out = execute_compaction(store, gated, *ENTITY, settings=_settings())
    assert out.state == "degraded"  # blocked spend -> degrade, not crash

    captured = capsys.readouterr().out
    assert secret not in captured


class _OffCostStore:
    """A gate store with the dial 'off' => every evaluate blocks (no spend)."""

    def dial_mode(self, feature_key: str) -> DialMode:
        return "off"

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


class _SecretBearingSummarizer:
    """A summarizer that (wrongly) exposes a secret in its repr - the gate must
    block BEFORE it is ever reached, and nothing may log it."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> Any:
        raise AssertionError("blocked gate must never reach the provider")


def _gated_blocking_bundle(secret: str) -> ContextProviders:
    base = providers_for_tests()
    gate = CostGate(_OffCostStore(), _NullCache())
    settings = _settings()
    return replace(
        base,
        summarizer=GatedSummarizer(
            _SecretBearingSummarizer(secret), gate, settings=settings, client_id=None
        ),
    )


# =========================================================================== #
# 4. Degrade with no keys: watermark HELD, dirty re-armed, provider $0 (consolidated).
# =========================================================================== #
def test_degrade_with_no_keys_holds_watermark_and_never_spends() -> None:
    store = FakeContextStore([_event(3), _event(4)])
    store.context = {
        "id": "ctx-1", "entity_type": ENTITY[0], "entity_id": ENTITY[1],
        "summary": "prior prose", "facts": {"tier": "Free"}, "token_budget": 1200,
        "token_count": 2, "event_watermark": 0, "status": "pending",
        "model": "", "checksum": "", "version": 1,
    }

    out = execute_compaction(store, None, *ENTITY, settings=_settings())  # providers=None

    assert out.state == "degraded"
    assert out.watermark == 0  # HELD -> the freshness lag stays visible
    assert store.context["status"] == "degraded"
    assert store.rearms[-1]["backoff_seconds"] == 300  # re-armed for a later retry
    # No provider was reached and nothing was summarized -> zero spend, no half-write.
    assert all(u["status"] != "summarized" for u in store.upserts)
    # (The /context/health lag surface for a degraded entity is proven live in
    #  tests/integration/test_context_freshness.py.)
