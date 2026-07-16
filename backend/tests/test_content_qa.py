"""P7A-6 unit tests: the 14-dimension Content QA scorecard (the publish gate).

Fully deterministic - NO network. Builds :class:`GeneratedContent` directly (the
scorer is a pure consumer of the generator's output) so each dimension is exercised
in isolation, and proves the doctrine's enforceable publish rules:

* a well-formed, grounded draft PASSES (no dim < 70, weighted total >= 85);
* a keyword-stuffed draft scores low on keyword handling;
* a draft missing the differentiation angle FAILS the info-gain HARD gate;
* a concrete claim not in the source pack FAILS fact-grounding (a hard gate);
* a blog draft scored against a product SERP fails SERP-format fit;
* the weighted total + pass/block are computed exactly;
* the gate degrades WITHOUT a judge and still scores all 14 dimensions;
* an injected judge is used, but a doctrine floor still dominates it.
"""

from __future__ import annotations

import pytest

from app.services.content_generator import (
    NAP,
    DifferentiationAngle,
    GeneratedContent,
    GroundedClaim,
    Heading,
    ImagePlanItem,
    InternalLink,
    LocalProfile,
    SourcePack,
)
from app.services.content_qa import (
    DIMENSION_WEIGHTS,
    MIN_DIMENSION_SCORE,
    QA_DIMENSIONS,
    WEIGHTED_TOTAL_THRESHOLD,
    JudgeVerdict,
    QaScore,
    score,
)
from app.services.content_research import (
    FormatDecision,
    ResearchBrief,
    Teardown,
    TermSet,
    TopicalCluster,
    WinnabilityReport,
)
from app.services.content_schema import ValidationResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# A deterministic judge (satisfies the Judge Protocol; NO network).
# --------------------------------------------------------------------------- #
class FakeJudge:
    """Returns a fixed per-dimension score (default otherwise) and records every
    dimension it was asked to assess."""

    def __init__(self, scores: dict[str, int] | None = None, *, default: int = 88) -> None:
        self._scores = scores or {}
        self._default = default
        self.calls: list[str] = []

    def assess(self, dimension: str, *, draft: str, criteria: str, context: str = "") -> JudgeVerdict:
        self.calls.append(dimension)
        return JudgeVerdict(score=self._scores.get(dimension, self._default), rationale="fake")


# --------------------------------------------------------------------------- #
# Builders (a passing service draft by default; override to break one dimension).
# --------------------------------------------------------------------------- #
_ANSWER = (
    "Roof repair fixes leaks, cracked shingles, and worn flashing so your home stays dry and "
    "safe. A trained crew checks the roof, finds the cause, and repairs it fast. Most jobs are "
    "done in a day and come with a clear price."
)

_GOOD_DRAFT = f"""# Roof repair | Acme Roofing

Acme Roofing has helped homeowners keep their roofs sound for years. We fix leaks and replace \
worn shingles with care. Our team explains every step in plain words. You always know the plan \
and the price before we start.

## What is roof repair?

{_ANSWER}

## What a complete answer to roof repair covers

- Shingles
- Flashing

## Why choose Acme Roofing

We rebuilt 40 storm-damaged roofs in 2025. Our crew brings 18 years of hands-on work to your \
home. Clients say we save their homes when storms hit.

- Rebuilt 40 storm-damaged roofs in 2025

## What makes this different

Our 2025 study of 500 roofs found 30% needed only spot repair, not a full replacement.

## Frequently asked questions

### How much does roof repair cost?

Most repairs are small and quick. We share a clear price before any work begins.

## Related resources

- [roof replacement](/services/roof-replacement)
- [roof leak](/roof-leak)
- [shingle types](/shingle-types)

## Ready to move forward with roof repair?

Call us today and we will start with a free look at your roof.
"""

