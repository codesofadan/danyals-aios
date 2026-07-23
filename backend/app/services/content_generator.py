"""P7A-4: the ranking-grade Content GENERATOR - a PURE core that turns a research
:class:`ResearchBrief` + a per-client source-of-truth pack + fresh 6B context into
a people-first, grounded, extractable draft.

The standard it implements is committed at ``docs/CONTENT-DOCTRINE.md`` (the single
source of truth). This module encodes that doctrine's numeric rules as named
constants (each citing its section) and builds every draft to be *checkable* by the
later QA gate against the 14 QA dimensions (doctrine §11).

Design (mirrors ``context_compactor.py``'s purity): the core is PURE - no DB, no
network, no hidden globals. The ONLY external touch is the injected ``Summarizer``
writer seam (in the worker a cost-gated one, so the core can never reach a raw
provider). Given a deterministic ``FakeSummarizer``/``FakeWriter`` the whole
``generate`` call is deterministic, so unit tests run with ZERO network.

The load-bearing split (why "no invented facts" is a guarantee, not a hope):

* **The core is the grounding authority.** It assembles the skeleton
  deterministically - the one H1, the key heading + a 40-55-word extractable answer
  block, the framework outline, the entity-coverage checklist, the internal links,
  and (for local) the white-hat local anatomy - and feeds the writer ONLY facts
  drawn from the ``source_pack`` / fresh ``context``. Every grounded fact it injects
  is recorded in the ``grounding`` trace, so QA can audit provenance.
* **The writer only phrases.** It never sources a concrete claim; it turns the
  provided facts into prose. Section prose is HARD-BOUNDED to a per-section word
  budget (truncated if the provider overshoots), so a runaway provider can never
  blow the doctrine's word budget (doctrine §10) - the bound is a guarantee.
* **A missing fact becomes a ``[NEEDS: ...]`` placeholder**, never a hallucination
  (doctrine §1). A ``[NEEDS:]`` marker is a feature: it routes the gap to a human
  and hard-blocks publish until resolved.

Every draft MUST carry one explicit information-gain / differentiation angle
(doctrine §7) derived from the top-10 teardown's differentiator entities - the
anti-"scaled-content-abuse" lever. The generator resolves and EXPOSES it
(``differentiation_angle``) so the QA gate can enforce its presence + provenance.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.schemas.content import Framework, auto_framework
from app.services.content_research import ResearchBrief
from integrations.llm import Summarizer

if TYPE_CHECKING:  # a pure pydantic model; imported only for the adapter's typing
    from app.schemas.context import ContextView

# --------------------------------------------------------------------------- #
# Doctrine constants. The CANONICAL doctrine is the SEO-CONTENT-OS knowledge base
# (backend/seo-content-os/knowledge/); docs/CONTENT-DOCTRINE.md is the code<->knowledge
# cross-map. These constants ENFORCE a named numeric subset of that knowledge.
# --------------------------------------------------------------------------- #
# The enforced NUMBERS below are re-derived from the SEO-CONTENT-OS knowledge base
# (backend/seo-content-os/knowledge/ — the canonical doctrine; see docs/CONTENT-DOCTRINE.md).
# Each names the knowledge source it enforces.
# Passage-block opener band (foundations/passage-block-protocol.md: short-answer 60-120).
ANSWER_MIN_WORDS = 40
ANSWER_MAX_WORDS = 55
# Keyword handling: NO density TARGET (Law 17 - density gaming reduces AI citation).
# Placement matters, not a % floor; the only density rule is the anti-stuffing ceiling.
PRIMARY_DENSITY_TARGET_MIN = 0.0
PRIMARY_DENSITY_TARGET_MAX = 0.02
PRIMARY_DENSITY_HARD_CEILING = 0.03  # G5 anti-stuffing ceiling
# Per-page word bounds are outer SAFETY clamps only (budgets are per-passage-block).
WORD_COUNT_FLOOR = 600
WORD_COUNT_CEILING = 3500
# Local uniqueness: the "genuine majority city-specific" heuristic (local-content-laws.md
# Law 15/16, NON-safe-harbor) - backed by the strip-the-city + external-verifiability gates.
LOCAL_UNIQUE_MIN = 0.50
# Media + FAQ + coverage caps (coverage is a floor to clear, never an auto-fail - Law 15).
MAX_IMAGES = 5
MAX_FAQ = 6
MAX_COVERAGE_ENTITIES = 8
MAX_INTERNAL_SPOKES = 6
# Title / meta length ceilings (foundations/meta-and-headings.md: ~50-60 title / ~160 meta).
TITLE_MAX_CHARS = 60
META_MAX_CHARS = 160

_DEFAULT_MODEL = "content-writer"
_DEFAULT_TARGET_WORDS = 1200
_MIN_SECTION_WORDS = 60
_INTRO_WORD_FRACTION = 0.6
_FAQ_ANSWER_WORDS = 45
_SCAFFOLD_RESERVE_WORDS = 400

# §7: the differentiation-angle kinds, in priority order.
DIFFERENTIATION_KINDS: tuple[str, ...] = (
    "unique_data",
    "first_hand_experience",
    "better_format",
    "missed_angle",
)

# §11: the 14 QA dimensions the QA gate consumes (mirrored from the doctrine so a
# later chunk imports one canonical tuple).
QA_DIMENSIONS: tuple[str, ...] = (
    "intent_match",
    "grounding_factual_accuracy",
    "information_gain",
    "eeat_experience",
    "entity_coverage",
    "keyword_placement_density",
    "extractable_answer_block",
    "heading_structure",
    "snippet_ai_overview_formatting",
    "internal_linking",
    "readability_people_first",
    "meta_title_description",
    "local_anatomy_uniqueness",
    "originality_anti_scaled_abuse",
)


# --------------------------------------------------------------------------- #
# §6: the 7 frameworks -> their ordered persuasion "moves" (role + H2 template).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Move:
    """One framework step: a stable ``role`` (for routing/tests) + an ``H2``
    heading template (uses ``{primary}`` / ``{client}``)."""

    role: str
    heading: str


_FRAMEWORK_MOVES: dict[Framework, tuple[_Move, ...]] = {
    "AIDA": (
        _Move("attention", "Why {primary} matters"),
        _Move("interest", "How {primary} works"),
        _Move("desire", "The benefits of choosing {client}"),
        _Move("action", "Get started with {primary}"),
    ),
    "PAS": (
        _Move("problem", "The problem with {primary}"),
        _Move("agitate", "Why it gets worse when ignored"),
        _Move("solution", "How to solve it"),
    ),
    "BAB": (
        _Move("before", "Where you are now"),
        _Move("after", "Where {primary} takes you"),
        _Move("bridge", "How {client} bridges the gap"),
    ),
    "FAB": (
        _Move("features", "{primary} features"),
        _Move("advantages", "What sets it apart"),
        _Move("benefits", "What you gain"),
    ),
    "4 Ps": (
        _Move("picture", "Picture the outcome"),
        _Move("promise", "Our promise"),
        _Move("prove", "The proof"),
        _Move("push", "Take the next step"),
    ),
    "PASTOR": (
        _Move("problem", "The problem"),
        _Move("amplify", "Why it matters"),
        _Move("story", "A real {primary} story"),
        _Move("testimonial", "What clients say"),
        _Move("offer", "Our offer"),
        _Move("response", "How to respond"),
    ),
    "4 U's": (
        _Move("useful", "The useful essentials of {primary}"),
        _Move("urgent", "Why act now"),
        _Move("unique", "What makes {client} unique"),
        _Move("ultra_specific", "Exactly what you get"),
    ),
}


# --------------------------------------------------------------------------- #
# Injected inputs (the generator's own shapes, mirroring how the compactor owns
# ``PriorContext`` rather than consuming a DB row).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NAP:
    """A local business's Name / Address / Phone - must match the GBP listing."""

    name: str
    address: str
    phone: str


