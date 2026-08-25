"""VOICE - deterministic detection, targeted repair (P3, stage 8).

NEVER blind self-critique. "Read this back and improve the voice" is the prompt that
launders a good page into a blander one: the model has no fixed target, so it rewrites
whatever it happens to notice and reports success either way.

Everything repaired here is MEASURED first, by a ported validator:

  - blocklist hits    `blocklist_lint.py`     Tier-1 doctrine phrases, quoted exactly
  - filler ratio      `voice_fingerprint.py`  padding as a share of the page
  - monotone rhythm   `voice_fingerprint.py`  sentence lengths with no variation
  - grade band        `readability_scorer.py` the 6-9 band, BOTH sides

That last one is a backstop for a failure this pipeline has produced in both directions.
The draft prompt carries the constraint, but a prompt is a request; measuring the result
is the guarantee. First draft of the San Jose page came back at grade 12.6; the fix for
it, before the constraint had a floor, came back at 5.0.
"""

from __future__ import annotations

from app.services.content_lint import (
    MAX_FILLER_RATIO,
    MAX_GRADE,
    MIN_GRADE,
    analyse_readability,
    fingerprint_voice,
    lint_blocklist,
    strip_markdown,
)
from app.services.content_lint.blocklist import BlocklistHit
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.repair import Finding, run_repair_stage
from app.services.content_pipeline.writer import DoctrineWriter

STAGE = "voice"

# Sentence-length spread below this reads as a checklist rather than prose. A page can
# sit inside the grade band and still be unreadable if every sentence is the same
# length, which is exactly what "keep sentences short" produces when taken literally.
MIN_SENTENCE_STDEV = 4.0

# Below this there is not enough text for a rhythm statistic to mean anything.
MIN_SENTENCES_FOR_RHYTHM = 8

# How many line numbers to spell out before summarising the rest as a count.
_MAX_LINES_NAMED = 6

_INSTRUCTION = (
    "Repair the voice problems listed below. Keep the page's structure, its facts and "
    "its length; change only what the check objected to.\n"
    "Local-service prose earns trust by being specific and plain: concrete nouns, "
    "varied sentence length, no throat-clearing before the point."
)


def _measure(text: str) -> tuple[Finding, ...]:
    out: list[Finding] = []

    # Grouped by PHRASE, not listed per occurrence. One banned phrase used 24 times is
    # one instruction; emitting it 24 times inflates the repair prompt with 24 near
    # identical lines, and every one of those tokens is billed on a call whose whole
    # purpose is to remove them.
    grouped: dict[str, list[BlocklistHit]] = {}
    for hit in lint_blocklist(text).hits:
        grouped.setdefault(hit.display.lower(), []).append(hit)
    for hits in grouped.values():
        first = hits[0]
        distinct = sorted({h.line for h in hits})
        lines = ", ".join(str(n) for n in distinct[:_MAX_LINES_NAMED])
        if len(distinct) > _MAX_LINES_NAMED:
            lines += f", and {len(distinct) - _MAX_LINES_NAMED} more"
        out.append(Finding(
            code="BLOCKLIST", line=first.line,
            message=(
                f"{first.display!r} is a {first.tier} blocklisted phrase "
                f"({first.category}), used {len(hits)}x (lines {lines}). Replace EVERY "
                "occurrence with the specific thing it stands in for - do not swap in "
                "a synonym for the same empty claim."
            ),
        ))

    prose = strip_markdown(text)
    fp = fingerprint_voice(prose)
    if fp.filler_ratio > MAX_FILLER_RATIO:
        out.append(Finding(
            code="FILLER", line=0,
            message=(
                f"filler is {fp.filler_ratio:.1%} of the page against a "
                f"{MAX_FILLER_RATIO:.0%} ceiling ({fp.filler_word_hits} words, "
                f"{fp.filler_phrase_hits} phrases). Cut the padding; do not replace it."
            ),
        ))
    if fp.sentences >= MIN_SENTENCES_FOR_RHYTHM and fp.sentence_len_stdev < MIN_SENTENCE_STDEV:
        out.append(Finding(
            code="MONOTONE", line=0,
            message=(
                f"sentence length barely varies (stdev {fp.sentence_len_stdev:.1f}, "
                f"mean {fp.avg_sentence_len:.1f}). Combine some neighbouring sentences "
                "and let others stay short. Do not simply lengthen everything."
            ),
        ))

    rd = analyse_readability(prose)
    if rd.fk_grade > MAX_GRADE:
        out.append(Finding(
            code="GRADE_HIGH", line=0,
            message=(
                f"reading grade {rd.fk_grade:.1f} is above the {MAX_GRADE:.0f} ceiling "
                f"({rd.long_sentences} sentences over the long threshold). Split the "
                "longest sentences and prefer shorter words."
            ),
        ))
    elif rd.fk_grade < MIN_GRADE:
        out.append(Finding(
            code="GRADE_LOW", line=0,
            message=(
                f"reading grade {rd.fk_grade:.1f} is BELOW the {MIN_GRADE:.0f} floor - "
                "the page reads as a checklist. Join related short sentences into "
                "fuller ones. Do not add words purely to raise the score."
            ),
        ))
    return tuple(out)


def run_voice(
    ctx: PipelineContext, *, writer: DoctrineWriter, model: str | None = None
) -> StageResult:
    """Fix what the voice and readability checks measured, or spend nothing."""
    return run_repair_stage(
        ctx, stage=STAGE, writer=writer, measure=_measure,
        instruction=_INSTRUCTION, model=model,
    )