_GOOD_HEADINGS = [
    Heading(1, "Roof repair | Acme Roofing"),
    Heading(2, "What is roof repair?"),
    Heading(2, "What a complete answer to roof repair covers"),
    Heading(2, "Why choose Acme Roofing"),
    Heading(2, "What makes this different"),
    Heading(2, "Frequently asked questions"),
    Heading(3, "How much does roof repair cost?"),
    Heading(2, "Related resources"),
    Heading(2, "Ready to move forward with roof repair?"),
]

_GOOD_ANGLE = DifferentiationAngle(
    kind="unique_data",
    statement="Original data from Acme Roofing: Our 2025 study of 500 roofs found 30% needed only spot repair",
    grounded=True,
    derived_from=["Drone Survey", "Warranty"],
)

_GOOD_LINKS = [
    InternalLink(anchor="roof replacement", url="/services/roof-replacement", keyword="roof replacement"),
    InternalLink(anchor="roof leak", url="/roof-leak", keyword="roof leak"),
    InternalLink(anchor="shingle types", url="/shingle-types", keyword="shingle types"),
]

_GOOD_GROUNDING = [
    GroundedClaim(claim="Roof repair", source="source_pack.services[0]"),
    GroundedClaim(claim="Rebuilt 40 storm-damaged roofs in 2025", source="source_pack.proof_points[0]"),
    GroundedClaim(claim="18", source="source_pack.facts.years_experience"),
    GroundedClaim(
        claim="Our 2025 study of 500 roofs found 30% needed only spot repair",
        source="source_pack.unique_data[0]",
    ),
]


def _content(
    *,
    draft_md: str = _GOOD_DRAFT,
    headings: list[Heading] | None = None,
    page_type: str = "service",
    answer_block: str = _ANSWER,
    angle: DifferentiationAngle | None = None,
    internal_links: list[InternalLink] | None = None,
    grounding: list[GroundedClaim] | None = None,
    needs: list[str] | None = None,
    primary_density: float = 0.01,
    local_uniqueness: dict[str, float] | None = None,
    images_plan: list[ImagePlanItem] | None = None,
) -> GeneratedContent:
    return GeneratedContent(
        title="Roof repair | Acme Roofing",
        meta_description="Roof repair: original data from Acme Roofing. Get started with Acme Roofing today.",
        draft_md=draft_md,
        page_type=page_type,
        framework="AIDA",
        target="WordPress",
        headings=headings if headings is not None else list(_GOOD_HEADINGS),
        answer_block=answer_block,
        section_roles=["attention", "interest", "desire", "action"],
        differentiation_angle=angle if angle is not None else _GOOD_ANGLE,
        internal_links=internal_links if internal_links is not None else list(_GOOD_LINKS),
        images_plan=images_plan
        if images_plan is not None
        else [ImagePlanItem(slot="hero", prompt="Hero", alt="Roof repair - Acme Roofing")],
        grounding=grounding if grounding is not None else list(_GOOD_GROUNDING),
        needs=needs if needs is not None else [],
        word_count=650,
        primary_density=primary_density,
        entities_covered=["Shingles", "Flashing"],
        entities_missing=[],
        local_uniqueness=local_uniqueness if local_uniqueness is not None else {},
        notes=[],
    )


