"""Embedder seam (P6B-3): the ONLY door to an embeddings provider.

Anthropic has NO embeddings API, so the Embedder is a SEPARATE provider. We use
**Voyage AI**: it is Anthropic's recommended embeddings partner, ships the
cleanest lazy-import SDK (``voyageai.Client``), distinguishes document vs query
``input_type`` (better retrieval), and its ``voyage-3`` dimension (1024) matches
the ``context_vectors`` ledger's stored ``dim`` and the ``FakeEmbedder`` - so real
and fake are drop-in swappable and the Pinecone index dimension stays consistent.

Reachable only through the ``Embedder`` Protocol so P6B-4 can wrap it in a
cost-gated ``GatedEmbedder`` (cache_key = content_checksum => unchanged text is
$0). Two impls:

* ``VoyageEmbedder`` - lazy ``import voyageai`` (OPTIONAL ``[ai]`` extra). Absent
  SDK/key -> ``ProviderNotConfiguredError``.
* ``FakeEmbedder`` - DETERMINISTIC hash->vector of a fixed ``dim``, L2-normalized:
  a sha256 of the text is expanded to ``dim`` bytes, centered, and normalized. No
  network, stable across runs, so golden-set retrieval tests are reproducible.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

from integrations.errors import ProviderNotConfiguredError

_INSTALL_HINT = "install the AI extra (pip install -e '.[ai]') and set EMBEDDINGS_API_KEY"


@runtime_checkable
class Embedder(Protocol):
    """Turn texts into a list of ``dim``-length float vectors.

    ``dim`` is the fixed embedding dimension - it MUST equal the Pinecone index
    dimension and the ledger's stored ``dim`` so vectors round-trip.
    """

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VoyageEmbedder:
    """Real ``Embedder`` backed by Voyage AI; lazy-imports the ``voyageai`` SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "voyage-3",
        dim: int = 1024,
        input_type: str = "document",
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Voyage embedder unavailable: {_INSTALL_HINT}")
        try:
            import voyageai
        except ImportError as exc:  # SDK not installed (base install omits the [ai] extra)
            raise ProviderNotConfiguredError(
                f"Voyage embedder unavailable: {_INSTALL_HINT}"
            ) from exc
        self._client = voyageai.Client(api_key=api_key)
        self.model = model
        self.dim = dim
        self._input_type = input_type

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embed(texts, model=self.model, input_type=self._input_type)
        return [list(vector) for vector in result.embeddings]


class FakeEmbedder:
    """Deterministic, offline ``Embedder`` - sha256 -> ``dim`` floats, L2-normalized.

    Same text => same unit vector every run, so golden-set retrieval is stable and
    ``InMemoryVectorStore`` cosine ordering is reproducible in CI with no keys.
    """

    def __init__(self, *, dim: int = 1024, model: str = "fake-embed-1") -> None:
        self.dim = dim
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        raw = bytearray()
        counter = 0
        while len(raw) < self.dim:  # expand the hash deterministically to fill dim bytes
            raw += hashlib.sha256(f"{counter}:{text}".encode()).digest()
            counter += 1
        # Center bytes around zero so vectors aren't all-positive (real cosine spread).
        centered = [byte - 127.5 for byte in raw[: self.dim]]
        norm = math.sqrt(sum(value * value for value in centered))
        if norm == 0.0:
            return [0.0] * self.dim
        return [value / norm for value in centered]
