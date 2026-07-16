"""P6B-3 unit gate: the context AI provider seams (no network, no keys).

Covers the three Protocols and their fakes (Summarizer / Embedder / VectorStore),
the deterministic + L2-normalized FakeEmbedder, InMemoryVectorStore cosine
ranking + namespace isolation, the key-gated factory (degrades to None without
keys; SELECTS real impls with keys, monkeypatched so no SDK/network is touched),
and that the real impls raise a clear ProviderNotConfiguredError when built
without a key. No AI SDK is installed for the gate - everything here is fakes.
"""

from __future__ import annotations

import math

import pytest

from app.config import Settings
from integrations import context_providers as cp
from integrations.context_providers import (
    ContextProviders,
    context_providers_from_settings,
    providers_for_tests,
)
from integrations.embeddings import Embedder, FakeEmbedder, VoyageEmbedder
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import AnthropicSummarizer, FakeSummarizer, LLMResult, Summarizer
from integrations.vectorstore import (
    InMemoryVectorStore,
    Match,
    PineconeVectorStore,
    VectorItem,
    VectorStore,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Protocol conformance (runtime)
# --------------------------------------------------------------------------- #
def test_fakes_satisfy_protocols() -> None:
    assert isinstance(FakeSummarizer(), Summarizer)
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(InMemoryVectorStore(), VectorStore)


# --------------------------------------------------------------------------- #
# FakeSummarizer - deterministic + token counts
# --------------------------------------------------------------------------- #
def test_fake_summarizer_deterministic_and_meters() -> None:
    fake = FakeSummarizer()
    prompt = "  the client  moved to tier   B  and dropped tier A  "
    a = fake.summarize(prompt, model="fake-summary", max_tokens=200)
    b = fake.summarize(prompt, model="fake-summary", max_tokens=200)
    assert isinstance(a, LLMResult)
    assert a == b  # identical input -> identical result (stable golden tests)
    assert a.text == "the client moved to tier B and dropped tier A"  # whitespace-normalized
    assert a.input_tokens >= 1 and a.output_tokens >= 1


def test_fake_summarizer_truncates_to_budget() -> None:
    fake = FakeSummarizer(max_chars=10)
    result = fake.summarize("x" * 100, model="m", max_tokens=50)
    assert len(result.text) == 10


# --------------------------------------------------------------------------- #
# FakeEmbedder - deterministic, L2-normalized, fixed dim
# --------------------------------------------------------------------------- #
def test_fake_embedder_deterministic() -> None:
    e = FakeEmbedder(dim=256)
    v1 = e.embed(["hello world"])[0]
    v2 = e.embed(["hello world"])[0]
    assert v1 == v2  # same text -> same vector
    assert e.embed(["different"])[0] != v1
    assert len(v1) == 256 == e.dim


def test_fake_embedder_l2_normalized() -> None:
    e = FakeEmbedder(dim=128)
    for text in ("alpha", "the client focuses on local seo", "z"):
        vec = e.embed([text])[0]
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0, abs=1e-9)


def test_fake_embedder_batch_matches_singletons() -> None:
    e = FakeEmbedder(dim=64)
    batch = e.embed(["a", "b", "c"])
    assert batch == [e.embed(["a"])[0], e.embed(["b"])[0], e.embed(["c"])[0]]
    assert e.embed([]) == []


# --------------------------------------------------------------------------- #
# InMemoryVectorStore - cosine ranking, namespace isolation, upsert/delete
# --------------------------------------------------------------------------- #
def test_inmemory_query_returns_nearest_by_cosine() -> None:
    store = InMemoryVectorStore()
    ns = "client:abc"
    store.upsert(
        ns,
        [
            VectorItem(id="north", vector=[1.0, 0.0], metadata={"chunk_key": "summary"}),
            VectorItem(id="east", vector=[0.0, 1.0]),
            VectorItem(id="nne", vector=[0.9, 0.1]),
        ],
    )
    hits = store.query(ns, [1.0, 0.0], top_k=2)
    assert [h.id for h in hits] == ["north", "nne"]  # ordered by descending similarity
    assert isinstance(hits[0], Match)
    assert hits[0].score == pytest.approx(1.0)
    assert hits[0].metadata == {"chunk_key": "summary"}
    assert hits[1].score > store.query(ns, [1.0, 0.0], top_k=3)[2].score


def test_inmemory_upsert_overwrites_and_delete_removes() -> None:
    store = InMemoryVectorStore()
    ns = "user:u1"
    store.upsert(ns, [VectorItem(id="k", vector=[1.0, 0.0])])
    store.upsert(ns, [VectorItem(id="k", vector=[0.0, 1.0])])  # same id overwrites
    assert store.query(ns, [0.0, 1.0], top_k=1)[0].score == pytest.approx(1.0)
    store.delete(ns, ["k"])
    assert store.query(ns, [0.0, 1.0], top_k=1) == []
    store.delete(ns, ["missing"])  # delete of absent id / namespace is a no-op