def _brief(
    *,
    keyword: str = "roof repair",
    intent: str = "commercial",
    recommended_format: str = "blog",
    format_confidence: float = 0.7,
    table_stakes: list[str] | None = None,
    differentiators: list[str] | None = None,
) -> ResearchBrief:
    terms = TermSet(
        primary=keyword,
        secondary=["roof repair cost", "emergency roof repair"],
        semantic_entities=["Shingles", "Flashing"],
        questions=[f"What is {keyword}?", f"How much does {keyword} cost?"],
    )
    cluster = TopicalCluster(
        pillar=keyword,
        primary=keyword,
        supporting=["roof repair cost", "emergency roof repair", "roof leak"],
    )
    teardown = Teardown(
        pages=[],
        table_stakes_entities=table_stakes if table_stakes is not None else ["Shingles", "Flashing"],
        differentiator_entities=differentiators if differentiators is not None else ["Drone Survey", "Warranty"],
        heading_blueprint=["Cost", "Process"],
        word_count_target=1200,
        schema_types=["Service"],
        media_target=3,
        freshness_expected=True,
        fetched=8,
        refused=[],
    )
    return ResearchBrief(
        keyword=keyword,
        geo=None,
        serp_date="2026-07-16",
        intent=intent,  # type: ignore[arg-type]
        intent_confidence=0.8,
        terms=terms,
        cluster=cluster,
        content_format=FormatDecision(
            recommended=recommended_format,  # type: ignore[arg-type]
            confidence=format_confidence,
            signals={},
        ),
        fanout=[f"What is {keyword}?", f"How much does {keyword} cost?"],
        winnability=WinnabilityReport(client_da=40.0, neutral_da_assumed=False, targets=[]),
        teardown=teardown,
        registry=[],
        low_confidence=False,
        degraded=False,
        notes=[],
    )


def _source_pack(
    *,
    proof: list[str] | None = None,
    testimonials: list[str] | None = None,
    unique_data: list[str] | None = None,
    locations: list[LocalProfile] | None = None,
    nap: NAP | None = None,
) -> SourcePack:
    return SourcePack(
        client_name="Acme Roofing",
        facts={"years_experience": "18", "warranty": "25-year workmanship warranty"},
        services=["Roof repair", "Roof replacement", "Gutter installation"],
        proof_points=proof if proof is not None else ["Rebuilt 40 storm-damaged roofs in 2025"],
        testimonials=testimonials if testimonials is not None else ["'They saved our home' - J. Doe"],
        unique_data=unique_data
        if unique_data is not None
        else ["Our 2025 study of 500 roofs found 30% needed only spot repair"],
        internal_urls={"roof replacement": "/services/roof-replacement"},
        nap=nap,
        locations=locations or [],
    )


def _schema_ok() -> ValidationResult:
    return ValidationResult(valid=True, primary_type="Service", errors=[], warnings=[])


# --------------------------------------------------------------------------- #
# 0. The happy path: a well-formed, grounded draft PASSES.
# --------------------------------------------------------------------------- #
def test_well_formed_draft_passes_the_gate() -> None:
    result = score(_content(), _brief(), _schema_ok(), _source_pack())
    assert isinstance(result, QaScore)
    assert result.passed is True
    assert result.blocked_by == []
    assert result.weighted_total >= WEIGHTED_TOTAL_THRESHOLD
    assert min(result.dimensions.values()) >= MIN_DIMENSION_SCORE
    assert result.provisional is True


# --------------------------------------------------------------------------- #
# 1. A sub-threshold draft is BLOCKED.
# --------------------------------------------------------------------------- #
def test_sub_threshold_draft_is_blocked() -> None:
    # Ungrounded angle + an unresolved [NEEDS:] + no first-hand signal => several
    # hard gates trip at once.
    bad_angle = DifferentiationAngle(
        kind="missed_angle",
        statement="[NEEDS: unique data or first-hand experience]",
        grounded=False,
        derived_from=[],
    )
    content = _content(
        draft_md="# Roof repair\n\n[NEEDS: first-hand experience]\n\nThin body.",
        angle=bad_angle,
        needs=["first-hand experience", "unique data for the differentiation angle"],
    )
    result = score(content, _brief(), _schema_ok(), _source_pack(proof=[], testimonials=[]))
    assert result.passed is False
    assert result.blocked_by  # at least one critical dimension tripped
    assert "fact_grounding" in result.blocked_by
    assert "information_gain" in result.blocked_by


# --------------------------------------------------------------------------- #
# 2. A keyword-stuffed draft scores low on keyword handling.
# --------------------------------------------------------------------------- #
def test_keyword_stuffed_draft_scores_low_on_keyword_handling() -> None:
    stuffed = _content(primary_density=0.05)  # far above the 2-3% ceiling
    result = score(stuffed, _brief(), _schema_ok(), _source_pack())
    assert result.dimensions["keyword_handling"] < MIN_DIMENSION_SCORE
    assert result.passed is False