@dataclass(frozen=True)
class LocalProfile:
    """One city the client serves + its FIRST-HAND local proof (real local
    projects / landmarks / named local clients) and optional per-city NAP."""

    city: str
    proof: list[str] = field(default_factory=list)
    nap: NAP | None = None


@dataclass(frozen=True)
class SourcePack:
    """The per-client SOURCE OF TRUTH - the ONLY facts the generator may state.

    Everything concrete a draft claims must live here (or in ``context``). Empty
    lists/dicts are fine; the generator degrades to ``[NEEDS: ...]`` placeholders
    for anything a section requires but cannot ground.
    """

    client_name: str
    facts: Mapping[str, str] = field(default_factory=dict)
    services: list[str] = field(default_factory=list)
    proof_points: list[str] = field(default_factory=list)  # §2 first-hand Experience
    unique_data: list[str] = field(default_factory=list)  # §7 information gain
    testimonials: list[str] = field(default_factory=list)
    internal_urls: Mapping[str, str] = field(default_factory=dict)  # keyword -> URL registry
    nap: NAP | None = None
    locations: list[LocalProfile] = field(default_factory=list)  # §8 local pages


@dataclass(frozen=True)
class GenerationContext:
    """Fresh 6B client context that grounds the draft (a light projection of the
    retrieval API's :class:`ContextView`): the living ``summary`` + folded
    ``facts`` + whether it is ``stale`` (so a caller can flag a degraded run)."""

    summary: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)
    stale: bool = False

    @classmethod
    def from_context_view(cls, view: ContextView | None) -> GenerationContext | None:
        """Adapt the retrieval API's ``ContextView`` (what
        ``context_service.get_context(entity=client, fresh=True)`` returns) into
        the generator's grounding input. ``None`` in => ``None`` out (degraded)."""
        if view is None:
            return None
        return cls(summary=view.summary, facts=dict(view.facts), stale=view.stale)


