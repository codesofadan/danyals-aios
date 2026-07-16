"""P6B-6 gate: VECTOR SYNC + supersession GC + reconcile.

All proofs run offline with ``FakeEmbedder`` + ``InMemoryVectorStore`` + an
in-memory ledger fake that mirrors ``ContextRepo.context_vectors`` semantics
(upsert-on-(entity,chunk_key); ``delete_vector`` returns the deleted row so the
caller can GC the store). No keys, deterministic vectors.

The load-bearing proofs:

* an **unchanged** chunk is NOT re-embedded (the embedder spy sees 0 texts), not
  re-upserted, and its ledger row is untouched;
* a **changed** chunk (same key, new checksum) is embedded once, the store holds
  the NEW vector, and the ledger checksum/version advance;
* a **new** chunk is embedded + upserted + gets a ledger row;
* a **superseded** chunk (ledger key the compactor no longer emits) is removed
  from **BOTH** the store and the ledger;
* **reconcile** flags an injected orphan / missing / mismatch, an in-sync entity
  reports healthy, and ``repair=True`` heals the drift;
* namespace isolation: entity A's vectors never appear in entity B's namespace.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from app.schemas.context import ContextChunk
from app.services.context_vectorsync import (
    namespace_for,
    pinecone_id_for,
    reconcile,
    sync_vectors,
)
from integrations.embeddings import FakeEmbedder
from integrations.vectorstore import InMemoryVectorStore, VectorItem

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class SpyEmbedder(FakeEmbedder):
    """A real (deterministic) ``FakeEmbedder`` that records every text it embeds,
    so a test can prove an unchanged chunk is never sent to the provider."""

    def __init__(self) -> None:
        super().__init__(dim=1024, model="fake-embed-1")
        self.embedded_texts: list[str] = []
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.embedded_texts.extend(texts)
        return super().embed(texts)


class FakeLedger:
    """In-memory ``context_vectors`` ledger keyed by (entity_type, entity_id, chunk_key).

    Mirrors ``ContextRepo``: ``record_vector`` upserts, ``delete_vector`` pops and
    RETURNS the deleted row (so the sync core can GC the store from its pinecone_id),
    ``list_vectors`` is the per-entity authority ordered by chunk_key.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}

    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for key, row in sorted(self.rows.items())
            if key[0] == entity_type and key[1] == entity_id
        ]

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
            "entity_type": entity_type,
            "entity_id": entity_id,
            "chunk_key": chunk_key,
            "pinecone_id": pinecone_id,
            "content_checksum": content_checksum,
            "version": version,
            "dim": dim,
            "model": model,
        }
        self.rows[(entity_type, entity_id, chunk_key)] = row
        return dict(row)

    def delete_vector(
        self, entity_type: str, entity_id: str, chunk_key: str
    ) -> dict[str, Any] | None:
        return self.rows.pop((entity_type, entity_id, chunk_key), None)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _chunk(chunk_key: str, content: str) -> ContextChunk:
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ContextChunk(chunk_key=chunk_key, content=content, content_checksum=checksum)


def _store_ids(store: InMemoryVectorStore, namespace: str) -> set[str]:
    return {item.id for item in store.list_items(namespace)}


def _ledger_keys(ledger: FakeLedger, entity_type: str, entity_id: str) -> set[str]:
    return {row["chunk_key"] for row in ledger.list_vectors(entity_type, entity_id)}


ENT = ("client", "cl-1")


def _fixture() -> tuple[SpyEmbedder, InMemoryVectorStore, FakeLedger]:
    return SpyEmbedder(), InMemoryVectorStore(), FakeLedger()


# --------------------------------------------------------------------------- #
# Unchanged chunk => NOT re-embedded
# --------------------------------------------------------------------------- #
def test_unchanged_chunk_is_not_reembedded() -> None:
    embedder, store, ledger = _fixture()
    chunks = [_chunk("summary", "alpha living summary")]

    first = sync_vectors(*ENT, chunks, version=1, embedder=embedder, store=store, ledger=ledger)
    assert first.upserted == ["summary"]
    assert first.embedded_count == 1
    before = ledger.list_vectors(*ENT)

    embedder.embedded_texts.clear()
    embedder.calls = 0

    # Re-sync the identical chunk: same checksum => a pure skip.
    second = sync_vectors(*ENT, chunks, version=2, embedder=embedder, store=store, ledger=ledger)
    assert second.skipped == ["summary"]
    assert second.upserted == []
    assert second.embedded_count == 0
    assert embedder.calls == 0  # provider never touched for unchanged text
    assert embedder.embedded_texts == []
    # Ledger untouched: version did NOT advance to 2 (no re-record happened).
    assert ledger.list_vectors(*ENT) == before


