"""P7A-4 unit tests: the ranking-grade content GENERATOR.

Fully deterministic on a ``FakeWriter`` (a prompt-hash-derived ``Summarizer``) -
NO network. Proves the Content Doctrine's enforceable rules:

* framework routing (Auto -> per-page-type default; an explicit framework wins);
* the extractable structure is enforced (exactly one H1, the 40-55-word answer
  block, a real H2/H3 hierarchy);
* every draft carries the mandatory differentiation angle, derived from the
  top-10 teardown's differentiator entities;
* the white-hat local-page anatomy blocks are present for ``page_type='local'``
  (per-city sections + uniqueness, NAP, GBP note, localized FAQ);
* the grounding trace maps claims back to the source pack;
* a missing required fact yields a ``[NEEDS:]`` placeholder (never a hallucination);
* the word / section budgets are honored even against a runaway provider.
"""

from __future__ import annotations

import hashlib

import pytest

from app.services.content_generator import (
    ANSWER_MAX_WORDS,
    DIFFERENTIATION_KINDS,
    MAX_IMAGES,
    NAP,
    PRIMARY_DENSITY_HARD_CEILING,
    WORD_COUNT_CEILING,
    GenerationContext,
    LocalProfile,
    SourcePack,
    _bound_words,
    generate,
    resolve_framework,
)
from app.services.content_research import (
    FormatDecision,
    ResearchBrief,
    Teardown,
    TermSet,
    TopicalCluster,
    WinnabilityReport,
)
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# A deterministic writer (satisfies the Summarizer Protocol; NO network).
# --------------------------------------------------------------------------- #
class FakeWriter:
    """Prompt-hash-derived writer: identical prompt => identical output, DIFFERENT
    prompts => different tokens (so per-city sections legitimately differ). The
    word count is controllable via ``words`` so the answer-block + budget tests are
    exact."""

    def __init__(self, *, words: int = 90) -> None:
        self._words = words
        self.calls = 0

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        base = [digest[i : i + 6] for i in range(0, len(digest), 6)]
        body = " ".join(f"{base[i % len(base)]}{i}" for i in range(self._words))
        return LLMResult(text=body, input_tokens=max(1, len(prompt) // 4), output_tokens=self._words)


# --------------------------------------------------------------------------- #
# Brief + source-pack builders.
# --------------------------------------------------------------------------- #
def _brief(
    *,
    keyword: str = "roof repair",
    geo: str | None = None,
    intent: str = "commercial",
    supporting: list[str] | None = None,
    fanout: list[str] | None = None,
    table_stakes: list[str] | None = None,
    differentiators: list[str] | None = None,
    word_count_target: int = 1200,
    low_confidence: bool = False,
) -> ResearchBrief:
    primary = keyword
    terms = TermSet(
        primary=primary,
        secondary=supporting or ["roof repair cost", "emergency roof repair"],
        semantic_entities=["Shingles", "Flashing"],
        questions=fanout or [f"What is {primary}?", f"How much does {primary} cost?"],
    )
    cluster = TopicalCluster(
        pillar=primary,
        primary=primary,
        supporting=supporting or ["roof repair cost", "emergency roof repair", "roof leak"],
    )
    teardown = Teardown(
        pages=[],
        table_stakes_entities=table_stakes if table_stakes is not None else ["Shingles", "Flashing"],
        differentiator_entities=differentiators if differentiators is not None else ["Drone Survey", "Warranty"],
        heading_blueprint=["Cost", "Process"],
        word_count_target=word_count_target,
        schema_types=["Service"],
        media_target=3,
        freshness_expected=True,
        fetched=8,
        refused=[],
    )
    return ResearchBrief(
        keyword=keyword,
        geo=geo,
        serp_date="2026-07-16",
        intent=intent,  # type: ignore[arg-type]
        intent_confidence=0.8,
        terms=terms,
        cluster=cluster,
        content_format=FormatDecision(recommended="blog", confidence=0.7, signals={}),
        fanout=fanout or [f"What is {primary}?", f"How much does {primary} cost?", f"Is {primary} worth it?"],
        winnability=WinnabilityReport(client_da=40.0, neutral_da_assumed=False, targets=[]),
        teardown=teardown,
        registry=[],
        low_confidence=low_confidence,
        degraded=False,
        notes=[],
    )


def _source_pack(
    *,
    proof: list[str] | None = None,
    unique_data: list[str] | None = None,
    locations: list[LocalProfile] | None = None,
    nap: NAP | None = None,
    internal_urls: dict[str, str] | None = None,
) -> SourcePack:
    return SourcePack(
        client_name="Acme Roofing",
        facts={"years_experience": "18", "warranty": "25-year workmanship warranty"},
        services=["Roof repair", "Roof replacement", "Gutter installation"],
        proof_points=proof if proof is not None else ["Rebuilt 40 storm-damaged roofs in 2025"],
        unique_data=unique_data if unique_data is not None else [],
        testimonials=["'They saved our home' - J. Doe"],
        internal_urls=internal_urls or {"roof replacement": "/services/roof-replacement"},
        nap=nap,
        locations=locations or [],
    )


def _context() -> GenerationContext:
    return GenerationContext(
        summary="Acme Roofing is a family-owned contractor serving Central Texas since 2008.",
        facts={"tier": "fully", "last_audit_score": "82"},
        stale=False,
    )


def _h1_count(draft: str) -> int:
    return sum(1 for line in draft.splitlines() if line.startswith("# "))


# --------------------------------------------------------------------------- #
# 1. Framework routing
# --------------------------------------------------------------------------- #
def test_resolve_framework_auto_by_page_type() -> None:
    assert resolve_framework("service", "Auto") == "AIDA"
    assert resolve_framework("local", "Auto") == "BAB"
    assert resolve_framework("blog", "Auto") == "PAS"


def test_resolve_framework_explicit_overrides() -> None:
    assert resolve_framework("service", "PAS") == "PAS"
    assert resolve_framework("blog", "FAB") == "FAB"


def test_generate_routes_auto_service_to_aida_moves() -> None:
    result = generate(
        _brief(), _source_pack(), _context(), page_type="service", framework="Auto", writer=FakeWriter()
    )
    assert result.framework == "AIDA"
    assert result.section_roles == ["attention", "interest", "desire", "action"]


def test_generate_local_auto_routes_to_bab() -> None:
    result = generate(
        _brief(geo="Austin"),
        _source_pack(locations=[LocalProfile("Austin", proof=["Fixed the Zilker clubhouse roof"])]),
        None,
        page_type="local",
        framework="Auto",
        writer=FakeWriter(),
    )
    assert result.framework == "BAB"
    assert result.section_roles == ["before", "after", "bridge"]


def test_generate_explicit_framework_wins() -> None:
    result = generate(
        _brief(), _source_pack(), None, page_type="service", framework="PASTOR", writer=FakeWriter()
    )
    assert result.framework == "PASTOR"
    assert result.section_roles[0] == "problem"
    assert "testimonial" in result.section_roles


# --------------------------------------------------------------------------- #
# 2. Extractable structure (one H1, answer block, headings)
# --------------------------------------------------------------------------- #
def test_exactly_one_h1() -> None:
    result = generate(_brief(), _source_pack(), _context(), page_type="blog", writer=FakeWriter())
    assert _h1_count(result.draft_md) == 1
    assert sum(1 for h in result.headings if h.level == 1) == 1
    assert result.draft_md.startswith("# ")


def test_multiple_h2_and_h3_headings() -> None:
    result = generate(_brief(), _source_pack(), _context(), page_type="blog", writer=FakeWriter())
    h2 = [h for h in result.headings if h.level == 2]
    h3 = [h for h in result.headings if h.level == 3]
    assert len(h2) >= 4  # key heading + moves + FAQ + links + conclusion
    assert len(h3) >= 1  # FAQ questions render as H3


def test_answer_block_is_40_to_55_words_and_carries_primary() -> None:
    result = generate(
        _brief(keyword="metal roof cost"), _source_pack(), _context(), page_type="blog", writer=FakeWriter()
    )
    words = result.answer_block.split()
    assert 40 <= len(words) <= ANSWER_MAX_WORDS
    assert "metal roof cost" in result.answer_block.lower()
    # The answer block appears verbatim in the draft, under the key heading.
    assert result.answer_block in result.draft_md


# --------------------------------------------------------------------------- #
# 3. The mandatory differentiation angle (derived from the teardown)
# --------------------------------------------------------------------------- #
def test_differentiation_angle_present_and_derived_from_teardown() -> None:
    diffs = ["Drone Survey", "Lifetime Warranty", "Infrared Scan"]
    result = generate(
        _brief(differentiators=diffs),
        _source_pack(unique_data=["Our 2025 study of 500 roofs found 30% needed only spot repair"]),
        _context(),
        page_type="service",
        writer=FakeWriter(),
    )
    angle = result.differentiation_angle
    assert angle.grounded is True
    assert angle.kind in DIFFERENTIATION_KINDS
    assert angle.statement.strip()
    assert set(angle.derived_from) <= set(diffs)
    assert angle.derived_from  # non-empty when the teardown has differentiators


def test_unique_data_takes_priority_for_angle_kind() -> None:
    result = generate(
        _brief(),
        _source_pack(unique_data=["Proprietary benchmark: 12% faster installs"], proof=["A real project"]),
        None,
        page_type="service",
        writer=FakeWriter(),
    )
    assert result.differentiation_angle.kind == "unique_data"


# --------------------------------------------------------------------------- #
# 4. White-hat local-page anatomy + per-city uniqueness
# --------------------------------------------------------------------------- #
def test_local_anatomy_blocks_present_and_unique() -> None:
    locations = [
        LocalProfile("Austin", proof=["Reroofed the historic Zilker lodge after the 2025 hail storm"]),
        LocalProfile("Dallas", proof=["Installed standing-seam metal on the Deep Ellum art lofts"]),
    ]
    nap = NAP(name="Acme Roofing", address="100 Main St, Austin TX", phone="+1-512-555-0100")
    result = generate(
        _brief(keyword="roof repair", geo="Austin"),
        _source_pack(locations=locations, nap=nap),
        None,
        page_type="local",
        writer=FakeWriter(),
    )
    draft = result.draft_md
    assert "## Serving Austin" in draft
    assert "## Serving Dallas" in draft
    assert "## Visit us" in draft
    assert "100 Main St, Austin TX" in draft
    assert "Google Business Profile" in draft
    assert "Frequently asked questions" in draft
    # Per-city uniqueness computed + above the doctrine floor for distinct proof.
    assert set(result.local_uniqueness) == {"Austin", "Dallas"}
    assert all(ratio >= 0.6 for ratio in result.local_uniqueness.values())


def test_local_missing_nap_and_proof_yields_needs() -> None:
    result = generate(
        _brief(geo="Austin"),
        _source_pack(locations=[LocalProfile("Austin", proof=[])], nap=None),
        None,
        page_type="local",
        writer=FakeWriter(),
    )
    assert "[NEEDS:" in result.draft_md
    joined = " ".join(result.needs).lower()
    assert "nap" in joined
    assert "local proof for austin" in joined


# --------------------------------------------------------------------------- #
# 5. Grounding trace maps claims back to the source pack
# --------------------------------------------------------------------------- #
def test_grounding_trace_maps_claims_to_source_pack() -> None:
    result = generate(_brief(), _source_pack(), _context(), page_type="service", writer=FakeWriter())
    sources = {claim.source for claim in result.grounding}
    assert any(source.startswith("source_pack") for source in sources)
    # A concrete source-pack fact is traced (not invented) - its value is recorded.
    claims = {claim.claim for claim in result.grounding}
    assert "Roof repair" in claims or any("Roof repair" in c for c in claims)
    # Fresh context also grounds the draft.
    assert any(source.startswith("context") for source in sources)


# --------------------------------------------------------------------------- #
# 6. No hallucination: a missing required fact becomes a [NEEDS:] placeholder
# --------------------------------------------------------------------------- #
def test_missing_differentiation_fact_yields_needs_no_hallucination() -> None:
    # No unique data, no proof points, and a teardown with NO differentiators =>
    # the angle cannot be grounded, so a [NEEDS:] is emitted rather than invented.
    result = generate(
        _brief(differentiators=[]),
        _source_pack(proof=[], unique_data=[]),
        None,
        page_type="blog",
        writer=FakeWriter(),
    )
    assert result.differentiation_angle.grounded is False
    assert "[NEEDS:" in result.draft_md
    assert result.needs  # the gap is recorded, not hallucinated


# --------------------------------------------------------------------------- #
# 7. Word / section budgets honored (even against a runaway provider)
# --------------------------------------------------------------------------- #
def test_bound_words_truncates() -> None:
    assert len(_bound_words("word " * 1000, 50).split()) == 50
    assert _bound_words("short text", 50) == "short text"


def test_word_budget_honored_against_runaway_writer() -> None:
    result = generate(
        _brief(word_count_target=1200),
        _source_pack(),
        _context(),
        page_type="service",
        writer=FakeWriter(words=100_000),  # a provider that ignores the budget
    )
    assert result.word_count <= WORD_COUNT_CEILING
    assert len(result.answer_block.split()) <= ANSWER_MAX_WORDS
    assert result.primary_density <= PRIMARY_DENSITY_HARD_CEILING


# --------------------------------------------------------------------------- #
# 8. Internal links, images, determinism
# --------------------------------------------------------------------------- #
def test_internal_links_from_registry_and_cluster() -> None:
    result = generate(
        _brief(supporting=["roof leak", "shingle types"]),
        _source_pack(internal_urls={"roof replacement": "/services/roof-replacement"}),
        None,
        page_type="service",
        writer=FakeWriter(),
    )
    keywords = {link.keyword for link in result.internal_links}
    assert "roof replacement" in keywords  # registry URL
    assert "roof leak" in keywords  # cluster spoke -> slug
    urls = {link.url for link in result.internal_links}
    assert "/services/roof-replacement" in urls
    assert any(url.startswith("/roof-leak") for url in urls)


def test_images_plan_hero_first_and_capped() -> None:
    result = generate(_brief(), _source_pack(), None, page_type="service", writer=FakeWriter())
    assert result.images_plan[0].slot == "hero"
    assert len(result.images_plan) <= MAX_IMAGES
    assert all(img.alt for img in result.images_plan)  # every image has alt text


def test_generation_is_deterministic() -> None:
    first = generate(
        _brief(), _source_pack(), _context(), page_type="service", framework="Auto", writer=FakeWriter()
    )
    second = generate(
        _brief(), _source_pack(), _context(), page_type="service", framework="Auto", writer=FakeWriter()
    )
    assert first.draft_md == second.draft_md
    assert first.title == second.title
    assert first.meta_description == second.meta_description
