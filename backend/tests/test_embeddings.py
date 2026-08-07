"""Unit gate for the OpenAI embeddings provider (EMBEDDINGS_PROVIDER=openai).

Covers ``OpenAIEmbedder`` over ``httpx.MockTransport`` (parses the OpenAI
``/v1/embeddings`` response into order-correct vectors, the key rides in the
``Authorization: Bearer`` header, the body carries model + input + dimensions, empty
input is a network-free no-op, a malformed response raises ``ProviderCallError``, and
a keyless construction degrades via ``ProviderNotConfiguredError``), plus the provider
factory selecting the right embedder off ``EMBEDDINGS_PROVIDER`` (openai vs the intact
Voyage default). No SDK / network: everything is mocked HTTP or a monkeypatched class.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from integrations import context_providers as cp
from integrations.context_providers import context_providers_from_settings
from integrations.embeddings import Embedder, OpenAIEmbedder
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

pytestmark = pytest.mark.unit

Handler = Callable[[httpx.Request], httpx.Response]


def _with_mock(seam: Any, handler: Handler) -> None:
    """Swap a real seam's httpx client for a MockTransport one, KEEPING its base_url
    + headers (so the Bearer auth still rides the request and relative paths resolve)."""
    old = seam._client
    seam._client = httpx.Client(
        base_url=old.base_url, headers=old.headers, transport=httpx.MockTransport(handler)
    )


def _embeddings_response(vectors: list[list[float]], *, reverse: bool = False) -> dict[str, Any]:
    """Build a realistic OpenAI /v1/embeddings payload; ``reverse`` scrambles the
    data order (keeping each item's ``index``) to prove the parser re-sorts."""
    order = list(range(len(vectors)))
    if reverse:
        order = order[::-1]
    data = [{"object": "embedding", "index": i, "embedding": vectors[i]} for i in order]
    return {
        "object": "list",
        "data": data,
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


# --------------------------------------------------------------------------- #
# OpenAIEmbedder - Protocol conformance + HTTP behaviour via MockTransport
# --------------------------------------------------------------------------- #
def test_openai_embedder_satisfies_embedder_protocol() -> None:
    # Construction is network-free; it only builds an httpx.Client.
    assert isinstance(OpenAIEmbedder(api_key="k"), Embedder)


def test_openai_embedder_default_model_and_dim() -> None:
    emb = OpenAIEmbedder(api_key="k")
    assert emb.model == "text-embedding-3-small"
    assert emb.dim == 1536  # OpenAI's native default (vs Voyage's 1024)


def test_openai_embedder_parses_vectors_and_sends_key_model_dimensions() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_embeddings_response([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]))

    emb = OpenAIEmbedder(api_key="super-secret", dim=3)
    _with_mock(emb, handler)
    out = emb.embed(["alpha", "beta"])

    assert out == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]  # parsed 1:1, in input order
    assert seen["auth"] == "Bearer super-secret"  # key in the header, never a URL/log
    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/embeddings"
    assert seen["body"] == {
        "model": "text-embedding-3-small",
        "input": ["alpha", "beta"],
        "dimensions": 3,  # output length pinned to dim
    }


def test_openai_embedder_reorders_scrambled_response_by_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embeddings_response([[1.0], [2.0], [3.0]], reverse=True))

    emb = OpenAIEmbedder(api_key="k", dim=1)
    _with_mock(emb, handler)
    assert emb.embed(["a", "b", "c"]) == [[1.0], [2.0], [3.0]]  # re-sorted to input order


def test_openai_embedder_empty_is_a_noop_without_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not fire
        raise AssertionError("empty input must not hit the network")

    emb = OpenAIEmbedder(api_key="k")
    _with_mock(emb, handler)
    assert emb.embed([]) == []


def test_openai_embedder_bad_shape_raises_provider_call_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0}]})  # item missing 'embedding'

    emb = OpenAIEmbedder(api_key="k", dim=2)
    _with_mock(emb, handler)
    with pytest.raises(ProviderCallError):
        emb.embed(["x"])