@dataclass(frozen=True)
class GeneratorTuning:
    """Operational knobs (a worker overrides from ``Settings``); defaults are the
    doctrine values so the pure call is self-contained + testable."""

    word_count_target: int | None = None  # override; else the teardown target
    word_count_floor: int = WORD_COUNT_FLOOR
    word_count_ceiling: int = WORD_COUNT_CEILING
    answer_min_words: int = ANSWER_MIN_WORDS
    answer_max_words: int = ANSWER_MAX_WORDS
    max_images: int = MAX_IMAGES
    max_faq: int = MAX_FAQ
    max_coverage_entities: int = MAX_COVERAGE_ENTITIES
    max_internal_spokes: int = MAX_INTERNAL_SPOKES


DEFAULT_TUNING = GeneratorTuning()


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Heading:
    """One heading in the draft outline (level 1-3)."""

    level: int
    text: str


@dataclass(frozen=True)
class InternalLink:
    """An internal-link suggestion: display ``anchor`` -> ``url`` for ``keyword``
    (from the keyword->URL registry or a cluster spoke's slug)."""

    anchor: str
    url: str
    keyword: str


@dataclass(frozen=True)
class ImagePlanItem:
    """One planned image: its ``slot`` (hero / section:<role>), a generation
    ``prompt``, and the authoritative ``alt`` text (accessibility + on-page SEO)."""

    slot: str
    prompt: str
    alt: str


@dataclass(frozen=True)
class GroundedClaim:
    """One entry in the grounding trace: a ``claim`` and the ``source`` key it
    traces to (e.g. ``source_pack.facts.<k>`` / ``context.summary``)."""

    claim: str
    source: str


@dataclass(frozen=True)
class DifferentiationAngle:
    """The mandatory information-gain angle (doctrine §7): its ``kind`` (one of
    :data:`DIFFERENTIATION_KINDS`), the ``statement`` woven into the draft, whether
    it is ``grounded`` (else a ``[NEEDS:]`` was emitted), and the top-10
    ``derived_from`` differentiator entities it was built on."""

    kind: str
    statement: str
    grounded: bool
    derived_from: list[str]