# --------------------------------------------------------------------------- #
# Changed chunk => embedded once, store + ledger advance
# --------------------------------------------------------------------------- #
def test_changed_chunk_is_reembedded_and_ledger_advances() -> None:
    embedder, store, ledger = _fixture()
    namespace = namespace_for(*ENT)
    sync_vectors(
        *ENT, [_chunk("summary", "old prose")], version=1,
        embedder=embedder, store=store, ledger=ledger,
    )
    embedder.embedded_texts.clear()

    changed = _chunk("summary", "brand new prose")
    result = sync_vectors(
        *ENT, [changed], version=2, embedder=embedder, store=store, ledger=ledger,
    )
    assert result.upserted == ["summary"]
    assert result.embedded_count == 1
    assert embedder.embedded_texts == ["brand new prose"]  # only the changed content

    # Store holds the NEW vector: same stable id, updated metadata; a query for the
    # new content returns it at ~1.0 cosine.
    pid = pinecone_id_for(*ENT, "summary")
    items = {item.id: item for item in store.list_items(namespace)}
    assert items[pid].metadata["content_checksum"] == changed.content_checksum
    assert items[pid].metadata["version"] == 2
    top = store.query(namespace, embedder.embed(["brand new prose"])[0], top_k=1)
    assert top[0].id == pid
    assert top[0].score == pytest.approx(1.0, abs=1e-6)

    # Ledger checksum + version advanced.
    row = ledger.list_vectors(*ENT)[0]
    assert row["content_checksum"] == changed.content_checksum
    assert row["version"] == 2


# --------------------------------------------------------------------------- #
# New chunk => embedded + upserted + ledger row created
# --------------------------------------------------------------------------- #
def test_new_chunk_is_embedded_upserted_and_recorded() -> None:
    embedder, store, ledger = _fixture()
    namespace = namespace_for(*ENT)
    sync_vectors(
        *ENT, [_chunk("summary", "s")], version=1,
        embedder=embedder, store=store, ledger=ledger,
    )
    embedder.embedded_texts.clear()

    result = sync_vectors(
        *ENT,
        [_chunk("summary", "s"), _chunk("facts:client", "tier: A")],
        version=2, embedder=embedder, store=store, ledger=ledger,
    )
    assert result.skipped == ["summary"]  # unchanged
    assert result.upserted == ["facts:client"]  # only the new key
    assert embedder.embedded_texts == ["tier: A"]

    assert _ledger_keys(ledger, *ENT) == {"summary", "facts:client"}
    assert pinecone_id_for(*ENT, "facts:client") in _store_ids(store, namespace)


# --------------------------------------------------------------------------- #
# Superseded chunk => deleted from BOTH the store AND the ledger
# --------------------------------------------------------------------------- #
def test_superseded_chunk_is_deleted_from_both_store_and_ledger() -> None:
    embedder, store, ledger = _fixture()
    namespace = namespace_for(*ENT)
    sync_vectors(
        *ENT,
        [_chunk("summary", "s"), _chunk("facts:client", "tier: A")],
        version=1, embedder=embedder, store=store, ledger=ledger,
    )
    gone_id = pinecone_id_for(*ENT, "facts:client")
    assert gone_id in _store_ids(store, namespace)
    assert "facts:client" in _ledger_keys(ledger, *ENT)

    # The compactor no longer emits facts:client -> it is superseded.
    result = sync_vectors(
        *ENT, [_chunk("summary", "s")], version=2,
        embedder=embedder, store=store, ledger=ledger,
    )
    assert result.deleted == ["facts:client"]

    # Removed from the STORE: not in the namespace, and a query for its exact
    # content can never return it.
    assert gone_id not in _store_ids(store, namespace)
    hits = store.query(namespace, embedder.embed(["tier: A"])[0], top_k=10)
    assert gone_id not in {hit.id for hit in hits}
    # Removed from the LEDGER too.
    assert "facts:client" not in _ledger_keys(ledger, *ENT)
    assert _ledger_keys(ledger, *ENT) == {"summary"}


# --------------------------------------------------------------------------- #
# reconcile: healthy / orphan / missing / mismatch
# --------------------------------------------------------------------------- #
def _seed(embedder: SpyEmbedder, store: InMemoryVectorStore, ledger: FakeLedger) -> list[ContextChunk]:
    chunks = [_chunk("summary", "s"), _chunk("facts:client", "tier: A")]
    sync_vectors(*ENT, chunks, version=3, embedder=embedder, store=store, ledger=ledger)
    return chunks


