"""Key-gated content-provider factory (P7A-2): assemble the seams into a bundle.

Mirrors ``integrations.context_providers``. ``content_providers_from_settings``
returns a ``ContentProviders`` bundle when the module can actually function, else
``None`` (degraded) - the later pipeline chunk holds the job and reports 'degraded'
until the keys land, exactly as the context compactor does.

The WRITER (Anthropic, reused from ``integrations.llm``) is the gate: content
fundamentally needs an LLM to draft, so a missing ``ANTHROPIC_API_KEY`` degrades
the whole module to ``None``. With the writer present the factory assembles the
ENRICHMENT seams per available key - a real ``SerperResearcher`` /
``OpenAIImageGenerator`` when its key is set, else the deterministic fake - so the
module runs (draft-only) the moment the writer key lands and lights up research +
images as those keys arrive.

WORDPRESS IS ALWAYS THE FAKE HERE. A WordPress application password is per-site and
lives in the vault, NOT in settings; the SERVICE layer (a later chunk) decrypts it
and constructs a real ``WordPressClient`` per publish. The factory has no per-site
credential, so it supplies the safe offline publisher as the bundle default.

``content_providers_for_tests`` returns an all-fakes bundle so the pipeline +
publish suites run fully live with zero external keys.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.logging_setup import get_logger
from integrations.content_research import FakeSerpResearcher, SerperResearcher, SerpResearcher
from integrations.images import FakeImageGenerator, ImageGenerator, OpenAIImageGenerator
from integrations.llm import AnthropicSummarizer, FakeSummarizer, Summarizer
from integrations.wordpress import FakeWordPressPublisher, WordPressPublisher

logger = get_logger("integrations.content_providers")


@dataclass(frozen=True)
class ContentProviders:
    """The four content seams plus the writer tiers + per-call cost estimates the
    pipeline reads.

    ``writer`` is the EXISTING ``integrations.llm`` summarizer seam (reused, not
    re-created); ``model_writer`` / ``model_heavy`` are the Claude tiers the drafter
    routes between. ``research_cost_estimate`` / ``generate_cost_estimate`` feed the
    money-dial when a later chunk wires the cost path.
    """

    serp: SerpResearcher
    writer: Summarizer
    images: ImageGenerator
    wordpress: WordPressPublisher
    model_writer: str
    model_heavy: str
    research_cost_estimate: float
    generate_cost_estimate: float


def content_providers_from_settings(settings: Settings) -> ContentProviders | None:
    """Real-ish bundle when the writer key is present; ``None`` (degraded) otherwise.

    Constructing the real seams lazily imports ``httpx``; a genuinely missing base
    dep raises ``ProviderNotConfiguredError`` naming the fix. No secret is ever
    logged - the degraded path logs only the reason.
    """
    anthropic_key = settings.anthropic_api_key
    if not anthropic_key:
        logger.info("content_providers_degraded", reason="missing_writer_key")
        return None

    writer = AnthropicSummarizer(
        api_key=anthropic_key.get_secret_value(),
        model_summary=settings.anthropic_model_summary,
        model_heavy=settings.anthropic_model_heavy,
    )

    serper_key = settings.serper_api_key
    serp: SerpResearcher = (
        SerperResearcher(api_key=serper_key.get_secret_value())
        if serper_key
        else FakeSerpResearcher()
    )

    image_key = settings.image_gen_api_key
    images: ImageGenerator = (
        OpenAIImageGenerator(
            api_key=image_key.get_secret_value(), model=settings.image_gen_model
        )
        if image_key
        else FakeImageGenerator()
    )

    return ContentProviders(
        serp=serp,
        writer=writer,
        images=images,
        # Per-site WP credentials live in the vault, not settings; the service layer
        # builds the real client per publish. The factory default is the fake.
        wordpress=FakeWordPressPublisher(),
        model_writer=settings.anthropic_model_summary,
        model_heavy=settings.anthropic_model_heavy,
        research_cost_estimate=settings.content_research_cost_estimate,
        generate_cost_estimate=settings.content_generate_cost_estimate,
    )


def content_providers_for_tests(
    *, research_cost: float = 0.01, generate_cost: float = 0.15
) -> ContentProviders:
    """A deterministic, network-free all-fakes bundle for the pipeline suites."""
    return ContentProviders(
        serp=FakeSerpResearcher(),
        writer=FakeSummarizer(),
        images=FakeImageGenerator(),
        wordpress=FakeWordPressPublisher(),
        model_writer="fake-writer",
        model_heavy="fake-heavy",
        research_cost_estimate=research_cost,
        generate_cost_estimate=generate_cost,
    )
