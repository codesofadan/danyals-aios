"""P6B-6: VECTOR SYNC + supersession GC + reconcile.

The governing principle of Part 6B: **Postgres is the source of truth, Pinecone is
a DERIVED index**. The ``context_vectors`` ledger row is the authority for what is
currently embedded; the vector store is fully reconstructable from it. This module
keeps the two in step and *detects* (optionally repairs) drift between them.

Three responsibilities, all pure-ish (injected ``Embedder`` / ``VectorStore`` /
ledger - no direct network, no config): the worker (P6B-7) wires a cost-gated
``GatedEmbedder`` + Pinecone/InMemory store + the real ``ContextRepo``.

* :func:`sync_vectors` - **re-embed ONLY changed chunks.** Diff the compactor's
  fresh chunks against the ledger by ``content_checksum``: a new or checksum-changed
  ``chunk_key`` is embedded + upserted + recorded; an unchanged one is SKIPPED
  entirely (no embed, no upsert, no gate call - the cheapest possible no-op); a
  ledger ``chunk_key`` the compactor no longer emits is *superseded* and GC'd from
  **BOTH** the store and the ledger. This is what makes the derived index track a
  living, self-superseding context without ever re-paying for unchanged text.
* :func:`reconcile` - a **drift detector**: compare the ledger against the store
  namespace and flag ``orphan`` (in the store, not the ledger), ``missing`` (a
  ledger row with no vector), ``mismatch`` (both present but checksum/version
  differ). By default it only *reports* (the scheduled sweep in P6B-9 consumes it);
  with ``repair=True`` it deletes orphans and - when handed the current chunks +
  an embedder - force-re-embeds the missing/mismatched (which plain ``sync`` would
  wrongly SKIP, since their ledger checksum still matches the content).

Every vector's metadata carries ``chunk_key`` + ``version`` + ``content_checksum``
so reconcile can compare the store side without a second ledger read - the checksum
in the metadata is what makes ``mismatch`` detectable store-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.schemas.context import ContextChunk
from integrations.embeddings import Embedder
from integrations.vectorstore import VectorItem, VectorStore


# --------------------------------------------------------------------------- #
# The ledger seam (ContextRepo satisfies this structurally)
# --------------------------------------------------------------------------- #
class VectorLedger(Protocol):
    """The ``context_vectors`` methods this module needs (see ``ContextRepo``).

    ``list_vectors`` is the authority for "what is currently embedded"; the writes
    are the service-role upsert/delete the compaction worker owns. A row carries at
    least ``chunk_key``, ``pinecone_id``, ``content_checksum`` and ``version``.
    """

    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]: ...

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
    ) -> dict[str, Any]: ...

    def delete_vector(
        self, entity_type: str, entity_id: str, chunk_key: str
    ) -> dict[str, Any] | None: ...


# --------------------------------------------------------------------------- #
# Result / report types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class VectorSyncResult:
    """What one :func:`sync_vectors` pass did, by ``chunk_key``.

    ``upserted`` = embedded + written to store + ledger; ``skipped`` = unchanged
    (checksum match, not touched); ``deleted`` = superseded, removed from BOTH the
    store and the ledger. ``embedded_count`` is the number of provider vectors paid
    for (== ``len(upserted)``); ``model``/``dim`` describe the embedding written.
    """

    upserted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    embedded_count: int = 0
    model: str = ""
    dim: int = 0


@dataclass(frozen=True)
class DriftItem:
    """One reconcile discrepancy between the ledger and the store.

    Any side that is absent leaves its checksum/version ``None`` (a ``missing``
    item has no store side; an ``orphan`` has no ledger side).
    """

    chunk_key: str
    pinecone_id: str
    ledger_checksum: str | None = None
    store_checksum: str | None = None
    ledger_version: int | None = None
    store_version: int | None = None


@dataclass(frozen=True)
class ReconcileReport:
    """The ledger-vs-store consistency verdict for one entity namespace.

    ``orphans`` are in the store but not the ledger (delete them); ``missing`` are
    ledger rows with no vector (re-embed them); ``mismatched`` are present in both
    but their checksum or version disagrees (re-embed to the ledger's truth). The
    ``*_repaired`` counters are 0 unless :func:`reconcile` ran with ``repair=True``.
    """

    entity_type: str
    entity_id: str
    namespace: str
    orphans: list[DriftItem] = field(default_factory=list)
    missing: list[DriftItem] = field(default_factory=list)
    mismatched: list[DriftItem] = field(default_factory=list)
    orphans_deleted: int = 0
    missing_repaired: int = 0
    mismatched_repaired: int = 0

    @property
    def healthy(self) -> bool:
        """True when the store and ledger agree exactly (no drift of any kind)."""
        return not (self.orphans or self.missing or self.mismatched)

    @property
    def drift_count(self) -> int:
        """Total flagged discrepancies across all three categories."""
        return len(self.orphans) + len(self.missing) + len(self.mismatched)


# --------------------------------------------------------------------------- #
# Conventions
# --------------------------------------------------------------------------- #
def namespace_for(entity_type: str, entity_id: str) -> str:
    """The per-entity vector namespace ``entity_type:entity_id`` (tenant partition)."""
    return f"{entity_type}:{entity_id}"


def pinecone_id_for(entity_type: str, entity_id: str, chunk_key: str) -> str:
    """The stable per-chunk vector id ``entity_type:entity_id#chunk_key``.

    Stable across re-embeds of the SAME chunk, so a changed-content re-upsert
    overwrites the prior vector in place (the id IS the upsert key) rather than
    leaking a duplicate.
    """
    return f"{entity_type}:{entity_id}#{chunk_key}"


def _embed_model(embedder: Embedder, model: str | None) -> str:
    """The embedding model to stamp on the ledger: explicit override else the
    embedder's own ``model`` attribute (the ``Embedder`` Protocol declares only
    ``dim``, but every concrete embedder exposes ``model``)."""
    if model is not None:
        return model
    return str(getattr(embedder, "model", ""))


def _item_for(
    entity_type: str, entity_id: str, chunk: ContextChunk, vector: list[float], *, version: int
) -> VectorItem:
    """Build the store item for a chunk: stable id + vector + drift-comparable
    metadata (``chunk_key`` + ``version`` + ``content_checksum``)."""
    return VectorItem(
        id=pinecone_id_for(entity_type, entity_id, chunk.chunk_key),
        vector=vector,
        metadata={
            "chunk_key": chunk.chunk_key,
            "version": version,
            "content_checksum": chunk.content_checksum,
        },
    )


# --------------------------------------------------------------------------- #
# 1. Sync - embed only the changed, GC the superseded from BOTH stores
# --------------------------------------------------------------------------- #
def sync_vectors(
    entity_type: str,
    entity_id: str,
    chunks: list[ContextChunk],
    *,
    version: int,
    embedder: Embedder,
    store: VectorStore,
    ledger: VectorLedger,
    model: str | None = None,
) -> VectorSyncResult:
    """Re-embed only the changed chunks, upsert them, and GC superseded vectors.

    The ledger (``content_checksum`` per ``chunk_key``) is the diff baseline:

    * a ``chunk_key`` that is **new**, or whose ``content_checksum`` **changed**,
      is embedded (one batched ``embedder.embed`` call), upserted to the entity's
      namespace, and recorded in the ledger;
    * a ``chunk_key`` present with an **identical checksum** is SKIPPED entirely -
      no embed, no upsert, no ledger write, not even a gate call;
    * a ledger ``chunk_key`` **absent from ``chunks``** is *superseded*: deleted
      from the ledger AND the vector store (supersession GC removes it from BOTH).

    Deterministic given a deterministic embedder. Returns a :class:`VectorSyncResult`
    with the per-``chunk_key`` upserted / skipped / deleted breakdown.
    """
    namespace = namespace_for(entity_type, entity_id)
    ledger_by_key = {row["chunk_key"]: row for row in ledger.list_vectors(entity_type, entity_id)}
    fresh_keys = {chunk.chunk_key for chunk in chunks}

    to_embed: list[ContextChunk] = []
    skipped: list[str] = []
    for chunk in chunks:
        prior = ledger_by_key.get(chunk.chunk_key)
        if prior is not None and prior.get("content_checksum") == chunk.content_checksum:
            skipped.append(chunk.chunk_key)  # unchanged: no embed, no upsert, no cost
        else:
            to_embed.append(chunk)

    resolved_model = _embed_model(embedder, model)
    dim = int(embedder.dim)

    # Embed the changed chunks in one batch, upsert to the store, record in the ledger.
    upserted: list[str] = []
    if to_embed:
        vectors = embedder.embed([chunk.content for chunk in to_embed])
        items = [
            _item_for(entity_type, entity_id, chunk, vector, version=version)
            for chunk, vector in zip(to_embed, vectors, strict=True)
        ]
        store.upsert(namespace, items)
        for chunk, item in zip(to_embed, items, strict=True):
            ledger.record_vector(
                entity_type,
                entity_id,
                chunk_key=chunk.chunk_key,
                pinecone_id=item.id,
                content_checksum=chunk.content_checksum,
                version=version,
                dim=dim,
                model=resolved_model,
            )
            upserted.append(chunk.chunk_key)

    # Supersession GC: drop each stale ledger key from the ledger AND the store.
    deleted: list[str] = []
    for chunk_key in sorted(set(ledger_by_key) - fresh_keys):
        removed = ledger.delete_vector(entity_type, entity_id, chunk_key)
        pinecone_id = (removed or ledger_by_key[chunk_key]).get("pinecone_id")
        if pinecone_id:
            store.delete(namespace, [str(pinecone_id)])
        deleted.append(chunk_key)

    return VectorSyncResult(
        upserted=upserted,
        skipped=skipped,
        deleted=deleted,
        embedded_count=len(to_embed),
        model=resolved_model,
        dim=dim,
    )


# --------------------------------------------------------------------------- #
# 2. Reconcile - detect (and optionally repair) ledger-vs-store drift
# --------------------------------------------------------------------------- #
def reconcile(
    entity_type: str,
    entity_id: str,
    *,
    store: VectorStore,
    ledger: VectorLedger,
    repair: bool = False,
    chunks: list[ContextChunk] | None = None,
    embedder: Embedder | None = None,
    version: int = 0,
    model: str | None = None,
) -> ReconcileReport:
    """Compare the ledger against the store namespace and flag any drift.

    Detection (always): ``orphan`` = a vector in the store with no ledger row;
    ``missing`` = a ledger row whose vector is gone from the store; ``mismatch`` =
    both present but the stored ``content_checksum``/``version`` disagrees with the
    ledger. A healthy entity yields an empty report.

    Repair (``repair=True`` - the flag; default off keeps it a pure detector):
    orphans are deleted from the store; ``missing``/``mismatched`` are force-
    re-embedded to the ledger's truth **iff** the caller supplies the current
    ``chunks`` + an ``embedder`` (plain :func:`sync_vectors` cannot fix these - it
    would SKIP them, their ledger checksum still matching the content). The returned
    report reflects the drift as *detected*, with the ``*_repaired`` counters set.
    """
    namespace = namespace_for(entity_type, entity_id)
    ledger_by_key = {row["chunk_key"]: row for row in ledger.list_vectors(entity_type, entity_id)}
    ledger_by_id = {str(row["pinecone_id"]): row for row in ledger_by_key.values()}
    store_by_id = {item.id: item for item in store.list_items(namespace)}

    orphans: list[DriftItem] = []
    for vec_id, item in store_by_id.items():
        if vec_id not in ledger_by_id:
            orphans.append(
                DriftItem(
                    chunk_key=str(item.metadata.get("chunk_key", "")),
                    pinecone_id=vec_id,
                    store_checksum=_opt_str(item.metadata.get("content_checksum")),
                    store_version=_opt_int(item.metadata.get("version")),
                )
            )

    missing: list[DriftItem] = []
    mismatched: list[DriftItem] = []
    for chunk_key, row in ledger_by_key.items():
        pinecone_id = str(row["pinecone_id"])
        stored = store_by_id.get(pinecone_id)
        ledger_checksum = _opt_str(row.get("content_checksum"))
        ledger_version = _opt_int(row.get("version"))
        if stored is None:
            missing.append(
                DriftItem(
                    chunk_key=chunk_key,
                    pinecone_id=pinecone_id,
                    ledger_checksum=ledger_checksum,
                    ledger_version=ledger_version,
                )
            )
            continue
        store_checksum = _opt_str(stored.metadata.get("content_checksum"))
        store_version = _opt_int(stored.metadata.get("version"))
        checksum_drift = store_checksum is not None and store_checksum != ledger_checksum
        version_drift = store_version is not None and store_version != ledger_version
        if checksum_drift or version_drift:
            mismatched.append(
                DriftItem(
                    chunk_key=chunk_key,
                    pinecone_id=pinecone_id,
                    ledger_checksum=ledger_checksum,
                    store_checksum=store_checksum,
                    ledger_version=ledger_version,
                    store_version=store_version,
                )
            )

    orphans_deleted = missing_repaired = mismatched_repaired = 0
    if repair:
        orphans_deleted, missing_repaired, mismatched_repaired = _repair(
            entity_type,
            entity_id,
            namespace,
            orphans=orphans,
            missing=missing,
            mismatched=mismatched,
            store=store,
            ledger=ledger,
            chunks=chunks,
            embedder=embedder,
            version=version,
            model=model,
        )

    return ReconcileReport(
        entity_type=entity_type,
        entity_id=entity_id,
        namespace=namespace,
        orphans=orphans,
        missing=missing,
        mismatched=mismatched,
        orphans_deleted=orphans_deleted,
        missing_repaired=missing_repaired,
        mismatched_repaired=mismatched_repaired,
    )


def _repair(
    entity_type: str,
    entity_id: str,
    namespace: str,
    *,
    orphans: list[DriftItem],
    missing: list[DriftItem],
    mismatched: list[DriftItem],
    store: VectorStore,
    ledger: VectorLedger,
    chunks: list[ContextChunk] | None,
    embedder: Embedder | None,
    version: int,
    model: str | None,
) -> tuple[int, int, int]:
    """Apply repairs and return ``(orphans_deleted, missing_repaired, mismatched_repaired)``.

    Orphans are always deletable (a store id with no ledger row - just drop it).
    ``missing``/``mismatched`` need the chunk CONTENT to re-embed, so they are fixed
    only when both ``chunks`` and ``embedder`` are supplied; matched by ``chunk_key``.
    """
    # Orphans: present only in the store -> delete them there.
    orphan_ids = [item.pinecone_id for item in orphans if item.pinecone_id]
    if orphan_ids:
        store.delete(namespace, orphan_ids)

    if embedder is None or not chunks:
        return len(orphan_ids), 0, 0

    by_key = {chunk.chunk_key: chunk for chunk in chunks}
    resolved_model = _embed_model(embedder, model)
    dim = int(embedder.dim)

    def _reembed(items: list[DriftItem]) -> int:
        targets = [(d, by_key[d.chunk_key]) for d in items if d.chunk_key in by_key]
        if not targets:
            return 0
        vectors = embedder.embed([chunk.content for _, chunk in targets])
        store_items = [
            _item_for(entity_type, entity_id, chunk, vector, version=version)
            for (_, chunk), vector in zip(targets, vectors, strict=True)
        ]
        store.upsert(namespace, store_items)
        for (_, chunk), item in zip(targets, store_items, strict=True):
            ledger.record_vector(
                entity_type,
                entity_id,
                chunk_key=chunk.chunk_key,
                pinecone_id=item.id,
                content_checksum=chunk.content_checksum,
                version=version,
                dim=dim,
                model=resolved_model,
            )
        return len(targets)

    return len(orphan_ids), _reembed(missing), _reembed(mismatched)


def _opt_str(value: Any) -> str | None:
    """``str(value)`` or ``None`` when absent - keeps drift fields honestly nullable."""
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    """``int(value)`` or ``None`` when absent/unparseable (store metadata may round-trip
    a version as a float via the provider)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