def test_inmemory_namespaces_isolated() -> None:
    store = InMemoryVectorStore()
    store.upsert("client:a", [VectorItem(id="x", vector=[1.0, 0.0])])
    store.upsert("client:b", [VectorItem(id="y", vector=[1.0, 0.0])])
    assert [m.id for m in store.query("client:a", [1.0, 0.0], top_k=5)] == ["x"]
    assert store.query("client:c", [1.0, 0.0], top_k=5) == []  # unknown namespace -> empty


# --------------------------------------------------------------------------- #
# Factory - degrades without keys, selects real impls with keys
# --------------------------------------------------------------------------- #
def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_factory_degrades_when_keys_absent() -> None:
    assert context_providers_from_settings(_settings()) is None


def test_factory_degrades_on_partial_keys() -> None:
    # All three keys + index are required; any one missing -> degraded None.
    partial = _settings(
        anthropic_api_key="a", embeddings_api_key="b", pinecone_api_key="c"
    )  # pinecone_index still None
    assert context_providers_from_settings(partial) is None


def test_factory_selects_real_impls_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # All keys present -> factory builds the REAL bundle. We monkeypatch the three
    # real classes so NO SDK import / network happens; we only assert SELECTION.
    built: dict[str, object] = {}

    def fake_summarizer(**kwargs: object) -> object:
        built["summarizer"] = kwargs
        return "SUMMARIZER"

    def fake_voyage(**kwargs: object) -> object:
        built["embedder"] = kwargs
        return "EMBEDDER"

    def fake_pinecone(**kwargs: object) -> object:
        built["vector_store"] = kwargs
        return "VECTORSTORE"

    monkeypatch.setattr(cp, "AnthropicSummarizer", fake_summarizer)
    monkeypatch.setattr(cp, "VoyageEmbedder", fake_voyage)
    monkeypatch.setattr(cp, "PineconeVectorStore", fake_pinecone)

    settings = _settings(
        anthropic_api_key="ak",
        embeddings_api_key="ek",
        pinecone_api_key="pk",
        pinecone_index="my-index",
        pinecone_host="my-host",
        context_topk=9,
    )
    bundle = context_providers_from_settings(settings)
    assert isinstance(bundle, ContextProviders)
    assert bundle.summarizer == "SUMMARIZER"
    assert bundle.embedder == "EMBEDDER"
    assert bundle.vector_store == "VECTORSTORE"
    assert bundle.model_summary == "claude-haiku-4-5"
    assert bundle.model_heavy == "claude-sonnet-5"
    assert bundle.topk == 9
    # Secrets are passed through decrypted to the SDK clients only, never logged.
    assert built["summarizer"] == {
        "api_key": "ak",
        "model_summary": "claude-haiku-4-5",
        "model_heavy": "claude-sonnet-5",
    }
    assert built["embedder"] == {"api_key": "ek", "model": "voyage-3", "dim": 1024}
    assert built["vector_store"] == {"api_key": "pk", "index": "my-index", "host": "my-host"}


def test_factory_unknown_embeddings_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "AnthropicSummarizer", lambda **_k: "S")
    settings = _settings(
        anthropic_api_key="a",
        embeddings_api_key="b",
        pinecone_api_key="c",
        pinecone_index="idx",
        embeddings_provider="bogus",
    )
    with pytest.raises(ProviderNotConfiguredError, match="bogus"):
        context_providers_from_settings(settings)


def test_providers_for_tests_returns_fakes() -> None:
    bundle = providers_for_tests(dim=32, topk=4)
    assert isinstance(bundle.summarizer, FakeSummarizer)
    assert isinstance(bundle.embedder, FakeEmbedder)
    assert isinstance(bundle.vector_store, InMemoryVectorStore)
    assert bundle.embedder.dim == 32
    assert bundle.topk == 4


# --------------------------------------------------------------------------- #
# Real impls raise a clear error without a key (no SDK needed - key check first)
# --------------------------------------------------------------------------- #
def test_real_impls_require_a_key() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="ANTHROPIC_API_KEY"):
        AnthropicSummarizer(api_key="")
    with pytest.raises(ProviderNotConfiguredError, match="EMBEDDINGS_API_KEY"):
        VoyageEmbedder(api_key="")
    with pytest.raises(ProviderNotConfiguredError, match="PINECONE"):
        PineconeVectorStore(api_key="", index="")
    with pytest.raises(ProviderNotConfiguredError, match="PINECONE"):
        PineconeVectorStore(api_key="k", index="")  # key but no index -> still not configured
