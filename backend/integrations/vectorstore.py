"""VectorStore seam (P6B-3): the ONLY door to the vector index.

Pinecone is the derived index (Postgres is the source of truth; the store is
fully reconstructable from the ``context_vectors`` ledger). Every entity gets its
own namespace ``entity_type:entity_id`` so a query can never cross tenants.
Reachable only through the ``VectorStore`` Protocol. Two impls:

* ``PineconeVectorStore`` - lazy ``import pinecone`` (OPTIONAL ``[ai]`` extra).
  Tenacity retry/backoff on transient (network / Pinecone API) errors; key + index
  (+ optional host) from settings. Absent SDK/key -> ``ProviderNotConfiguredError``.
* ``InMemoryVectorStore`` - a dict-of-namespaces with REAL cosine similarity for
  ``query`` and exact upsert/delete, so the worker (P6B-7) and retrieval tests run
  fully live with no Pinecone.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Protocol, TypeVar, runtime_checkable

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from integrations.errors import ProviderNotConfiguredError

_T = TypeVar("_T")

_INSTALL_HINT = "install the AI extra (pip install -e '.[ai]') and set PINECONE_API_KEY + PINECONE_INDEX"


@dataclass(frozen=True)
class VectorItem:
    """One vector to upsert: a stable id, its values, and optional metadata."""

    id: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Match:
    """One ranked query hit: id, similarity score (higher = closer), metadata."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """Namespaced vector index: upsert, similarity query, delete-by-id.

    ``namespace`` is always ``entity_type:entity_id`` - the per-entity partition.
    ``list_items`` enumerates a whole namespace (id + metadata) - the reconcile
    sweep (P6B-6) needs it to detect vectors present in the store but absent from
    the Postgres ledger (orphans); it is never on the hot retrieval path.
    """

    def upsert(self, namespace: str, items: list[VectorItem]) -> None: ...
    def query(self, namespace: str, vector: list[float], top_k: int) -> list[Match]: ...
    def delete(self, namespace: str, ids: list[str]) -> None: ...
    def list_items(self, namespace: str) -> list[VectorItem]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in ``[-1, 1]``; 0.0 for mismatched-length or zero vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    """Live, offline ``VectorStore`` - dict of namespaces, exact cosine ranking."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, VectorItem]] = {}

    def upsert(self, namespace: str, items: list[VectorItem]) -> None:
        bucket = self._namespaces.setdefault(namespace, {})
        for item in items:
            bucket[item.id] = item  # id is the upsert key -> re-upsert overwrites

    def query(self, namespace: str, vector: list[float], top_k: int) -> list[Match]:
        bucket = self._namespaces.get(namespace, {})
        scored = [
            Match(id=item.id, score=_cosine(vector, item.vector), metadata=dict(item.metadata))
            for item in bucket.values()
        ]
        scored.sort(key=lambda match: match.score, reverse=True)
        return scored[: max(top_k, 0)]

    def delete(self, namespace: str, ids: list[str]) -> None:
        bucket = self._namespaces.get(namespace)
        if not bucket:
            return
        for id_ in ids:
            bucket.pop(id_, None)

    def list_items(self, namespace: str) -> list[VectorItem]:
        return list(self._namespaces.get(namespace, {}).values())


class PineconeVectorStore:
    """Real ``VectorStore`` backed by Pinecone; lazy-imports the ``pinecone`` SDK.

    Every op runs under tenacity retry/backoff on transient errors (network +
    Pinecone's own API exception) so a blip doesn't fail a compaction - Postgres
    stays authoritative, and reconcile (P6B-6) heals any residual drift.
    """

    def __init__(self, *, api_key: str, index: str, host: str | None = None) -> None:
        if not api_key or not index:
            raise ProviderNotConfiguredError(f"Pinecone vector store unavailable: {_INSTALL_HINT}")
        try:
            import pinecone
        except ImportError as exc:  # SDK not installed (base install omits the [ai] extra)
            raise ProviderNotConfiguredError(
                f"Pinecone vector store unavailable: {_INSTALL_HINT}"
            ) from exc
        client = pinecone.Pinecone(api_key=api_key)
        self._index = client.Index(host=host) if host else client.Index(index)
        # Backoff only on transient failures; a bad request should surface at once.
        transient: list[type[BaseException]] = [ConnectionError, TimeoutError, OSError]
        api_exc = getattr(getattr(pinecone, "exceptions", None), "PineconeApiException", None)
        if isinstance(api_exc, type):
            transient.append(api_exc)
        self._transient: tuple[type[BaseException], ...] = tuple(transient)

    def _run(self, operation: Callable[[], _T]) -> _T:
        for attempt in Retrying(
            retry=retry_if_exception_type(self._transient),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            stop=stop_after_attempt(4),
            reraise=True,
        ):
            with attempt:
                return operation()
        raise AssertionError("unreachable: tenacity reraises or returns")  # pragma: no cover

    def upsert(self, namespace: str, items: list[VectorItem]) -> None:
        if not items:
            return
        vectors = [
            {"id": item.id, "values": item.vector, "metadata": item.metadata} for item in items
        ]
        self._run(lambda: self._index.upsert(vectors=vectors, namespace=namespace))

    def query(self, namespace: str, vector: list[float], top_k: int) -> list[Match]:
        response = self._run(
            lambda: self._index.query(
                namespace=namespace,
                vector=vector,
                top_k=top_k,
                include_values=False,
                include_metadata=True,
            )
        )
        return [
            Match(id=m.id, score=float(m.score or 0.0), metadata=dict(m.metadata or {}))
            for m in response.matches
        ]

    def delete(self, namespace: str, ids: list[str]) -> None:
        if not ids:
            return
        self._run(lambda: self._index.delete(ids=ids, namespace=namespace))

    def list_items(self, namespace: str) -> list[VectorItem]:  # pragma: no cover - needs live Pinecone
        # ``index.list`` paginates ids for a namespace; ``fetch`` then returns each
        # vector's values + metadata. Batched by 1000 (Pinecone's fetch ceiling);
        # ``partial`` binds the batch so no loop variable is captured in a closure.
        ids: list[str] = []
        for page in self._index.list(namespace=namespace):
            ids.extend(page)
        items: list[VectorItem] = []
        for start in range(0, len(ids), 1000):
            batch = ids[start : start + 1000]
            response = self._run(partial(self._index.fetch, ids=batch, namespace=namespace))
            for vec_id, record in (response.vectors or {}).items():
                items.append(
                    VectorItem(
                        id=vec_id,
                        vector=list(record.values or []),
                        metadata=dict(record.metadata or {}),
                    )
                )
        return items
