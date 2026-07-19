"""P7A-6: the 14-dimension Content QA scorecard - the hard publish gate.

This is a PURE service (mirrors ``content_generator.py``'s purity): the core is
deterministic - no DB, no network, no hidden globals - and the ONLY external touch
is an INJECTED, cost-gated ``Judge`` for the handful of judgment dimensions an LLM
scores better than a rule. Given no judge (or a deterministic fake) the whole
:func:`score` call is deterministic, so unit tests run with ZERO network.

It consumes the outputs of the earlier chunks and grades one draft against the
Content Doctrine's 14 QA dimensions (``docs/CONTENT-DOCTRINE.md`` §11 - the single
source of truth):

* the generator's :class:`~app.services.content_generator.GeneratedContent` (the
  draft + its ``differentiation_angle`` + the ``grounding`` trace + the counts);
* the research :class:`~app.services.content_research.ResearchBrief` (the entity
  set, the top-10 teardown's table-stakes vs differentiator entities, the intent,
  and the SERP-derived content format);
* the schema :class:`~app.services.content_schema.ValidationResult` (schema
  validity, match-visible-content);
* the per-client :class:`~app.services.content_generator.SourcePack` (the
  source-of-truth corpus fact-grounding audits every concrete claim against).

The load-bearing split (why the gate is a guarantee, not a vibe):

* **Deterministic sub-scorers** own everything a rule can decide truthfully:
  entity coverage, keyword handling / anti-stuffing, structure + readability
  (Flesch), snippet / AI extractability, schema validity, internal linking,
  SERP-format fit, local relevance, and - critically - **fact-grounding** (every
  concrete claim must trace to the grounding trace or the source pack; any
  ``[NEEDS:]`` placeholder or untraceable number tanks the dimension) and the
  **information-gain** hard gate (the mandatory ``differentiation_angle`` must be
  present, substantive, and grounded).
* **LLM-assisted dims** (``intent_match``, ``eeat_experience``, ``information_gain``
  quality, ``cta_ux``, and ``originality``'s plagiarism check) flow through the
  injected :class:`Judge`. Absent a judge they DEGRADE to a conservative
  deterministic proxy (and originality to an internal-duplication heuristic) - the
  gate always produces a score, it never crashes and never no-ops.
* **Doctrine floors always dominate.** Even a generous judge cannot rescue a draft
  that fails a deterministic doctrine rule (an ungrounded angle, zero first-hand
  experience) - the deterministic cap is applied after the judge.

The publish decision (doctrine §11): **no dimension < 70 AND weighted total >= 85**,
and the five critical dims (fact-grounding, originality, intent-match, E-E-A-T,
information-gain) HARD-BLOCK below their floor regardless of the total. Both the
threshold and the weight vector are **PROVISIONAL (R4)** - named constants here,
calibrated later by the live golden-set (P7A-10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.content_generator import (
    ANSWER_MAX_WORDS,
    ANSWER_MIN_WORDS,
    LOCAL_UNIQUE_MIN,
    PRIMARY_DENSITY_HARD_CEILING,
    PRIMARY_DENSITY_TARGET_MAX,
    PRIMARY_DENSITY_TARGET_MIN,
    GeneratedContent,
    SourcePack,
)
from app.services.content_research import ResearchBrief
from app.services.content_schema import ValidationResult

# --------------------------------------------------------------------------- #
# Doctrine constants (docs/CONTENT-DOCTRINE.md §11 is the source of truth).
# --------------------------------------------------------------------------- #
# The 14 QA dimensions this gate scores (0-100 each). Canonical snake_case keys;
# each maps to a doctrine §11 dimension.
QA_DIMENSIONS: tuple[str, ...] = (
    "intent_match",              # §11.1  - structure/format matches the brief intent
    "eeat_experience",           # §11.4  - first-hand Experience + expertise + trust
    "entity_coverage",           # §11.5  - table-stakes entities covered
    "keyword_handling",          # §11.6  - placement + density, anti-stuffing
    "structure_readability",     # §11.8/11 - one H1 + hierarchy + Flesch ~60-70
    "snippet_extractability",    # §11.7/9 - 40-55w answer block + lists/Q&A
    "originality",               # §11.14 - anti-scaled-content-abuse / no dup
    "fact_grounding",            # §11.2  - every claim traces; zero [NEEDS:]
    "local_relevance",           # §11.13 - local anatomy + per-city uniqueness
    "schema_validity",           # §11 (schema) - valid, match-visible JSON-LD
    "internal_linking",          # §11.10 - pillar<->cluster, varied anchors
    "cta_ux",                    # §11 (people-first UX) - clear CTA + media
    "information_gain",          # §11.3  - the mandatory differentiation angle
    "serp_format_fit",           # §11.1  - page-type matches the SERP format
)

# The five CRITICAL dimensions: below the hard-gate floor they BLOCK publish
# regardless of the weighted total (doctrine's non-negotiables).
HARD_GATE_DIMENSIONS: frozenset[str] = frozenset(
    {"fact_grounding", "originality", "intent_match", "eeat_experience", "information_gain"}
)

# --- PROVISIONAL (R4) publish thresholds --------------------------------------
# BOTH the thresholds AND the weight vector below are PROVISIONAL: they are the
# doctrine's starting point and will be CALIBRATED by the live golden-set in
# P7A-10. Treat them as tunable knobs, not settled truth. Change the doctrine §11
# numbers AND these constants together.
MIN_DIMENSION_SCORE = 70          # §11: no single dimension may fall below this
WEIGHTED_TOTAL_THRESHOLD = 85     # §11: the weighted total must reach this to pass
HARD_GATE_FLOOR = 70              # a critical dim below this hard-blocks (== the per-dim min)
PROVISIONAL = True                # every score this module emits is R4-provisional

# PROVISIONAL (R4) weight vector - sums to 1.0; grounding + the differentiation
# angle + intent/E-E-A-T carry the most weight (the doctrine's quality core).
DIMENSION_WEIGHTS: dict[str, float] = {
    "fact_grounding": 0.13,
    "information_gain": 0.11,
    "intent_match": 0.10,
    "eeat_experience": 0.10,
    "entity_coverage": 0.08,
    "originality": 0.08,
    "structure_readability": 0.07,
    "snippet_extractability": 0.07,
    "keyword_handling": 0.06,
    "serp_format_fit": 0.05,
    "internal_linking": 0.04,
    "schema_validity": 0.04,
    "cta_ux": 0.04,
    "local_relevance": 0.03,
}

# Deterministic caps the doctrine floors clamp the LLM/proxy scores to (so a
# generous judge can never override a hard doctrine failure).
_ANGLE_MISSING_CAP = 25           # §7: an ungrounded/absent differentiation angle
_NO_FIRST_HAND_CAP = 40           # §2/§11.4: a page with zero first-hand Experience
_GROUNDING_NEEDS_SCORE = 15       # §2: an unresolved [NEEDS:] hard-blocks publish
_GROUNDING_UNTRACEABLE_SCORE = 40 # §2: any untraceable concrete claim tanks grounding
_LOCAL_BOILERPLATE_CAP = 55       # §8: a city page below the uniqueness floor

# CTA / next-step phrases that mark a people-first call to action (§11).
_CTA_PHRASES: tuple[str, ...] = (
    "ready to", "get started", "next step", "move forward", "contact",
    "book ", "call us", "request", "get a quote", "schedule",
)

# SERP-format -> the page-types that legitimately satisfy it (doctrine §5). A blog
# scored against a product SERP (product not in {blog}) is a format miss.
_FORMAT_PAGE_FIT: dict[str, frozenset[str]] = {
    "blog": frozenset({"blog", "service"}),
    "product": frozenset({"service", "product"}),
    "local": frozenset({"local"}),
    "comparison": frozenset({"blog", "service"}),
    "tool": frozenset({"tool", "service"}),
    "video": frozenset({"blog", "service"}),
}

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_MD_SYNTAX_RE = re.compile(r"[#*`>\[\]()|]|https?://\S+")
_VOWEL_RUN_RE = re.compile(r"[aeiouy]+")
_SENTENCE_RE = re.compile(r"[.!?]+")
_NON_DIGIT_RE = re.compile(r"\D")
# A "concrete claim" token: money, a percentage, or a standalone 2+ digit number.
# The word-boundary anchors keep hex/id fragments (e.g. "a1b2c3f0") from matching.
_MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s?%")
_NUMBER_RE = re.compile(r"(?<![\w$])\d{2,}(?:,\d{3})*(?:\.\d+)?(?![\w%])")


# --------------------------------------------------------------------------- #
# The judge seam (the ONLY external touch; cost-gated in the worker)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class JudgeVerdict:
    """One judge verdict: a 0-100 ``score`` + a short ``rationale`` (for audit)."""

    score: int
    rationale: str = ""


@runtime_checkable
class Judge(Protocol):
    """The single door the QA gate uses for LLM-assisted judgment dimensions.

    In the worker this is a COST-GATED implementation (mirrors
    ``context_cost.GatedSummarizer`` / ``content_research.GatedResearcher``), so
    every ``assess`` is metered by the Part-2 money-dial and the pure scorer can
    never reach a raw provider. A production judge routes ``dimension="originality"``
    to its plagiarism provider and the rest to the LLM rubric; the pure scorer only
    sees this seam. Given ``judge=None`` the gate degrades to deterministic proxies.
    """

    def assess(self, dimension: str, *, draft: str, criteria: str, context: str = "") -> JudgeVerdict:
        ...


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class QaScore:
    """The QA verdict for one draft.

    ``dimensions`` is every §11 dimension -> its 0-100 score; ``weighted_total`` is
    the PROVISIONAL weighted roll-up (0-100); ``passed`` is the publish decision
    (no dim < 70, weighted total >= 85, and no hard gate tripped); ``blocked_by``
    lists the critical dimensions that hard-blocked publish; ``provisional`` is
    always ``True`` (the thresholds + weights are calibrated in P7A-10). ``notes``
    records every deduction so a reviewer sees *why*, never a silent score.
    """

    dimensions: dict[str, int]
    weighted_total: int
    passed: bool
    blocked_by: list[str]
    provisional: bool = True
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _prose(draft_md: str) -> str:
    """Strip markdown syntax + URLs so readability/originality see body text."""
    return re.sub(r"\s+", " ", _MD_SYNTAX_RE.sub(" ", draft_md)).strip()


def _digits(text: str) -> str:
    return _NON_DIGIT_RE.sub("", text)


def _clamp_score(value: float) -> int:
    """Clamp any raw score into the 0-100 integer band."""
    return max(0, min(100, round(value)))


def _syllables(word: str) -> int:
    """Approximate syllable count: vowel groups, minus a trailing silent 'e'."""
    lowered = word.lower()
    count = len(_VOWEL_RUN_RE.findall(lowered))
    if lowered.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def flesch_reading_ease(prose: str) -> float:
    """The Flesch Reading Ease of ``prose`` (doctrine §11.11 targets ~60-70).

    Higher is easier; ~60-70 is plain, people-first English. Deterministic: word
    tokens, sentence terminators, and vowel-group syllables only - no dependency.
    """
    words = _words(prose)
    if not words:
        return 0.0
    sentences = max(1, len(_SENTENCE_RE.findall(prose)))
    syllables = sum(_syllables(word) for word in words)
    words_per_sentence = len(words) / sentences
    syllables_per_word = syllables / len(words)
    return 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word


def _has_cta(content: GeneratedContent) -> bool:
    """Whether the draft carries a clear call-to-action (heading or meta)."""
    haystacks = [h.text.lower() for h in content.headings]
    haystacks.append(content.meta_description.lower())
    return any(phrase in text for text in haystacks for phrase in _CTA_PHRASES)


def _covered_entities(draft_md: str, entities: list[str]) -> tuple[list[str], list[str]]:
    """Split ``entities`` into those present in the draft vs missing (§11.5)."""
    low = draft_md.lower()
    covered = [e for e in entities if e.lower() in low]
    missing = [e for e in entities if e.lower() not in low]
    return covered, missing


def _needs_present(content: GeneratedContent) -> bool:
    """Whether any unresolved ``[NEEDS:]`` gap remains (hard-blocks grounding §2)."""
    return bool(content.needs) or "[NEEDS:" in content.draft_md


def _angle_is_substantive(content: GeneratedContent) -> bool:
    """Whether the mandatory differentiation angle is present + grounded +
    substantive (doctrine §7): grounded, no ``[NEEDS:]``, and a real statement."""
    angle = content.differentiation_angle
    statement = angle.statement.strip()
    return (
        angle.grounded
        and bool(statement)
        and "[NEEDS:" not in statement
        and len(_words(statement)) >= 5
    )


def _concrete_claim_digits(draft_md: str) -> list[str]:
    """Every concrete numeric claim in the draft, as its digit string (money,
    percentages, and standalone 2+ digit numbers) - the fact-grounding audit set."""
    tokens: list[str] = []
    for match in _MONEY_RE.findall(draft_md):
        tokens.append(_digits(match))
    for match in _PERCENT_RE.findall(draft_md):
        tokens.append(_digits(match))
    for match in _NUMBER_RE.findall(draft_md):
        tokens.append(_digits(match))
    return [t for t in tokens if t]


def _grounded_corpus_digits(content: GeneratedContent, source_pack: SourcePack) -> str:
    """The digit string of everything the draft is ALLOWED to claim: the grounding
    trace values + the whole source pack. A concrete number not in here is
    untraceable (an invented fact) and tanks grounding (§2)."""
    parts: list[str] = [claim.claim for claim in content.grounding]
    parts.append(source_pack.client_name)
    parts.extend(source_pack.services)
    parts.extend(source_pack.proof_points)
    parts.extend(source_pack.unique_data)
    parts.extend(source_pack.testimonials)
    parts.extend(str(v) for v in source_pack.facts.values())
    if source_pack.nap is not None:
        parts.append(f"{source_pack.nap.name} {source_pack.nap.address} {source_pack.nap.phone}")
    for location in source_pack.locations:
        parts.extend(location.proof)
        if location.nap is not None:
            parts.append(f"{location.nap.name} {location.nap.address} {location.nap.phone}")
    return _digits(" ".join(parts))


# --------------------------------------------------------------------------- #
# Deterministic sub-scorers -> (score, notes)
# --------------------------------------------------------------------------- #
def _score_entity_coverage(content: GeneratedContent, brief: ResearchBrief) -> tuple[int, list[str]]:
    """§11.5: the fraction of the teardown's table-stakes entities the draft
    covers. No table-stakes to cover => full marks (nothing is required)."""
    table_stakes = list(brief.teardown.table_stakes_entities)
    if not table_stakes:
        return 100, []
    covered, missing = _covered_entities(content.draft_md, table_stakes)
    score = _clamp_score(100 * len(covered) / len(table_stakes))
    notes = [f"missing table-stakes entities: {', '.join(missing)}"] if missing else []
    return score, notes


def _score_keyword_handling(content: GeneratedContent, brief: ResearchBrief) -> tuple[int, list[str]]:
    """§11.6/§3: primary density inside the target band, hard penalty for stuffing
    above the ceiling, and a penalty for over-optimized exact-match anchors."""
    density = content.primary_density
    primary = brief.terms.primary.strip().lower()
    notes: list[str] = []
    if density > PRIMARY_DENSITY_HARD_CEILING:
        score = 25
        notes.append(f"primary density {density:.3f} over the {PRIMARY_DENSITY_HARD_CEILING} stuffing ceiling")
    elif density > PRIMARY_DENSITY_TARGET_MAX:
        score = 72
        notes.append(f"primary density {density:.3f} above the {PRIMARY_DENSITY_TARGET_MAX} target")
    elif density < PRIMARY_DENSITY_TARGET_MIN:
        score = 68
        notes.append(f"primary density {density:.3f} below the {PRIMARY_DENSITY_TARGET_MIN} target")
    else:
        score = 100
    exact_anchors = sum(1 for link in content.internal_links if link.anchor.strip().lower() == primary)
    if exact_anchors >= 2:
        score = min(score, 55)
        notes.append(f"{exact_anchors} over-optimized exact-match '{primary}' anchors")
    if primary and primary not in content.title.lower():
        score -= 10
        notes.append("primary not front-loaded in the title")
    return _clamp_score(score), notes


def _score_structure_readability(content: GeneratedContent) -> tuple[int, list[str]]:
    """§11.8/§11.11: exactly one H1, a non-skipping heading hierarchy, the answer
    block within the word band, and a Flesch reading ease near the 60-70 target."""
    notes: list[str] = []
    structure = 100
    h1_count = sum(1 for h in content.headings if h.level == 1)
    if h1_count != 1:
        structure -= 40
        notes.append(f"expected exactly one H1, found {h1_count}")
    answer_words = len(content.answer_block.split())
    if not (ANSWER_MIN_WORDS <= answer_words <= ANSWER_MAX_WORDS):
        structure -= 15
        notes.append(f"answer block is {answer_words} words (want {ANSWER_MIN_WORDS}-{ANSWER_MAX_WORDS})")
    prev_level = 0
    for heading in content.headings:
        if prev_level and heading.level > prev_level + 1:
            structure -= 15
            notes.append(f"heading hierarchy skips a level (H{prev_level} -> H{heading.level})")
            break
        prev_level = heading.level

    flesch = flesch_reading_ease(_prose(content.draft_md))
    if 55 <= flesch <= 75:
        readability = 100
    elif 45 <= flesch <= 85:
        readability = 88
    elif 35 <= flesch <= 95:
        readability = 74
    else:
        readability = 55
        notes.append(f"Flesch reading ease {flesch:.0f} is far from the 60-70 target")

    score = _clamp_score(0.5 * _clamp_score(structure) + 0.5 * readability)
    return score, notes


def _score_snippet_extractability(content: GeneratedContent, brief: ResearchBrief) -> tuple[int, list[str]]:
    """§11.7/§11.9: a 40-55-word self-contained answer block carrying the primary,
    plus Q&A (H3) + lists so snippets and AI Overviews can lift the page."""
    notes: list[str] = []
    score = 100
    answer = content.answer_block
    answer_words = len(answer.split())
    if not answer:
        score -= 40
        notes.append("no extractable answer block")
    elif not (ANSWER_MIN_WORDS <= answer_words <= ANSWER_MAX_WORDS):
        score -= 20
        notes.append(f"answer block is {answer_words} words (want {ANSWER_MIN_WORDS}-{ANSWER_MAX_WORDS})")
    if not any(h.level == 3 for h in content.headings):
        score -= 15
        notes.append("no Q&A/FAQ (H3) sub-headings")
    if not re.search(r"^\s*[-*] ", content.draft_md, re.MULTILINE) and "|" not in content.draft_md:
        score -= 10
        notes.append("no lists or tables for extractability")
    primary = brief.terms.primary.strip().lower()
    if primary and answer and primary not in answer.lower():
        score -= 10
        notes.append("primary keyword absent from the answer block")
    return _clamp_score(score), notes


def _score_schema_validity(
    schema_result: ValidationResult | None, page_type: str = ""
) -> tuple[int, list[str]]:
    """§11 (schema): validity + match-visible-content from the schema chunk's
    :class:`ValidationResult`. Errors fail hard; warnings shave a little. A
    ``gbp_post`` carries no JSON-LD (``schema_for`` maps it to ``""`` - it is
    never rendered as its own page), so a missing result is EXPECTED there, not
    a quality gap - not applicable (mirrors ``_score_local_relevance``'s
    non-local early-return)."""
    if page_type == "gbp_post":
        return 100, []
    if schema_result is None:
        return 60, ["no JSON-LD validation result supplied"]
    if not schema_result.valid:
        score = _clamp_score(60 - 15 * len(schema_result.errors))
        return score, [f"invalid JSON-LD: {'; '.join(schema_result.errors)}"]
    score = _clamp_score(100 - 5 * len(schema_result.warnings))
    notes = [f"schema warnings: {'; '.join(schema_result.warnings)}"] if schema_result.warnings else []
    return score, notes


def _score_internal_linking(content: GeneratedContent, brief: ResearchBrief) -> tuple[int, list[str]]:
    """§11.10: pillar<->cluster internal links present, with VARIED anchors (not
    the same exact-match anchor everywhere). A ``gbp_post`` is a standalone
    business-update post, never part of a pillar/cluster page scheme, so the
    dimension is not applicable (mirrors ``_score_local_relevance``'s
    non-local early-return) - a real page with zero internal links still fails."""
    if content.page_type == "gbp_post":
        return 100, []
    links = content.internal_links
    if not links:
        return 40, ["no internal links (pillar<->cluster map not applied)"]
    notes: list[str] = []
    score = 100
    if len(links) < 2:
        score -= 20
        notes.append("only one internal link")
    anchors = [link.anchor.strip().lower() for link in links]
    variety = len(set(anchors)) / len(anchors)
    if variety < 0.7:
        score -= 20
        notes.append("repetitive internal-link anchors")
    cluster_keywords = {s.lower() for s in brief.cluster.supporting} | {brief.cluster.pillar.lower()}
    if not any(link.keyword.strip().lower() in cluster_keywords for link in links):
        score -= 15
        notes.append("no link resolves to a cluster/pillar keyword")
    return _clamp_score(score), notes


def _score_serp_format_fit(content: GeneratedContent, brief: ResearchBrief) -> tuple[int, list[str]]:
    """§11.1/§5: the page-type must satisfy the SERP-derived content format. A blog
    scored against a product SERP is a miss and fails this dimension. A
    ``gbp_post`` never competes for a SERP position (it's a Business Profile
    update, not an indexed page), so it is not applicable here (mirrors
    ``_score_local_relevance``'s non-local early-return)."""
    if content.page_type == "gbp_post":
        return 100, []
    recommended = brief.content_format.recommended
    fit_types = _FORMAT_PAGE_FIT.get(recommended, frozenset({"blog", "service", "local"}))
    if content.page_type in fit_types:
        score = 100
        notes: list[str] = []
        if recommended == "comparison" and "|" not in content.draft_md:
            score -= 15
            notes.append("comparison SERP but the draft carries no comparison table")
        return _clamp_score(score), notes
    # A confident format decision that the page-type contradicts fails hard; a
    # low-confidence one only warns.
    confident = brief.content_format.confidence >= 0.5
    score = 45 if confident else 65
    return score, [
        f"page-type '{content.page_type}' does not fit the SERP format '{recommended}'"
    ]


def _score_local_relevance(content: GeneratedContent) -> tuple[int, list[str]]:
    """§11.13: for a local page - NAP present, per-city sections + uniqueness above
    the floor, and a GBP-alignment note. Not a local page => not applicable."""
    if content.page_type != "local":
        return 100, []
    notes: list[str] = []
    score = 100
    needs_blob = " ".join(content.needs).lower()
    if "nap" in needs_blob:
        score -= 30
        notes.append("NAP missing on a local page")
    if "local proof" in needs_blob:
        score -= 20
        notes.append("local proof missing for a served city")
    if content.local_uniqueness:
        worst = min(content.local_uniqueness.values())
        if worst < LOCAL_UNIQUE_MIN:
            score -= 40  # §8: a boilerplate city page is a hard white-hat violation
            notes.append(f"a city page is only {worst:.0%} unique (floor {LOCAL_UNIQUE_MIN:.0%})")
    else:
        score -= 20
        notes.append("no per-city uniqueness computed")
    if "google business profile" not in content.draft_md.lower():
        score -= 10
        notes.append("no Google Business Profile alignment note")
    return _clamp_score(score), notes


def _score_fact_grounding(content: GeneratedContent, source_pack: SourcePack) -> tuple[int, list[str]]:
    """§11.2: every concrete claim must trace to the grounding trace or the source
    pack; an unresolved ``[NEEDS:]`` or any untraceable number tanks the dimension."""
    if _needs_present(content):
        return _GROUNDING_NEEDS_SCORE, [
            f"unresolved [NEEDS:] gap(s) block publish: {', '.join(content.needs) or 'in draft body'}"
        ]
    corpus = _grounded_corpus_digits(content, source_pack)
    untraceable = [tok for tok in _concrete_claim_digits(content.draft_md) if tok not in corpus]
    if untraceable:
        return _GROUNDING_UNTRACEABLE_SCORE, [
            f"untraceable concrete claim(s) not in source/grounding: {', '.join(sorted(set(untraceable)))}"
        ]
    return 100, []


# --------------------------------------------------------------------------- #
# LLM-assisted dims: judge when present, conservative deterministic proxy absent.
# The doctrine caps are applied AFTER, so the judge can never override a hard rule.
# --------------------------------------------------------------------------- #
def _judge_score(judge: Judge, dimension: str, *, draft: str, criteria: str, context: str) -> int:
    verdict = judge.assess(dimension, draft=draft, criteria=criteria, context=context)
    return _clamp_score(verdict.score)


def _proxy_intent_match(content: GeneratedContent, brief: ResearchBrief) -> int:
    """Conservative proxy for §11.1: reward the structural signals the brief's
    intent expects (an answer block; Q&A for info/commercial; a CTA for
    commercial/transactional)."""
    score = 85
    if not content.answer_block:
        score -= 25
    has_faq = any(h.level == 3 for h in content.headings)
    if brief.intent in {"informational", "commercial"} and not has_faq:
        score -= 10
    if brief.intent in {"commercial", "transactional"} and not _has_cta(content):
        score -= 15
    if brief.intent_confidence < 0.3:
        score -= 5
    return _clamp_score(score)


def _proxy_eeat(content: GeneratedContent, source_pack: SourcePack) -> int:
    """Conservative proxy for §11.4: first-hand proof + testimonials + a dedicated
    Experience block are the E-E-A-T signals; zero first-hand is a hard drop."""
    score = 60
    if source_pack.proof_points:
        score += 20
    if source_pack.testimonials:
        score += 10
    if "why choose" in content.draft_md.lower():
        score += 10
    return _clamp_score(score)


def _proxy_cta_ux(content: GeneratedContent) -> int:
    """Conservative proxy for §11 people-first UX: a clear CTA + planned media +
    internal links + a CTA-bearing meta description."""
    score = 60
    if _has_cta(content):
        score += 20
    if content.images_plan:
        score += 10
    if content.internal_links:
        score += 10
    return _clamp_score(score)


def _internal_dup_originality(content: GeneratedContent) -> int:
    """Degrade proxy for §11.14 when no plagiarism judge is present: the distinct
    5-gram ratio over the body (spun/boilerplate text repeats, so scores low)."""
    words = [w.lower() for w in _words(_prose(content.draft_md))]
    if len(words) < 5:
        return 100
    shingles = [tuple(words[i : i + 5]) for i in range(len(words) - 4)]
    ratio = len(set(shingles)) / len(shingles)
    return _clamp_score(100 * ratio)


def _score_originality(content: GeneratedContent, judge: Judge | None) -> tuple[int, list[str]]:
    """§11.14: a key-gated plagiarism check via the judge; absent one, the internal
    -duplication heuristic. A city page below the uniqueness floor caps it (§8)."""
    notes: list[str] = []
    if judge is None:
        score = _internal_dup_originality(content)
    else:
        score = _judge_score(
            judge,
            "originality",
            draft=content.draft_md,
            criteria="Originality / anti-scaled-content-abuse: is this materially original, "
            "worth publishing even if search did not exist, and not spun boilerplate?",
            context=f"differentiation_angle={content.differentiation_angle.statement}",
        )
    if content.local_uniqueness:
        worst = min(content.local_uniqueness.values())
        if worst < LOCAL_UNIQUE_MIN:
            score = min(score, _LOCAL_BOILERPLATE_CAP)
            notes.append(f"a city page is only {worst:.0%} unique - boilerplate risk")
    return _clamp_score(score), notes


def _score_intent_match(content: GeneratedContent, brief: ResearchBrief, judge: Judge | None) -> int:
    if judge is None:
        return _proxy_intent_match(content, brief)
    return _judge_score(
        judge,
        "intent_match",
        draft=content.draft_md,
        criteria="Does the page's structure and format match the search intent?",
        context=f"intent={brief.intent}; format={brief.content_format.recommended}",
    )


def _score_eeat(content: GeneratedContent, source_pack: SourcePack, judge: Judge | None) -> tuple[int, list[str]]:
    """§11.4 with the doctrine floor: a page with zero first-hand Experience is
    capped low even if a judge is generous."""
    notes: list[str] = []
    if judge is None:
        score = _proxy_eeat(content, source_pack)
    else:
        score = _judge_score(
            judge,
            "eeat_experience",
            draft=content.draft_md,
            criteria="E-E-A-T with first-hand Experience as the key signal: real projects, "
            "results, credentials, testimonials, and trust signals.",
            context=f"proof_points={len(source_pack.proof_points)}; testimonials={len(source_pack.testimonials)}",
        )
    zero_first_hand = not source_pack.proof_points and not source_pack.testimonials
    experience_needed = any("experience" in need.lower() for need in content.needs)
    if zero_first_hand or experience_needed:
        score = min(score, _NO_FIRST_HAND_CAP)
        notes.append("zero first-hand Experience signal on the page")
    return _clamp_score(score), notes


def _score_information_gain(content: GeneratedContent, judge: Judge | None) -> tuple[int, list[str]]:
    """§11.3/§7: the mandatory differentiation angle. The deterministic gate (angle
    present + grounded + substantive) CAPS the dimension - a judge scores quality
    only within what the gate allows, and cannot rescue an absent angle."""
    if not _angle_is_substantive(content):
        return _ANGLE_MISSING_CAP, [
            "the mandatory information-gain / differentiation angle is absent or ungrounded"
        ]
    angle = content.differentiation_angle
    if judge is None:
        # Grounded angle: strongest kinds (unique data / first-hand) score highest.
        quality = 90 if angle.kind in {"unique_data", "first_hand_experience"} else 82
    else:
        quality = _judge_score(
            judge,
            "information_gain",
            draft=content.draft_md,
            criteria="Information gain: does the page add a real, provenance-backed "
            "differentiation angle beyond rehashing the top-10?",
            context=f"angle_kind={angle.kind}; statement={angle.statement}",
        )
    return _clamp_score(quality), []


# --------------------------------------------------------------------------- #
# The orchestrator
# --------------------------------------------------------------------------- #
def score(
    content: GeneratedContent,
    brief: ResearchBrief,
    schema_result: ValidationResult | None,
    source_pack: SourcePack,
    *,
    judge: Judge | None = None,
) -> QaScore:
    """Score a draft against the 14 QA dimensions and return the publish verdict.

    Deterministic given ``judge=None`` (or a deterministic judge). The deterministic
    sub-scorers own grounding, coverage, structure, keyword handling, schema,
    linking, format fit, local anatomy, and the information-gain gate; the injected
    (cost-gated) ``judge`` refines intent-match, E-E-A-T, information-gain quality,
    CTA/UX, and originality, degrading to conservative proxies when absent. Doctrine
    floors are applied last, so no judge can override a hard rule.

    Publish (``passed``) iff no dimension < :data:`MIN_DIMENSION_SCORE`, the
    weighted total >= :data:`WEIGHTED_TOTAL_THRESHOLD`, and no
    :data:`HARD_GATE_DIMENSIONS` dim fell below :data:`HARD_GATE_FLOOR`. Both
    thresholds + the weights are PROVISIONAL (R4), calibrated by the golden-set.
    """
    notes: list[str] = []
    dimensions: dict[str, int] = {}

    def record(dimension: str, result: tuple[int, list[str]]) -> None:
        value, reasons = result
        dimensions[dimension] = value
        notes.extend(f"{dimension}: {reason}" for reason in reasons)

    # Deterministic sub-scorers.
    record("entity_coverage", _score_entity_coverage(content, brief))
    record("keyword_handling", _score_keyword_handling(content, brief))
    record("structure_readability", _score_structure_readability(content))
    record("snippet_extractability", _score_snippet_extractability(content, brief))
    record("schema_validity", _score_schema_validity(schema_result, content.page_type))
    record("internal_linking", _score_internal_linking(content, brief))
    record("serp_format_fit", _score_serp_format_fit(content, brief))
    record("local_relevance", _score_local_relevance(content))
    record("fact_grounding", _score_fact_grounding(content, source_pack))

    # LLM-assisted (judge or proxy), with the doctrine floors applied inside.
    dimensions["intent_match"] = _score_intent_match(content, brief, judge)
    record("eeat_experience", _score_eeat(content, source_pack, judge))
    record("information_gain", _score_information_gain(content, judge))
    dimensions["cta_ux"] = _proxy_cta_ux(content) if judge is None else _judge_score(
        judge,
        "cta_ux",
        draft=content.draft_md,
        criteria="CTA / UX: is there a clear, well-placed call to action and a scannable, "
        "people-first layout?",
        context=f"page_type={content.page_type}",
    )
    record("originality", _score_originality(content, judge))

    # The weighted roll-up (PROVISIONAL R4 weights; sums to 1.0).
    weighted_total = _clamp_score(
        sum(dimensions[dim] * DIMENSION_WEIGHTS[dim] for dim in QA_DIMENSIONS)
    )

    # Hard gates: a critical dim below the floor blocks regardless of the total.
    blocked_by = sorted(
        dim for dim in HARD_GATE_DIMENSIONS if dimensions[dim] < HARD_GATE_FLOOR
    )
    below_min = [dim for dim in QA_DIMENSIONS if dimensions[dim] < MIN_DIMENSION_SCORE]
    passed = (
        not blocked_by
        and not below_min
        and weighted_total >= WEIGHTED_TOTAL_THRESHOLD
    )
    if below_min and not blocked_by:
        notes.append(f"below the {MIN_DIMENSION_SCORE} per-dimension floor: {', '.join(below_min)}")

    # Emit dimensions in the canonical §11 order.
    ordered = {dim: dimensions[dim] for dim in QA_DIMENSIONS}
    return QaScore(
        dimensions=ordered,
        weighted_total=weighted_total,
        passed=passed,
        blocked_by=blocked_by,
        provisional=PROVISIONAL,
        notes=notes,
    )
