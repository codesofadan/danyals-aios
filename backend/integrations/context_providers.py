"""Key-gated provider factory (P6B-3): assemble the three seams into a bundle.

``context_providers_from_settings`` returns a ``ContextProviders`` bundle of REAL,
key-gated clients when ALL required keys are present, else ``None`` (degraded) -
mirroring the audit engine's silent key-gating. On ``None`` the compaction pipeline
(P6B-7) appends raw events, marks ``status='degraded'``, and HOLDS the freshness
watermark so lag stays visible until the keys land and it catches up.

``providers_for_tests`` returns the deterministic fakes bundle, so the worker +
retrieval + freshness suites run fully live with zero external keys.

The providers are reachable ONLY through this bundle; P6B-4 wraps the summarizer
and embedder in cost-gated wrappers before anything calls them.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.logging_setup import get_logger
from integrations.embeddings import Embedder, FakeEmbedder, VoyageEmbedder
from integrations.errors import ProviderNotConfiguredError
from integrations.llm import AnthropicSummarizer, FakeSummarizer, Summarizer
from integrations.vectorstore import InMemoryVectorStore, PineconeVectorStore, VectorStore

logger = get_logger("integrations.context_providers")


@dataclass(frozen=True)
class ContextProviders:
    """The three seams plus the tiering/retrieval knobs the pipeline reads.

    ``model_summary`` / ``model_heavy`` are the Claude tiers the compactor routes
    between by fold size; ``topk`` is the retrieval breadth.
    """

    summarizer: Summarizer
    embedder: Embedder
    vector_store: VectorStore
    model_summary: str
    model_heavy: str
    topk: int


def _build_embedder(settings: Settings, api_key: str) -> Embedder:
    """Select the real embeddings impl for the configured provider (Voyage today)."""
    provider = settings.embeddings_provider.lower()
    if provider == "voyage":
        return VoyageEmbedder(
            api_key=api_key, model=settings.embeddings_model, dim=settings.embeddings_dim
        )
    raise ProviderNotConfiguredError(
        f"unknown embeddings provider '{provider}': set EMBEDDINGS_PROVIDER=voyage"
    )


def context_providers_from_settings(settings: Settings) -> ContextProviders | None:
    """Real bundle when every key is present; ``None`` (degraded) otherwise.

    Constructing the real bundle lazily imports the optional AI SDKs; a missing SDK
    raises ``ProviderNotConfiguredError`` naming the fix. No secret is ever logged -
    the degraded path logs only the reason.
    """
    anthropic_key = settings.anthropic_api_key
    embeddings_key = settings.embeddings_api_key
    pinecone_key = settings.pinecone_api_key

    if not (anthropic_key and embeddings_key and pinecone_key and settings.pinecone_index):
        logger.info("context_providers_degraded", reason="missing_keys")
        return None

    summarizer = AnthropicSummarizer(
        api_key=anthropic_key.get_secret_value(),
        model_summary=settings.anthropic_model_summary,
        model_heavy=settings.anthropic_model_heavy,
    )
    embedder = _build_embedder(settings, embeddings_key.get_secret_value())
    vector_store = PineconeVectorStore(
        api_key=pinecone_key.get_secret_value(),
        index=settings.pinecone_index,
        host=settings.pinecone_host,
    )
    return ContextProviders(
        summarizer=summarizer,
        embedder=embedder,
        vector_store=vector_store,
        model_summary=settings.anthropic_model_summary,
        model_heavy=settings.anthropic_model_heavy,
        topk=settings.context_topk,
    )


def providers_for_tests(*, dim: int = 1024, topk: int = 6) -> ContextProviders:
    """A deterministic, network-free fakes bundle for the worker + freshness suites."""
    return ContextProviders(
        summarizer=FakeSummarizer(),
        embedder=FakeEmbedder(dim=dim),
        vector_store=InMemoryVectorStore(),
        model_summary="fake-summary",
        model_heavy="fake-heavy",
        topk=topk,
    )
