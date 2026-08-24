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
import json
from collections.abc import Sequence

import pytest

from app.services.content_generator import (
    _CAMERA_SUFFIX,
    _FALLBACK_SCENES,
    ANSWER_MAX_WORDS,
    DIFFERENTIATION_KINDS,
    LOCAL_UNIQUE_MIN,
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

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.systems = [*getattr(self, "systems", []), system]
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
    assert all(ratio >= LOCAL_UNIQUE_MIN for ratio in result.local_uniqueness.values())


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


# --------------------------------------------------------------------------- #
# 9. Image prompts are CONCRETE PHOTOGRAPHIC SCENES (never the abstract topic).
#    gpt-image-1 renders an abstract topic as title text -> an infographic. So the writer
#    authors one literal camera-ready scene per image and the final prompt is that scene +
#    the fixed camera/realism suffix. The topic never enters the prompt; the suffix forces
#    NO human face (the #1 AI tell) + hyper-realistic photographic texture (kills the
#    airbrushed look). Only the ALT text stays the human heading.
# --------------------------------------------------------------------------- #
# Concrete, literal, TOPIC-FREE, FACE-FREE scenes a fake writer returns as the batched brief.
_CONCRETE_SCENES = [
    "Close-up of a carpenter's hands sanding an oak plank in a sawdust-lit workshop",
    "A barista's hands steaming milk behind a cafe counter in morning light",
    "Gloved hands, shot from behind, planting seedlings in a sunny backyard bed",
    "An over-the-shoulder view of a wrench turning a bolt beside a lifted car",
    "A baker's hands sliding a tray of loaves into a glowing stone oven",
    "A cyclist seen from behind pausing on a stone bridge over a river at dusk",
]


class _SceneWriter:
    """A ``Summarizer`` fake: returns a strict-JSON scene array for the ONE batched photo
    brief (detected by the 'photo director' marker) and plain prose for every body
    section. Counts the brief calls so a test can prove the call is batched (exactly 1)."""

    def __init__(self, scenes: list[str]) -> None:
        self._scenes = scenes
        self.brief_calls = 0

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.systems = [*getattr(self, "systems", []), system]
        if "photo director" in prompt:  # the photo-brief instruction
            self.brief_calls += 1
            return LLMResult(text=json.dumps(self._scenes), input_tokens=10, output_tokens=10)
        return LLMResult(text="Plain grounded prose for this section.", input_tokens=6, output_tokens=6)


def test_image_prompts_are_concrete_scenes_plus_suffix_not_the_topic() -> None:
    writer = _SceneWriter(_CONCRETE_SCENES)
    result = generate(
        _brief(keyword="roof repair"), _source_pack(), _context(),
        page_type="service", framework="Auto", writer=writer,
    )
    # ONE batched writer call authored ALL image scenes (cheaper than one-per-image).
    assert writer.brief_calls == 1
    assert result.images_plan
    for i, img in enumerate(result.images_plan):
        # The prompt is EXACTLY the concrete scene + the fixed camera/realism suffix.
        assert img.prompt == f"{_CONCRETE_SCENES[i]} {_CAMERA_SUFFIX}"
        assert img.prompt.endswith(_CAMERA_SUFFIX)
        # The ABSTRACT topic never enters the prompt.
        assert "roof repair" not in img.prompt.lower()
        prompt_low = img.prompt.lower()
        # No-face framing is enforced (visible AI faces are the #1 tell).
        assert "no face" in prompt_low
        # Hyper-realistic, unretouched texture is demanded (kills the airbrushed AI look).
        assert "unretouched" in prompt_low
        assert "pores" in prompt_low and "grain" in prompt_low


def test_image_prompts_fall_back_to_concrete_templates_when_writer_raises() -> None:
    class _RaisingBriefWriter:
        """Body prose succeeds; the photo-brief call fails (a provider error)."""

        def summarize(
            self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
        ) -> LLMResult:
            self.systems = [*getattr(self, "systems", []), system]
            if "photo director" in prompt:
                raise RuntimeError("image-brief provider down")
            return LLMResult(text="Plain prose.", input_tokens=4, output_tokens=4)

    result = generate(
        _brief(keyword="roof repair"), _source_pack(), None,
        page_type="service", framework="Auto", writer=_RaisingBriefWriter(),
    )
    assert result.images_plan  # the job still produced an image plan (no crash)
    for img in result.images_plan:
        assert img.prompt.endswith(_CAMERA_SUFFIX)
        scene = img.prompt[: -len(_CAMERA_SUFFIX)].strip()
        assert scene in _FALLBACK_SCENES  # a concrete generic template, not the topic
        assert "roof repair" not in img.prompt.lower()
        assert "no face" in img.prompt.lower()  # the no-face suffix still applies


@pytest.mark.parametrize(
    "brief_text",
    ["", "   ", "not json at all", "[]", '["", "   "]', '{"scene": "x"}', "[1, 2, 3]"],
)
def test_image_prompts_fall_back_on_empty_or_junk_writer_output(brief_text: str) -> None:
    class _JunkBriefWriter:
        def summarize(
            self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
        ) -> LLMResult:
            self.systems = [*getattr(self, "systems", []), system]
            if "photo director" in prompt:
                return LLMResult(text=brief_text, input_tokens=1, output_tokens=1)
            return LLMResult(text="Plain prose.", input_tokens=4, output_tokens=4)

    result = generate(
        _brief(keyword="roof repair"), _source_pack(), None,
        page_type="service", framework="Auto", writer=_JunkBriefWriter(),
    )
    assert result.images_plan
    for img in result.images_plan:
        scene = img.prompt[: -len(_CAMERA_SUFFIX)].strip()
        assert scene in _FALLBACK_SCENES  # degraded to a concrete generic scene
        assert "roof repair" not in img.prompt.lower()


def test_image_alt_text_stays_the_section_heading() -> None:
    writer = _SceneWriter(_CONCRETE_SCENES)
    result = generate(
        _brief(keyword="roof repair"), _source_pack(), _context(),
        page_type="service", framework="Auto", writer=writer,
    )
    imgs = result.images_plan
    # Hero comes first; its alt is the primary + client (unchanged behaviour).
    assert imgs[0].slot == "hero"
    assert imgs[0].alt == "roof repair - Acme Roofing"
    # Section images keep the human-readable AIDA heading as alt (accessibility + SEO),
    # even though the PROMPT is a topic-free concrete scene.
    expected_alt = {
        "section:attention": "Why roof repair matters",
        "section:interest": "How roof repair works",
        "section:desire": "The benefits of choosing Acme Roofing",
        "section:action": "Get started with roof repair",
    }
    section_imgs = [img for img in imgs if img.slot.startswith("section:")]
    assert section_imgs  # AIDA has four moves -> four section images
    for img in section_imgs:
        assert img.alt == expected_alt[img.slot]
        assert img.alt != img.prompt  # the alt is the heading, not the scene prompt


def test_camera_suffix_enforces_no_faces_and_realistic_texture() -> None:
    suffix = _CAMERA_SUFFIX.lower()
    # No-face framing (visible AI faces are the #1 "this is AI" tell).
    for phrase in ("no face", "no visible faces", "no portraits", "no eye contact"):
        assert phrase in suffix
    # Hyper-realistic, unretouched photographic texture (kills the airbrushed / CGI look).
    for phrase in (
        "unretouched", "pores", "grain", "not airbrushed", "not a 3d render", "no plastic skin",
    ):
        assert phrase in suffix
    # The infographic / text negatives are kept as cheap insurance on top of the scene lever.
    for phrase in ("not an infographic", "no text", "no logos"):
        assert phrase in suffix
    # The suffix is topic-free by construction (no article subject leaks in).
    assert "roof repair" not in suffix


def test_fallback_scenes_are_generic_topic_free_and_sufficient() -> None:
    assert len(_FALLBACK_SCENES) >= MAX_IMAGES  # enough distinct templates to fill every slot
    for scene in _FALLBACK_SCENES:
        assert scene.strip()
        assert "roof repair" not in scene.lower()  # a generic scene, never the abstract topic