def test_reconcile_healthy_entity_reports_no_drift() -> None:
    embedder, store, ledger = _fixture()
    _seed(embedder, store, ledger)
    report = reconcile(*ENT, store=store, ledger=ledger)
    assert report.healthy
    assert report.drift_count == 0
    assert report.orphans == report.missing == report.mismatched == []


def test_reconcile_flags_an_orphan() -> None:
    embedder, store, ledger = _fixture()
    _seed(embedder, store, ledger)
    namespace = namespace_for(*ENT)
    # A vector in the store with no ledger row.
    store.upsert(
        namespace,
        [VectorItem(id="client:cl-1#ghost", vector=embedder.embed(["x"])[0], metadata={"chunk_key": "ghost"})],
    )
    report = reconcile(*ENT, store=store, ledger=ledger)
    assert not report.healthy
    assert [d.pinecone_id for d in report.orphans] == ["client:cl-1#ghost"]
    assert report.missing == report.mismatched == []


def test_reconcile_flags_a_missing_vector() -> None:
    embedder, store, ledger = _fixture()
    _seed(embedder, store, ledger)
    namespace = namespace_for(*ENT)
    # A ledger row whose store vector vanished.
    store.delete(namespace, [pinecone_id_for(*ENT, "facts:client")])
    report = reconcile(*ENT, store=store, ledger=ledger)
    assert not report.healthy
    assert [d.chunk_key for d in report.missing] == ["facts:client"]
    assert report.orphans == report.mismatched == []


def test_reconcile_flags_a_checksum_mismatch() -> None:
    embedder, store, ledger = _fixture()
    _seed(embedder, store, ledger)
    namespace = namespace_for(*ENT)
    pid = pinecone_id_for(*ENT, "summary")
    # Same id in both, but the store's checksum/version drifted from the ledger.
    store.upsert(
        namespace,
        [VectorItem(id=pid, vector=embedder.embed(["s"])[0],
                    metadata={"chunk_key": "summary", "version": 99, "content_checksum": "STALE"})],
    )
    report = reconcile(*ENT, store=store, ledger=ledger)
    assert not report.healthy
    assert [d.chunk_key for d in report.mismatched] == ["summary"]
    drift = report.mismatched[0]
    assert drift.store_checksum == "STALE"
    assert drift.ledger_checksum != "STALE"


def test_reconcile_repair_heals_orphan_missing_and_mismatch() -> None:
    embedder, store, ledger = _fixture()
    chunks = _seed(embedder, store, ledger)
    namespace = namespace_for(*ENT)

    # Inject all three kinds of drift.
    store.upsert(namespace, [VectorItem(id="client:cl-1#ghost", vector=embedder.embed(["x"])[0], metadata={})])
    store.delete(namespace, [pinecone_id_for(*ENT, "facts:client")])  # missing
    store.upsert(
        namespace,
        [VectorItem(id=pinecone_id_for(*ENT, "summary"), vector=embedder.embed(["s"])[0],
                    metadata={"chunk_key": "summary", "version": 99, "content_checksum": "STALE"})],
    )

    report = reconcile(
        *ENT, store=store, ledger=ledger, repair=True,
        chunks=chunks, embedder=embedder, version=3,
    )
    # Detection still reflects the pre-repair drift...
    assert report.orphans_deleted == 1
    assert report.missing_repaired == 1
    assert report.mismatched_repaired == 1

    # ...and a fresh reconcile now sees a clean, in-sync entity.
    after = reconcile(*ENT, store=store, ledger=ledger)
    assert after.healthy


# --------------------------------------------------------------------------- #
# Namespace isolation
# --------------------------------------------------------------------------- #
def test_namespace_isolation_between_entities() -> None:
    embedder, store, ledger = _fixture()
    sync_vectors(
        "client", "A", [_chunk("summary", "a-summary")], version=1,
        embedder=embedder, store=store, ledger=ledger,
    )
    sync_vectors(
        "client", "B", [_chunk("summary", "b-summary")], version=1,
        embedder=embedder, store=store, ledger=ledger,
    )
    ns_a = namespace_for("client", "A")
    ns_b = namespace_for("client", "B")

    a_ids = _store_ids(store, ns_a)
    b_ids = _store_ids(store, ns_b)
    assert a_ids == {pinecone_id_for("client", "A", "summary")}
    assert b_ids == {pinecone_id_for("client", "B", "summary")}
    assert a_ids.isdisjoint(b_ids)  # B's vector never leaks into A's namespace

    # A query in A's namespace can only ever return A's vectors.
    hits = store.query(ns_a, embedder.embed(["b-summary"])[0], top_k=10)
    assert all(hit.id in a_ids for hit in hits)
