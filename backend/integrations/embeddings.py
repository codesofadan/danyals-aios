"""Embedder seam (P6B-3): the ONLY door to an embeddings provider.

Anthropic has NO embeddings API, so the Embedder is a SEPARATE provider. We use
**Voyage AI**: it is Anthropic's recommended embeddings partner, ships the
cleanest lazy-import SDK (``voyageai.Client``), distinguishes document vs query
``input_type`` (better retrieval), and its ``voyage-3`` dimension (1024) matches
the ``context_vectors`` ledger's stored ``dim`` and the ``FakeEmbedder`` - so real
and fake are drop-in swappable and the Pinecone index dimension stays consistent.

Reachable only through the ``Embedder`` Protocol so P6B-4 can wrap it in a
cost-gated ``GatedEmbedder`` (cache_key = content_checksum => unchanged text is
$0). Three impls select on ``EMBEDDINGS_PROVIDER``:

* ``VoyageEmbedder`` (``EMBEDDINGS_PROVIDER=voyage``, the default) - lazy
  ``import voyageai`` (OPTIONAL ``[ai]`` extra). Absent SDK/key ->
  ``ProviderNotConfiguredError``.
* ``OpenAIEmbedder`` (``EMBEDDINGS_PROVIDER=openai``) - plain HTTP to the OpenAI
  ``/v1/embeddings`` endpoint over the shared sync ``HttpProviderClient`` (no SDK).
  The activation path for a client who has an OpenAI key but NO Voyage key.
* ``FakeEmbedder`` - DETERMINISTIC hash->vector of a fixed ``dim``, L2-normalized:
  a sha256 of the text is expanded to ``dim`` bytes, centered, and normalized. No
  network, stable across runs, so golden-set retrieval tests are reproducible.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

_INSTALL_HINT = "install the AI extra (pip install -e '.[ai]') and set EMBEDDINGS_API_KEY"
_OPENAI_INSTALL_HINT = (
    "set EMBEDDINGS_PROVIDER=openai + EMBEDDINGS_API_KEY=<openai key> to enable OpenAI embeddings"
)
_OPENAI_EMBEDDINGS_BASE = "https://api.openai.com"
# The OpenAI text-embedding-3 family's native default (text-embedding-3-small). The
# ``dimensions`` request param can truncate this to any smaller size (see the class
# docstring), so the embedder always returns exactly ``dim``-length vectors.
_OPENAI_DEFAULT_MODEL = "text-embedding-3-small"
_OPENAI_DEFAULT_DIM = 1536


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


class OpenAIEmbedder(HttpProviderClient):
    """Real ``Embedder`` over the OpenAI embeddings REST API (no SDK, plain HTTP).

    Calls ``POST https://api.openai.com/v1/embeddings`` with
    ``{"model": .., "input": [..], "dimensions": dim}`` and the key in an
    ``Authorization: Bearer`` header (never logged), over the shared sync
    ``HttpProviderClient`` (retry/backoff on 429/5xx, secret-safe 4xx errors) - the
    same base the ``OpenAIImageGenerator`` uses. This is the activation path for a
    client who has an OpenAI key but NO Voyage key: set ``EMBEDDINGS_PROVIDER=openai``
    and ``EMBEDDINGS_API_KEY=<openai key>``.

    **Dimension note.** ``text-embedding-3-small`` is **1536** dims natively vs Voyage
    ``voyage-3``'s **1024** - so the vector index (Pinecone) dimension MUST match the
    chosen provider. The text-embedding-3 models accept a ``dimensions`` request
    parameter that truncates the output, so this embedder PINS the returned vector
    length to ``dim`` (== ``EMBEDDINGS_DIM`` == the ``FakeEmbedder`` dim == the Pinecone
    index dimension), keeping real<->fake drop-in swappable and the index dimension
    always consistent with the active provider. Because Pinecone is unconfigured here,
    the derived index is the dimension-flexible in-memory fake and Postgres stays
    authoritative - so switching the provider to OpenAI activates safely with no
    reindex. The Voyage default (1024) is UNCHANGED.
    """

    provider = "openai_embed"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = _OPENAI_DEFAULT_MODEL,
        dim: int = _OPENAI_DEFAULT_DIM,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"OpenAI embedder unavailable: {_OPENAI_INSTALL_HINT}")
        super().__init__(
            base_url=_OPENAI_EMBEDDINGS_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body: dict[str, object] = {
            "model": self.model,
            "input": list(texts),
            "dimensions": self.dim,  # pin the output length to dim (see class docstring)
        }
        data = self.request_json("POST", "/v1/embeddings", json_body=body)
        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise ProviderCallError("OpenAI embeddings response 'data' missing or length != input")

        def _index(item: object) -> int:
            # OpenAI documents same-order data, but each item carries an ``index`` -
            # sort by it defensively so a re-ordered response still maps 1:1 to inputs.
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                return int(item["index"])
            return 0

        vectors: list[list[float]] = []
        for item in sorted(items, key=_index):
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list):
                raise ProviderCallError("OpenAI embeddings response item missing an 'embedding'")
            vectors.append([float(value) for value in vector])
        return vectors


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
