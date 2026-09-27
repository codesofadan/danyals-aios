"""Short-form composer: the placements the article generator structurally cannot serve.

WHY THIS EXISTS RATHER THAN A SMALLER ARTICLE. ``content_generator`` clamps its word
budget to a **600-word floor** (``WORD_COUNT_FLOOR``), and that floor is correct for what
it is: a ranking-grade page builder that assembles a framework skeleton, a
differentiation angle, an FAQ block and a local-proof section. Ask it for 29 words and it
returns 600 anyway - then ``BlueskyClient`` publishes ``text[:300]``.

So the 300-character placement was never a shrunken article. It is a different artifact,
and pretending otherwise produced the defect ``platform_spec`` documents: a blog post cut
mid-sentence with the editorial backlink - the entire reason the property exists - sliced
off the end.

WHAT THIS GUARANTEES THAT TRUNCATION CANNOT.

* The note is composed to fit, so nothing is cut. Where the model overruns anyway, it is
  trimmed at a SENTENCE boundary, never mid-word.
* The link is never in the body. Every adapter for these platforms appends
  ``anchor: url`` after the text and truncates the whole string, so a body that fills the
  budget is a body that deletes the link. The budget here already reserves room for it
  (``platform_spec.LINK_RESERVE_CHARS``), and the prompt forbids writing one.
* ``[NEEDS:]`` discipline is unchanged. A note that needs a fact nobody supplied says so
  and holds at review, exactly as an article does - a 200-character placement is a
  smaller lie, not a permissible one.

DEGRADES WITHOUT A ROUTER, like every other provider seam here: a deterministic note
built from the source pack, carrying an explicit ``[NEEDS:]`` when the pack is empty, so
a keyless deployment holds the placement for a human instead of publishing nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.logging_setup import get_logger
from app.modules.web2.platform_spec import PlatformSpec
from app.platform.ai.prompts import get as get_prompt
from app.platform.ai.router import CostBlockedError, ModelRequest, ModelRouter
from app.platform.ai.tiers import TaskTier
from app.services.content_generator import SourcePack

logger = get_logger("modules.web2.note_composer")

NEEDS_MARKER = "[NEEDS:"

#: Sentence-ending punctuation followed by whitespace. Used to trim at a boundary rather
#: than mid-word - the difference between a short post and a visibly severed one.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

#: Formatting the prompt forbids and the platform would render as literal characters or
#: silently drop. Stripped rather than trusted: a model that emits a markdown heading
#: into a plain-text feed post produces "## Why drains block" on the page.
_MARKDOWN_NOISE = re.compile(r"^\s{0,3}(#{1,6}\s+|[-*+]\s+|>\s+|\d+\.\s+)", re.MULTILINE)


@dataclass(frozen=True)
class Note:
    """One composed short-form placement."""

    text: str
    platform: str
    char_count: int
    #: False when a ``[NEEDS:]`` gap remains - such a note HOLDS at review, exactly as a
    #: gappy article does.
    publishable: bool
    #: True when the model overran the budget and the text was trimmed at a sentence
    #: boundary. Recorded rather than hidden: a note that needed trimming is a signal the
    #: budget or the prompt is wrong for this platform.
    trimmed: bool = False
    spent_usd: float = 0.0
    degraded: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


def compose(
    *,
    spec: PlatformSpec,
    topic: str,
    client_name: str,
    geo: str | None,
    source_pack: SourcePack | None,
    router: ModelRouter | None,
    module: str = "web2",
    feature_key: str = "content",
    client_id: str | None = None,
    job_id: str = "",
) -> Note:
    """Compose one short-form placement inside ``spec``'s character budget.

    Never raises for a cost block - it returns a degraded note and lets the caller HOLD
    the placement, mirroring how the article path treats ``ContentSpendBlocked``.
    """
    budget = _budget(spec)
    facts = _facts_block(source_pack, client_name)

    if router is None or not router.configured:
        return _degraded(spec, topic, client_name, budget, "no model backend configured")

    prompt = get_prompt("web2/note_body")
    try:
        result = router.complete(
            ModelRequest(
                task=TaskTier.DRAFTING,
                prompt=prompt.render(
                    client_name=client_name,
                    platform=spec.platform,
                    platform_shape=spec.describe(),
                    topic=topic,
                    geo=geo or "not specified",
                    max_chars=budget,
                    facts=facts,
                ),
                # A note is a few hundred characters; asking for an article's budget
                # would price it like one at the cost gate.
                expected_output_tokens=max(120, budget // 3),
                module=module,
                client_id=client_id,
                client_name=client_name,
                job_id=job_id,
                job_type=module,
                feature_key=feature_key,
                prompt_id=prompt.id,
            )
        )
    except CostBlockedError as blocked:
        return _degraded(spec, topic, client_name, budget, f"spend_blocked:{blocked.outcome}")

    text, trimmed = _fit(_clean(result.text), budget)
    publishable = NEEDS_MARKER not in text and bool(text.strip())
    if trimmed:
        logger.info(
            "web2_note_trimmed", platform=spec.platform, budget=budget, job_id=job_id
        )
    return Note(
        text=text,
        platform=spec.platform,
        char_count=len(text),
        publishable=publishable,
        trimmed=trimmed,
        spent_usd=result.cost_usd,
        degraded=result.degraded,
        notes=[f"short-form note composed for {spec.platform} (budget {budget} chars)"],
    )


def _budget(spec: PlatformSpec) -> int:
    """The characters the BODY may use.

    Reserves room for the link the adapter appends afterwards. Without that reserve a
    note that exactly fills the platform's ceiling publishes with the backlink truncated
    away - a placement that cost a model call and carries nothing.
    """
    from app.modules.web2.platform_spec import LINK_RESERVE_CHARS

    ceiling = spec.max_body_chars
    if ceiling is None:
        # A snippet host with no measured ceiling still wants a short, plain document
        # rather than a 900-word article rendered to text.
        return 1200
    return max(ceiling - LINK_RESERVE_CHARS, 80)


def _clean(text: str) -> str:
    """Strip markup the platform would show literally or silently drop."""
    stripped = _MARKDOWN_NOISE.sub("", text.strip())
    # Collapse the blank-line paragraphs an article-shaped model habitually produces;
    # a feed post is one block.
    return re.sub(r"\n{2,}", "\n", stripped).strip()


def _fit(text: str, budget: int) -> tuple[str, bool]:
    """Return ``text`` within ``budget``, trimmed at a SENTENCE boundary if it overruns.

    Mid-word truncation is what the adapters already do and what this module exists to
    stop; a note cut at a full stop reads as short, one cut at ``"emergency drain unbl"``
    reads as broken.
    """
    if len(text) <= budget:
        return text, False
    kept: list[str] = []
    used = 0
    for sentence in _SENTENCE_END.split(text):
        candidate = used + len(sentence) + (1 if kept else 0)
        if candidate > budget:
            break
        kept.append(sentence)
        used = candidate
    if kept:
        return " ".join(kept).strip(), True
    # A single sentence longer than the whole budget: fall back to a word boundary,
    # which is still never mid-word.
    clipped = text[:budget].rsplit(" ", 1)[0].rstrip(",;:- ")
    return clipped, True


def _facts_block(pack: SourcePack | None, client_name: str) -> str:
    """The grounding facts, or an explicit statement that there are none.

    "No verified facts" is deliberately spelled out rather than left blank: an empty
    section reads to a model as an omission it may helpfully fill, which is exactly the
    hallucination the ``[NEEDS:]`` discipline exists to prevent.
    """
    if pack is None:
        return (
            f"No verified facts are available for {client_name}. Write only what is true "
            "of any business of this kind, and mark anything specific as [NEEDS: ...]."
        )
    lines: list[str] = [f"Business name: {pack.client_name or client_name}"]
    # The SourcePack's REAL fields, named explicitly rather than swept with getattr: a
    # typo'd attribute name would contribute nothing and fail silently, and the result -
    # a note that says less than it could while looking perfectly correct - is the kind
    # of defect that never gets reported because nothing appears broken.
    for values, label in (
        (pack.services, "Services"),
        (pack.proof_points, "First-hand proof"),
        (pack.unique_data, "Data we own"),
        (pack.testimonials, "Client testimonials"),
    ):
        if values:
            lines.append(f"{label}: " + "; ".join(str(v) for v in values))
    for key, value in sorted(pack.facts.items()):
        if value:
            lines.append(f"{key}: {value}")
    if pack.nap is not None:
        lines.append(f"Name/address/phone: {pack.nap}")
    if pack.locations:
        lines.append(
            "Locations: "
            + ", ".join(str(getattr(loc, "city", "") or loc) for loc in pack.locations)
        )
    if len(lines) == 1:
        lines.append("No further verified facts. Mark anything specific as [NEEDS: ...].")
    return "\n".join(lines)


def _degraded(
    spec: PlatformSpec, topic: str, client_name: str, budget: int, reason: str
) -> Note:
    """A deterministic, network-free placeholder that HOLDS at review.

    Carries an explicit ``[NEEDS:]`` so it can never be mistaken for a publishable note -
    ``publishable`` is False and the review gate refuses it, which is the same treatment
    a gappy article gets.
    """
    text = (
        f"{topic} - {client_name}. "
        f"[NEEDS: the note body; {reason}]"
    )[:budget]
    return Note(
        text=text,
        platform=spec.platform,
        char_count=len(text),
        publishable=False,
        spent_usd=0.0,
        notes=[f"degraded short-form note: {reason}"],
    )