def test_openai_embedder_length_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embeddings_response([[1.0]]))  # 1 vector for 2 inputs

    emb = OpenAIEmbedder(api_key="k", dim=1)
    _with_mock(emb, handler)
    with pytest.raises(ProviderCallError):
        emb.embed(["x", "y"])


def test_openai_embedder_secret_never_in_4xx_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    emb = OpenAIEmbedder(api_key="super-secret", dim=2)
    _with_mock(emb, handler)
    with pytest.raises(ProviderCallError) as exc:
        emb.embed(["x"])
    assert "super-secret" not in str(exc.value)  # secret never in the error text


def test_openai_embedder_requires_a_key() -> None:
    # Degrade path: a real impl built without a key names the fix (never a no-op).
    with pytest.raises(ProviderNotConfiguredError, match="EMBEDDINGS_PROVIDER=openai"):
        OpenAIEmbedder(api_key="")


# --------------------------------------------------------------------------- #
# Factory selection off EMBEDDINGS_PROVIDER (monkeypatched: no SDK/network)
# --------------------------------------------------------------------------- #
def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _stub_non_embedder_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "AnthropicSummarizer", lambda **_k: "S")
    monkeypatch.setattr(cp, "PineconeVectorStore", lambda **_k: "V")


def test_factory_selects_openai_embedder_when_provider_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, object] = {}
    _stub_non_embedder_seams(monkeypatch)
    monkeypatch.setattr(cp, "OpenAIEmbedder", lambda **kwargs: built.update(kwargs) or "OPENAI_EMB")

    settings = _settings(
        anthropic_api_key="a",
        embeddings_api_key="ek",
        pinecone_api_key="pk",
        pinecone_index="idx",
        embeddings_provider="openai",
        embeddings_model="text-embedding-3-small",
    )
    bundle = context_providers_from_settings(settings)
    assert bundle is not None
    assert bundle.embedder == "OPENAI_EMB"
    # The decrypted key + configured model/dim are handed to the OpenAI embedder only.
    assert built == {"api_key": "ek", "model": "text-embedding-3-small", "dim": 1024}


def test_factory_openai_defaults_model_when_left_at_voyage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Operator switched the provider to openai but left EMBEDDINGS_MODEL at the Voyage
    # default -> the factory substitutes OpenAI's default rather than passing "voyage-3".
    built: dict[str, object] = {}
    _stub_non_embedder_seams(monkeypatch)
    monkeypatch.setattr(cp, "OpenAIEmbedder", lambda **kwargs: built.update(kwargs) or "E")

    settings = _settings(
        anthropic_api_key="a",
        embeddings_api_key="ek",
        pinecone_api_key="pk",
        pinecone_index="idx",
        embeddings_provider="openai",  # embeddings_model stays "voyage-3"
    )
    context_providers_from_settings(settings)
    assert built["model"] == "text-embedding-3-small"


def test_factory_voyage_path_is_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: the default provider still selects the Voyage embedder unchanged.
    built: dict[str, object] = {}
    _stub_non_embedder_seams(monkeypatch)
    monkeypatch.setattr(cp, "VoyageEmbedder", lambda **kwargs: built.update(kwargs) or "VOY")

    settings = _settings(
        anthropic_api_key="a",
        embeddings_api_key="ek",
        pinecone_api_key="pk",
        pinecone_index="idx",
    )  # embeddings_provider defaults to "voyage"
    bundle = context_providers_from_settings(settings)
    assert bundle is not None
    assert bundle.embedder == "VOY"
    assert built == {"api_key": "ek", "model": "voyage-3", "dim": 1024}


def test_factory_degrades_without_a_key_regardless_of_provider() -> None:
    # No keys -> degraded None even with provider=openai (never constructs a real impl).
    assert context_providers_from_settings(_settings(embeddings_provider="openai")) is None