@dataclass(frozen=True)
class GeneratedContent:
    """The ranking-grade draft + everything the QA gate + publish chunk consume.

    ``grounding`` traces every concrete claim to its source; ``needs`` is the list
    of ``[NEEDS:]`` gaps the draft left rather than hallucinate; ``differentiation_
    angle`` is the enforced information-gain lever; ``local_uniqueness`` is the
    per-city uniqueness ratio (local pages).
    """

    title: str
    meta_description: str
    draft_md: str
    page_type: str
    framework: Framework
    target: str
    headings: list[Heading]
    answer_block: str
    section_roles: list[str]
    differentiation_angle: DifferentiationAngle
    internal_links: list[InternalLink]
    images_plan: list[ImagePlanItem]
    grounding: list[GroundedClaim]
    needs: list[str]
    word_count: int
    primary_density: float
    entities_covered: list[str]
    entities_missing: list[str]
    local_uniqueness: dict[str, float]
    notes: list[str]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_MD_SYNTAX_RE = re.compile(r"[#*`>\[\]()]|https?://\S+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _word_count(text: str) -> int:
    """Prose word count: strip markdown syntax + URLs, then count word tokens."""
    return len(_words(_MD_SYNTAX_RE.sub(" ", text)))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _bound_words(text: str, max_words: int) -> str:
    """Hard-bound ``text`` to ``max_words`` words (truncate). The per-section budget
    guarantee that mirrors the compactor's ``_enforce_budget`` - a runaway provider
    can never exceed the doctrine word budget (§10)."""
    tokens = text.split()
    if len(tokens) <= max_words:
        return text.strip()
    return " ".join(tokens[:max_words])


def _density(draft_md: str, primary: str) -> float:
    """Primary-keyword density as a 0-1 fraction (§3): occurrences of the primary
    phrase * its word length / total words."""
    total = _word_count(draft_md)
    if total == 0 or not primary.strip():
        return 0.0
    occurrences = len(re.findall(re.escape(primary), draft_md, re.IGNORECASE))
    primary_words = max(1, len(_words(primary)))
    return round(occurrences * primary_words / total, 4)


def _cap(text: str, max_chars: int) -> str:
    """Trim ``text`` to ``max_chars`` on a word boundary (titles / meta)."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return (cut or text[:max_chars]).rstrip(" ,.;:-")


def resolve_framework(page_type: str, framework: str) -> Framework:
    """Resolve the framework to use (doctrine §6): an explicit valid framework wins;
    ``Auto`` / anything unknown falls back to ``auto_framework(page_type)``
    (service->AIDA, local->BAB, blog->PAS)."""
    if framework in _FRAMEWORK_MOVES:
        return framework  # membership in the Framework-keyed table narrows it to a Framework
    return auto_framework(page_type)


def _per_city_uniqueness(city_bodies: Mapping[str, str]) -> dict[str, float]:
    """Per-city uniqueness ratio (§8): for each city, the fraction of its body's
    word set that appears in NO sibling city (1.0 when there is a single city)."""
    token_sets = {city: {w.lower() for w in _words(body)} for city, body in city_bodies.items()}
    out: dict[str, float] = {}
    for city, tokens in token_sets.items():
        if not tokens:
            out[city] = 0.0
            continue
        others: set[str] = set()
        for other_city, other_tokens in token_sets.items():
            if other_city != city:
                others |= other_tokens
        unique = tokens - others
        out[city] = round(len(unique) / len(tokens), 3)
    return out


class _Builder:
    """A mutable accumulator for the draft (the pure function's local workspace;
    frozen into :class:`GeneratedContent` at the end)."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.headings: list[Heading] = []
        self.grounding: list[GroundedClaim] = []
        self.needs: list[str] = []
        self.links: list[InternalLink] = []
        self.images: list[ImagePlanItem] = []
        self.section_roles: list[str] = []
        self.local_uniqueness: dict[str, float] = {}
        self.notes: list[str] = []
        self.answer: str = ""

    def h1(self, text: str) -> None:
        self.headings.append(Heading(level=1, text=text))
        self.parts.append(f"# {text}")

    def h2(self, text: str) -> None:
        self.headings.append(Heading(level=2, text=text))
        self.parts.append(f"## {text}")

    def h3(self, text: str) -> None:
        self.headings.append(Heading(level=3, text=text))
        self.parts.append(f"### {text}")

    def para(self, text: str) -> None:
        if text.strip():
            self.parts.append(text.strip())

    def bullets(self, items: Sequence[str]) -> None:
        rows = [f"- {item}" for item in items if item.strip()]
        if rows:
            self.parts.append("\n".join(rows))

    def ground(self, source: str, claim: str) -> None:
        if claim.strip():
            self.grounding.append(GroundedClaim(claim=claim.strip(), source=source))

    def need(self, what: str) -> None:
        self.needs.append(what)
        self.parts.append(f"[NEEDS: {what}]")

    def render(self) -> str:
        return "\n\n".join(self.parts) + "\n"


# --------------------------------------------------------------------------- #
# Writer-driven prose (the ONLY external touch; bounded + grounded)
# --------------------------------------------------------------------------- #
def _write(
    writer: Summarizer,
    model: str,
    *,
    heading: str,
    primary: str,
    intent: str,
    role: str,
    grounded: Sequence[tuple[str, str]],
    entities: Sequence[str],
    max_words: int,
) -> str:
    """Ask the writer for one section's prose from ONLY the grounded facts, then
    hard-bound it to ``max_words``. The writer phrases; it never sources."""
    lines = [
        f"Write the '{heading}' section of a {intent} web page about '{primary}'.",
        f"Copywriting move: {role}. Write helpful, people-first prose - no headings, no lists.",
    ]
    if grounded:
        lines.append("Use ONLY these verified facts; invent nothing else:")
        lines.extend(f"- {value}" for _label, value in grounded)
    else:
        lines.append("State no specific figures, names, prices, or claims you were not given.")
    if entities:
        lines.append("Naturally cover these topics: " + ", ".join(entities))
    prompt = "\n".join(lines)
    result = writer.summarize(prompt, model=model, max_tokens=max(1, max_words * 2))
    return _bound_words(result.text, max_words)


def _answer_block(
    writer: Summarizer,
    model: str,
    *,
    primary: str,
    question: str,
    intent: str,
    grounded: Sequence[tuple[str, str]],
    tuning: GeneratorTuning,
) -> str:
    """The 40-55-word extractable direct answer (§4). Bounded to the max; the
    primary is guaranteed present (front-loaded) so QA #6 has its anchor."""
    lines = [
        f"Answer this directly and self-containedly in {tuning.answer_min_words}-"
        f"{tuning.answer_max_words} words: {question}",
        f"Topic: '{primary}' ({intent}). No 'as mentioned above'; assume no prior context.",
    ]
    if grounded:
        lines.append("Ground it in: " + "; ".join(value for _label, value in grounded))
    result = writer.summarize("\n".join(lines), model=model, max_tokens=tuning.answer_max_words * 2)
    answer = _bound_words(result.text, tuning.answer_max_words)
    if primary.lower() not in answer.lower():
        lead = primary[:1].upper() + primary[1:]
        answer = _bound_words(f"{lead}: {answer}", tuning.answer_max_words)
    answer = answer.strip()
    if answer and answer[-1] not in ".!?":
        answer += "."
    return answer


# --------------------------------------------------------------------------- #
# Grounding selection + the differentiation angle
# --------------------------------------------------------------------------- #
def _facts_for_move(role: str, source_pack: SourcePack) -> list[tuple[str, str]]:
    """Deterministically route a slice of the source pack to each move so the
    grounded facts spread across the body (never all in one section)."""
    grounded: list[tuple[str, str]] = []
    if role in {"interest", "features", "useful", "picture", "attention", "before", "problem"}:
        for i, service in enumerate(source_pack.services[:3]):
            grounded.append((f"source_pack.services[{i}]", service))
        for key, value in list(source_pack.facts.items())[:3]:
            grounded.append((f"source_pack.facts.{key}", str(value)))
    if role in {"desire", "after", "benefits", "promise", "offer", "solution", "amplify"}:
        for i, proof in enumerate(source_pack.proof_points[:2]):
            grounded.append((f"source_pack.proof_points[{i}]", proof))
    if role in {"prove", "testimonial", "story", "unique", "bridge", "advantages"}:
        for i, quote in enumerate(source_pack.testimonials[:2]):
            grounded.append((f"source_pack.testimonials[{i}]", quote))
        for i, datum in enumerate(source_pack.unique_data[:2]):
            grounded.append((f"source_pack.unique_data[{i}]", datum))
    return grounded


def _resolve_angle(brief: ResearchBrief, source_pack: SourcePack) -> DifferentiationAngle:
    """Resolve the mandatory information-gain angle (§7), derived from the top-10
    teardown's differentiator entities, in the doctrine's priority order. If none
    of the four kinds can be grounded, the statement is a ``[NEEDS:]`` marker."""
    diffs = list(brief.teardown.differentiator_entities[:5])
    if source_pack.unique_data:
        return DifferentiationAngle(
            kind="unique_data",
            statement=f"Original data from {source_pack.client_name}: {source_pack.unique_data[0]}",
            grounded=True,
            derived_from=diffs,
        )
    if source_pack.proof_points:
        return DifferentiationAngle(
            kind="first_hand_experience",
            statement=f"First-hand experience: {source_pack.proof_points[0]}",
            grounded=True,
            derived_from=diffs,
        )
    if diffs:
        return DifferentiationAngle(
            kind="missed_angle",
            statement=f"A deeper, better-formatted take on {diffs[0]} that the top results underserve",
            grounded=True,
            derived_from=diffs,
        )
    return DifferentiationAngle(
        kind="missed_angle",
        statement="[NEEDS: unique data or first-hand experience to establish an information-gain angle]",
        grounded=False,
        derived_from=diffs,
    )


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _emit_context_grounding(builder: _Builder, context: GenerationContext | None) -> None:
    if context is None:
        return
    if context.stale:
        builder.notes.append("client context was stale at generation time")
    if context.summary:
        builder.ground("context.summary", context.summary)
    for key, value in context.facts.items():
        builder.ground(f"context.facts.{key}", str(value))


def _experience_block(
    builder: _Builder,
    writer: Summarizer,
    model: str,
    *,
    source_pack: SourcePack,
    primary: str,
    intent: str,
    max_words: int,
) -> None:
    """The E-E-A-T / Experience block (§2) - first-hand proof + testimonials, or a
    ``[NEEDS:]`` when a page carries zero first-hand signal."""
    client = source_pack.client_name
    builder.h2(f"Why choose {client}")
    grounded: list[tuple[str, str]] = []
    for i, proof in enumerate(source_pack.proof_points[:3]):
        grounded.append((f"source_pack.proof_points[{i}]", proof))
    for i, quote in enumerate(source_pack.testimonials[:2]):
        grounded.append((f"source_pack.testimonials[{i}]", quote))
    if not grounded:
        builder.need("first-hand experience / proof (real projects, results, or credentials)")
        return
    builder.para(
        _write(
            writer,
            model,
            heading=f"Why choose {client}",
            primary=primary,
            intent=intent,
            role="experience",
            grounded=grounded,
            entities=(),
            max_words=max_words,
        )
    )
    if source_pack.proof_points:
        builder.bullets(source_pack.proof_points[:3])
    for label, value in grounded:
        builder.ground(label, value)


def _local_anatomy(
    builder: _Builder,
    writer: Summarizer,
    model: str,
    *,
    brief: ResearchBrief,
    source_pack: SourcePack,
    primary: str,
    intent: str,
    max_words: int,
) -> None:
    """The white-hat local page anatomy (§8): locale intro, per-city sections with
    first-hand local proof + per-city uniqueness, NAP, and a GBP-alignment note."""
    geo = brief.geo or (source_pack.locations[0].city if source_pack.locations else None)
    builder.h2(f"{primary} in {geo}" if geo else f"Local {primary}")
    builder.para(
        _write(
            writer,
            model,
            heading="Locale intro",
            primary=primary,
            intent=intent,
            role="locale_intro",
            grounded=[("source_pack.client_name", source_pack.client_name)],
            entities=(),
            max_words=max_words,
        )
    )

    city_bodies: dict[str, str] = {}
    for location in source_pack.locations:
        heading = f"Serving {location.city}"
        builder.h2(heading)
        if not location.proof:
            builder.need(f"local proof for {location.city} (projects, landmarks, local clients)")
            city_bodies[location.city] = f"Serving {location.city}"
            continue
        grounded = [
            (f"source_pack.locations[{location.city}].proof[{i}]", proof)
            for i, proof in enumerate(location.proof)
        ]
        body = _write(
            writer,
            model,
            heading=heading,
            primary=primary,
            intent=intent,
            role="local_proof",
            grounded=grounded,
            entities=(),
            max_words=max_words,
        )
        builder.para(body)
        builder.bullets(location.proof)
        for label, value in grounded:
            builder.ground(label, value)
        # Uniqueness is measured over the city-specific grounded content (§8).
        city_bodies[location.city] = f"{heading} {body} " + " ".join(location.proof)

    if len(city_bodies) >= 1:
        builder.local_uniqueness = _per_city_uniqueness(city_bodies)

    nap = source_pack.nap or next((loc.nap for loc in source_pack.locations if loc.nap), None)
    builder.h2("Visit us")
    if nap is None:
        builder.need("NAP (business name, address, phone) - required for a local page")
    else:
        builder.para(f"**{nap.name}**  \n{nap.address}  \n{nap.phone}")
        builder.ground("source_pack.nap", f"{nap.name}, {nap.address}, {nap.phone}")
    builder.para(
        "This page must stay consistent with the Google Business Profile "
        "(categories, service area, and hours)."
    )


def _faq_block(
    builder: _Builder,
    writer: Summarizer,
    model: str,
    *,
    brief: ResearchBrief,
    primary: str,
    intent: str,
    tuning: GeneratorTuning,
    locale: str | None = None,
) -> None:
    """The Q&A block (§4) built from the brief's PAA + AI-Overview fan-out - the
    format snippets + AI Overviews lift. The key question is used by the answer
    block, so it is skipped here. For local pages ``locale`` localizes the
    questions (doctrine §8's localized FAQ)."""
    questions = [q for q in brief.fanout if q][1 : 1 + tuning.max_faq]
    if not questions:
        return
    builder.h2("Frequently asked questions")
    if locale:
        questions = [f"{q.rstrip('?')} in {locale}?" for q in questions]
    for question in questions:
        builder.h3(question)
        builder.para(
            _write(
                writer,
                model,
                heading=question,
                primary=primary,
                intent=intent,
                role="faq",
                grounded=(),
                entities=(),
                max_words=_FAQ_ANSWER_WORDS,
            )
        )


def _links_block(
    builder: _Builder, *, brief: ResearchBrief, source_pack: SourcePack, tuning: GeneratorTuning
) -> None:
    """Internal-link suggestions (§4): the keyword->URL registry first (real URLs),
    then cluster spokes mapped to their slug (pillar<->cluster topical map)."""
    seen: set[str] = set()
    for keyword, url in source_pack.internal_urls.items():
        if keyword.lower() in seen:
            continue
        seen.add(keyword.lower())
        builder.links.append(InternalLink(anchor=keyword, url=url, keyword=keyword))
    for spoke in brief.cluster.supporting[: tuning.max_internal_spokes]:
        if spoke.lower() in seen:
            continue
        seen.add(spoke.lower())
        builder.links.append(InternalLink(anchor=spoke, url=f"/{_slug(spoke)}", keyword=spoke))
    if not builder.links:
        return
    builder.h2("Related resources")
    builder.parts.append("\n".join(f"- [{link.anchor}]({link.url})" for link in builder.links))


def _plan_images(
    builder: _Builder, *, primary: str, client: str, moves: tuple[_Move, ...], tuning: GeneratorTuning
) -> None:
    """Plan a hero + one image per major section, each with authoritative alt text
    (§9), capped at ``max_images``."""
    builder.images.append(
        ImagePlanItem(
            slot="hero", prompt=f"Hero image for {primary} - {client}", alt=f"{primary} - {client}"
        )
    )
    for move in moves:
        if len(builder.images) >= tuning.max_images:
            break
        heading = move.heading.format(primary=primary, client=client)
        builder.images.append(
            ImagePlanItem(slot=f"section:{move.role}", prompt=f"Illustration for '{heading}'", alt=heading)
        )


def _title(primary: str, angle: DifferentiationAngle, client: str) -> str:
    """A front-loaded, primary-first title (§9), bounded to the char ceiling."""
    lead = primary[:1].upper() + primary[1:]
    suffix = client if client and client.lower() not in lead.lower() else "Expert Guide"
    return _cap(f"{lead} | {suffix}", TITLE_MAX_CHARS)


def _meta(primary: str, angle: DifferentiationAngle, client: str) -> str:
    """A grounded meta description (§9): primary + the differentiation hook + a CTA,
    bounded. Never states an invented claim - the hook is the resolved angle."""
    hook = angle.statement if angle.grounded else f"Discover what makes {client} different"
    return _cap(f"{primary[:1].upper()}{primary[1:]}: {hook}. Get started with {client} today.", META_MAX_CHARS)


def _coverage(draft_md: str, entities: Sequence[str]) -> tuple[list[str], list[str]]:
    low = draft_md.lower()
    covered = [e for e in entities if e.lower() in low]
    missing = [e for e in entities if e.lower() not in low]
    return covered, missing


# --------------------------------------------------------------------------- #
# The orchestrator
# --------------------------------------------------------------------------- #
def generate(
    brief: ResearchBrief,
    source_pack: SourcePack,
    context: GenerationContext | None,
    *,
    page_type: str,
    framework: str = "Auto",
    target: str = "WordPress",
    writer: Summarizer,
    model: str = _DEFAULT_MODEL,
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> GeneratedContent:
    """Turn a research ``brief`` + ``source_pack`` + fresh ``context`` into a
    ranking-grade, grounded, extractable draft (see the module + doctrine).

    Deterministic given a deterministic ``writer``. The core injects all structure,
    facts, and the grounding trace; the writer only phrases; a missing required fact
    becomes a ``[NEEDS:]`` placeholder rather than a hallucination.
    """
    primary = brief.terms.primary.strip() or brief.keyword.strip()
    client = source_pack.client_name.strip() or "our team"
    intent = brief.intent
    resolved_fw = resolve_framework(page_type, framework)
    moves = _FRAMEWORK_MOVES[resolved_fw]

    # Word budget (§10): match/beat the teardown, clamped, reserving scaffold room.
    raw_target = tuning.word_count_target or brief.teardown.word_count_target or _DEFAULT_TARGET_WORDS
    content_budget = _clamp(raw_target, tuning.word_count_floor, tuning.word_count_ceiling)
    content_budget = max(tuning.word_count_floor, content_budget - _SCAFFOLD_RESERVE_WORDS)
    n_units = len(moves) + 2 + max(1, len(source_pack.locations))  # moves + diff + experience + local
    per_section = max(_MIN_SECTION_WORDS, content_budget // max(1, n_units))

    builder = _Builder()
    _emit_context_grounding(builder, context)

    angle = _resolve_angle(brief, source_pack)
    if not angle.grounded:
        builder.needs.append("unique data or first-hand experience for the differentiation angle")

    title = _title(primary, angle, client)
    meta = _meta(primary, angle, client)

    # A. One H1 (§4) + a grounded intro.
    builder.h1(title)
    builder.ground("source_pack.client_name", client)
    intro_grounded: list[tuple[str, str]] = []
    if context is not None and context.summary:
        intro_grounded.append(("context.summary", context.summary))
    builder.para(
        _write(
            writer,
            model,
            heading="Introduction",
            primary=primary,
            intent=intent,
            role="intro",
            grounded=intro_grounded,
            entities=brief.cluster.supporting[:3],
            max_words=int(per_section * _INTRO_WORD_FRACTION),
        )
    )

    # B. Key heading + the 40-55-word extractable answer block (§4).
    key_question = next((q for q in brief.fanout if q), f"What is {primary}?")
    builder.h2(key_question)
    answer = _answer_block(
        writer,
        model,
        primary=primary,
        question=key_question,
        intent=intent,
        grounded=[(f"source_pack.facts.{k}", str(v)) for k, v in list(source_pack.facts.items())[:2]],
        tuning=tuning,
    )
    builder.answer = answer
    builder.para(answer)

    # Entity-coverage checklist from the teardown's table-stakes entities (§3).
    coverage_entities = list(brief.teardown.table_stakes_entities[: tuning.max_coverage_entities])
    if coverage_entities:
        builder.h2(f"What a complete answer to {primary} covers")
        builder.bullets(coverage_entities)
        builder.ground("teardown.table_stakes_entities", "; ".join(coverage_entities))

    # C. Framework moves (§6) - each grounded + covering relevant subtopics.
    spokes = list(brief.cluster.supporting)
    for index, move in enumerate(moves):
        builder.section_roles.append(move.role)
        heading = move.heading.format(primary=primary, client=client)
        builder.h2(heading)
        grounded = _facts_for_move(move.role, source_pack)
        section_entities = spokes[index : index + 2]
        builder.para(
            _write(
                writer,
                model,
                heading=heading,
                primary=primary,
                intent=intent,
                role=move.role,
                grounded=grounded,
                entities=section_entities,
                max_words=per_section,
            )
        )
        for label, value in grounded:
            builder.ground(label, value)

    # D. The mandatory differentiation angle section (§7).
    builder.h2("What makes this different")
    if angle.grounded:
        builder.para(
            _write(
                writer,
                model,
                heading="What makes this different",
                primary=primary,
                intent=intent,
                role="differentiation",
                grounded=[("differentiation.angle", angle.statement)],
                entities=angle.derived_from[:2],
                max_words=per_section,
            )
        )
        builder.ground("differentiation.angle", angle.statement)
    else:
        builder.need("unique data or first-hand experience to establish an information-gain angle")

    # E. E-E-A-T / Experience (§2).
    _experience_block(
        builder, writer, model, source_pack=source_pack, primary=primary, intent=intent,
        max_words=per_section,
    )

    # F. White-hat local anatomy (§8) - local pages only.
    if page_type == "local":
        _local_anatomy(
            builder, writer, model, brief=brief, source_pack=source_pack, primary=primary,
            intent=intent, max_words=per_section,
        )

    # G. Q&A / FAQ (§4); localized for local pages (§8).
    _faq_block(
        builder, writer, model, brief=brief, primary=primary, intent=intent, tuning=tuning,
        locale=brief.geo if page_type == "local" else None,
    )

    # H. Internal links (§4).
    _links_block(builder, brief=brief, source_pack=source_pack, tuning=tuning)

    # I. Conclusion / CTA.
    builder.h2(f"Ready to move forward with {primary}?")
    builder.para(
        _write(
            writer,
            model,
            heading="Conclusion",
            primary=primary,
            intent=intent,
            role="conclusion",
            grounded=[("source_pack.client_name", client)],
            entities=(),
            max_words=max(_MIN_SECTION_WORDS, per_section // 2),
        )
    )

    _plan_images(builder, primary=primary, client=client, moves=moves, tuning=tuning)

    draft_md = builder.render()
    word_count = _word_count(draft_md)
    density = _density(draft_md, primary)
    covered, missing = _coverage(draft_md, brief.teardown.table_stakes_entities)

    if density > PRIMARY_DENSITY_HARD_CEILING:
        builder.notes.append(f"primary density {density:.3f} exceeds the {PRIMARY_DENSITY_HARD_CEILING} ceiling")
    if word_count < tuning.word_count_floor:
        builder.notes.append(f"thin draft: {word_count} words below the {tuning.word_count_floor} floor")
    if brief.low_confidence:
        builder.notes.append("research brief was low-confidence")

    return GeneratedContent(
        title=title,
        meta_description=meta,
        draft_md=draft_md,
        page_type=page_type,
        framework=resolved_fw,
        target=target,
        headings=builder.headings,
        answer_block=builder.answer,
        section_roles=builder.section_roles,
        differentiation_angle=angle,
        internal_links=builder.links,
        images_plan=builder.images,
        grounding=builder.grounding,
        needs=builder.needs,
        word_count=word_count,
        primary_density=density,
        entities_covered=covered,
        entities_missing=missing,
        local_uniqueness=builder.local_uniqueness,
        notes=builder.notes,
    )