def test_over_optimized_anchors_penalize_keyword_handling() -> None:
    exact = [
        InternalLink(anchor="roof repair", url="/a", keyword="roof repair cost"),
        InternalLink(anchor="roof repair", url="/b", keyword="roof leak"),
    ]
    result = score(_content(internal_links=exact), _brief(), _schema_ok(), _source_pack())
    assert result.dimensions["keyword_handling"] <= 55


# --------------------------------------------------------------------------- #
# 3. A draft missing the differentiation angle FAILS the info-gain hard gate.
# --------------------------------------------------------------------------- #
def test_missing_differentiation_angle_fails_info_gain_hard_gate() -> None:
    ungrounded = DifferentiationAngle(
        kind="missed_angle",
        statement="[NEEDS: unique data or first-hand experience to establish an information-gain angle]",
        grounded=False,
        derived_from=[],
    )
    result = score(_content(angle=ungrounded), _brief(), _schema_ok(), _source_pack())
    assert result.dimensions["information_gain"] < MIN_DIMENSION_SCORE
    assert "information_gain" in result.blocked_by
    assert result.passed is False


def test_thin_angle_statement_is_not_substantive() -> None:
    thin = DifferentiationAngle(kind="missed_angle", statement="Better roofs", grounded=True, derived_from=[])
    result = score(_content(angle=thin), _brief(), _schema_ok(), _source_pack())
    assert result.dimensions["information_gain"] < MIN_DIMENSION_SCORE


# --------------------------------------------------------------------------- #
# 4. A concrete claim not in the source pack FAILS fact-grounding.
# --------------------------------------------------------------------------- #
def test_untraceable_claim_fails_fact_grounding() -> None:
    draft = _GOOD_DRAFT + "\n\nWe have completed 9999 roofs across 47 states.\n"
    result = score(_content(draft_md=draft), _brief(), _schema_ok(), _source_pack())
    assert result.dimensions["fact_grounding"] < MIN_DIMENSION_SCORE
    assert "fact_grounding" in result.blocked_by
    assert result.passed is False


def test_unresolved_needs_placeholder_tanks_grounding() -> None:
    result = score(
        _content(needs=["NAP (business name, address, phone)"]),
        _brief(),
        _schema_ok(),
        _source_pack(),
    )
    assert result.dimensions["fact_grounding"] <= 20
    assert "fact_grounding" in result.blocked_by


# --------------------------------------------------------------------------- #
# 5. A blog draft scored against a product SERP fails SERP-format fit.
# --------------------------------------------------------------------------- #
def test_blog_against_product_serp_fails_format_fit() -> None:
    blog = _content(page_type="blog")
    result = score(blog, _brief(recommended_format="product", format_confidence=0.7), _schema_ok(), _source_pack())
    assert result.dimensions["serp_format_fit"] < MIN_DIMENSION_SCORE
    assert result.passed is False


def test_matching_format_passes_format_fit() -> None:
    result = score(_content(page_type="service"), _brief(recommended_format="blog"), _schema_ok(), _source_pack())
    assert result.dimensions["serp_format_fit"] == 100


# --------------------------------------------------------------------------- #
# 6. The weighted total + pass/block are computed exactly.
# --------------------------------------------------------------------------- #
def test_weighted_total_matches_the_weight_vector() -> None:
    result = score(_content(), _brief(), _schema_ok(), _source_pack())
    expected = round(sum(result.dimensions[dim] * DIMENSION_WEIGHTS[dim] for dim in QA_DIMENSIONS))
    assert result.weighted_total == expected
    assert 0 <= result.weighted_total <= 100
    # The weight vector is a proper convex combination.
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9
    assert set(DIMENSION_WEIGHTS) == set(QA_DIMENSIONS)


