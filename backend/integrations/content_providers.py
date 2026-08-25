"""Key-gated content-provider factory (P7A-2): assemble the seams into a bundle.

Mirrors ``integrations.context_providers``. ``content_providers_from_settings``
returns a ``ContentProviders`` bundle when the module can actually function, else
``None`` (degraded) - the later pipeline chunk holds the job and reports 'degraded'
until the keys land, exactly as the context compactor does.

TWO keys gate the module, and both degrade it to ``None``:

* ``ANTHROPIC_API_KEY`` - content fundamentally needs an LLM to draft.
* ``SERPER_API_KEY`` - content fundamentally needs REAL research to be grounded.

The research key is a gate, not an enrichment, and that is a deliberate correction.
This factory used to substitute ``FakeSerpResearcher`` when the Serper key was absent;
that fake synthesises "competitors" from a SHA-256 of the keyword, so a writer-key-only
deploy drafted articles from invented research and the pipeline PUBLISHED THEM TO
CLIENTS' LIVE SITES. Nothing downstream could tell it from real research because the
``SerpResearcher`` protocol carries no liveness signal. Degrading is the honest
behaviour: the worker holds the job at ``drafting`` and reports the reason.

IMAGES remain an enrichment. A missing ``IMAGE_GEN_API_KEY`` falls back to the fake
generator because the worker injects only a REAL hosted image and skips a fake or empty
one - a missing image is a visible absence, not fabricated evidence.

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
from app.services.content_images import content_image_store_from_settings
from integrations.content_research import FakeSerpResearcher, SerperResearcher, SerpResearcher
from integrations.errors import ProviderNotConfiguredError
from integrations.images import FakeImageGenerator, ImageGenerator, OpenAIImageGenerator
from integrations.keyword_data import (
    DataForSeoProvider,
    FakeKeywordDataProvider,
    KeywordDataProvider,
)
from integrations.llm import AnthropicSummarizer, FakeSummarizer, SystemSummarizer
from integrations.wordpress import FakeWordPressPublisher, WordPressPublisher

logger = get_logger("integrations.content_providers")


@dataclass(frozen=True)
class ContentProviders:
    """The four content seams plus the writer tiers + per-call cost estimates the
    pipeline reads.

    ``writer`` is the EXISTING ``integrations.llm`` summarizer seam (reused, not
    re-created), typed as ``SystemSummarizer`` because the content generator MUST be
    able to state its own system contract - falling through to the inner default lands
    on the context-COMPACTION prompt, which is how every draft was written until
    2026-08-24. Both ``AnthropicSummarizer`` and ``FakeSummarizer`` already satisfy it.
    ``model_writer`` / ``model_heavy`` are the Claude tiers the drafter
    routes between. ``research_cost_estimate`` / ``generate_cost_estimate`` feed the
    money-dial when a later chunk wires the cost path.
    """

    serp: SerpResearcher
    writer: SystemSummarizer
    images: ImageGenerator
    wordpress: WordPressPublisher
    # None when DataForSEO is not configured - deliberately NOT a fake.
    #
    # `FakeKeywordDataProvider` synthesises volume and difficulty from a hash. Those
    # are exactly the numbers a client makes budget decisions on, and nothing
    # downstream can tell a synthesised 880 from a bought one. v1 already shipped
    # `difficulty = log10(totalResults) * 8` looking like vendor data; substituting a
    # fake here would be the same lie with a nicer provenance story.
    #
    # So an absent provider is absent. The research stage marks every term `estimated`
    # and that label rides through to the workbook's Data source column.
    keyword_data: KeywordDataProvider | None
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
    # BOTH gates are checked BEFORE anything is constructed. Constructing the writer
    # first would raise ProviderNotConfiguredError on a deploy that is merely missing
    # the AI extra, turning an orderly degrade into a crash - and it would do that work
    # even when the research key is absent and the bundle is doomed anyway.
    anthropic_key = settings.anthropic_api_key
    if not anthropic_key or not anthropic_key.get_secret_value():
        logger.info("content_providers_degraded", reason="missing_writer_key")
        return None

    serper_key = settings.serper_api_key
    if not serper_key or not serper_key.get_secret_value():
        # NEVER substitute the synthetic researcher on the production path.
        # FakeSerpResearcher synthesises "competitors" from a SHA-256 of the keyword
        # (example.test URLs, template snippets). Drafting from it yields an article
        # whose research is invented, which the pipeline would then PUBLISH TO A
        # CLIENT'S LIVE SITE, and no downstream stage can tell it from real research.
        # Degrade exactly as a missing writer key does: the worker holds the job at
        # `drafting` via _hold_degraded and reports the reason honestly.
        logger.info("content_providers_degraded", reason="missing_serper_key")
        return None

    writer = AnthropicSummarizer(
        api_key=anthropic_key.get_secret_value(),
        model_summary=settings.anthropic_model_summary,
        model_heavy=settings.anthropic_model_heavy,
    )
    serp: SerpResearcher = SerperResearcher(api_key=serper_key.get_secret_value())

    image_key = settings.image_gen_api_key
    # gpt-image-2 (like gpt-image-1 before it) returns base64 (b64_json), not a hosted
    # url, so the real generator is handed an image HOST that decodes + serves the
    # bytes as a real https URL (None when no artifact root is configured -> a b64
    # image degrades to skipped).
    images: ImageGenerator = (
        OpenAIImageGenerator(
            api_key=image_key.get_secret_value(),
            model=settings.image_gen_model,
            # Landscape (horizontal rectangle) hero/section images — blog + page layouts
            # are wide, so a square image breaks the layout. Configurable via
            # image_gen_size (default 1536x1024, supported by both gpt-image-1 and
            # gpt-image-2).
            size=settings.image_gen_size,
            image_host=content_image_store_from_settings(settings),
        )
        if image_key
        else FakeImageGenerator()
    )

    # NOT a bundle-level gate, unlike the writer and serper keys above. A missing
    # keyword provider costs FIDELITY (estimated metrics, honestly labelled); a missing
    # writer or SERP key means there is nothing to write or nothing to write it from.
    # Degrading the whole bundle for the first would stop work that can legitimately
    # proceed.
    keyword_data: KeywordDataProvider | None = None
    dfs_login, dfs_password = settings.dataforseo_login, settings.dataforseo_password
    if dfs_login and dfs_password and dfs_password.get_secret_value():
        try:
            keyword_data = DataForSeoProvider(
                login=dfs_login, password=dfs_password.get_secret_value()
            )
        except ProviderNotConfiguredError as exc:
            # The AI/http extra is missing on this deploy. Same reasoning as above:
            # report it and carry on estimating, rather than failing the bundle.
            logger.info("keyword_data_degraded", reason=str(exc)[:120])
    else:
        logger.info("keyword_data_degraded", reason="missing_dataforseo_credentials")

    return ContentProviders(
        serp=serp,
        writer=writer,
        images=images,
        keyword_data=keyword_data,
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
        keyword_data=FakeKeywordDataProvider(),
        model_writer="fake-writer",
        model_heavy="fake-heavy",
        research_cost_estimate=research_cost,
        generate_cost_estimate=generate_cost,
    )