def test_hard_gate_blocks_even_when_total_is_high() -> None:
    # A single ungrounded angle blocks publish though every other dim is strong.
    ungrounded = DifferentiationAngle(kind="missed_angle", statement="[NEEDS: angle]", grounded=False, derived_from=[])
    result = score(_content(angle=ungrounded), _brief(), _schema_ok(), _source_pack())
    assert "information_gain" in result.blocked_by
    assert result.passed is False


# --------------------------------------------------------------------------- #
# 7. Degrade WITHOUT a judge still scores all 14 dimensions.
# --------------------------------------------------------------------------- #
def test_degrade_without_judge_still_scores_all_dimensions() -> None:
    result = score(_content(), _brief(), _schema_ok(), _source_pack(), judge=None)
    assert set(result.dimensions) == set(QA_DIMENSIONS)
    assert len(result.dimensions) == 14
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in result.dimensions.values())


def test_no_schema_result_degrades_schema_dimension() -> None:
    result = score(_content(), _brief(), None, _source_pack())
    assert result.dimensions["schema_validity"] == 60


# --------------------------------------------------------------------------- #
# 8. The injected judge is used, but a doctrine floor still dominates it.
# --------------------------------------------------------------------------- #
def test_judge_scores_the_llm_dimensions() -> None:
    judge = FakeJudge(default=91)
    result = score(_content(), _brief(), _schema_ok(), _source_pack(), judge=judge)
    # Every LLM-assisted dimension was routed through the judge.
    assert set(judge.calls) >= {"intent_match", "eeat_experience", "information_gain", "cta_ux", "originality"}
    assert result.dimensions["intent_match"] == 91
    assert result.dimensions["cta_ux"] == 91


def test_low_judge_intent_blocks_publish() -> None:
    judge = FakeJudge({"intent_match": 50})
    result = score(_content(), _brief(), _schema_ok(), _source_pack(), judge=judge)
    assert result.dimensions["intent_match"] == 50
    assert "intent_match" in result.blocked_by
    assert result.passed is False


def test_doctrine_floor_overrides_a_generous_judge_on_info_gain() -> None:
    # The judge loves it, but the angle is ungrounded => the deterministic cap wins.
    judge = FakeJudge({"information_gain": 100})
    ungrounded = DifferentiationAngle(kind="missed_angle", statement="[NEEDS: angle]", grounded=False, derived_from=[])
    result = score(_content(angle=ungrounded), _brief(), _schema_ok(), _source_pack(), judge=judge)
    assert result.dimensions["information_gain"] < MIN_DIMENSION_SCORE


def test_doctrine_floor_overrides_judge_on_zero_experience_eeat() -> None:
    judge = FakeJudge({"eeat_experience": 99})
    result = score(_content(), _brief(), _schema_ok(), _source_pack(proof=[], testimonials=[]), judge=judge)
    assert result.dimensions["eeat_experience"] <= 40


# --------------------------------------------------------------------------- #
# 9. Local relevance: anatomy + per-city uniqueness.
# --------------------------------------------------------------------------- #
def test_local_page_below_uniqueness_floor_scores_low() -> None:
    local_draft = _GOOD_DRAFT + "\n\nThis page must stay consistent with the Google Business Profile.\n"
    content = _content(
        draft_md=local_draft,
        page_type="local",
        local_uniqueness={"Austin": 0.20, "Dallas": 0.22},
    )
    result = score(content, _brief(recommended_format="local"), _schema_ok(), _source_pack())
    assert result.dimensions["local_relevance"] < MIN_DIMENSION_SCORE
    # Boilerplate city pages also drag originality down (via the local cap).
    assert result.dimensions["originality"] <= 55


def test_non_local_page_local_relevance_not_applicable() -> None:
    result = score(_content(page_type="service"), _brief(), _schema_ok(), _source_pack())
    assert result.dimensions["local_relevance"] == 100
