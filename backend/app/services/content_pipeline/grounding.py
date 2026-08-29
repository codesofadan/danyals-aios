"""Every figure on the page traceable to something the client actually supplied.

MEASURED, NOT SUSPECTED. On the first three paid runs the writer used every fact
it was given - and invented eight more figures alongside them: gallon counts,
dollar amounts, job totals that appeared in no source. The QA gate caught it
every time (fact_grounding 40/100, a hard block), which is the gate working; but
catching it at the end only tells an operator the page failed. Nothing tried to
FIX it, so every page arrived needing a human to hunt for invented numbers.

The draft prompt already says, in terms, that the supplied facts are the only
ones the page may state. The model agrees and then does it anyway. So this is a
deterministic check plus a targeted repair, in the shape the convert and voice
stages already use: measure for free, spend only when there is something to fix,
and keep the original if the repair did not improve it.

WHAT COUNTS AS A CLAIM IS NOT THIS MODULE'S OPINION. It is `content_qa`'s, via
`concrete_claim_digits` - the exact function the gate audits with. That sharing is
the whole point: the first version of this stage used its own, narrower rule
(skip bare integers under 100, to avoid mangling prose), and a measured run showed
the consequence - the repair passed its own check while the gate still blocked on
"24", "50" and "90". A repair that measures less than the gate can never satisfy
it. One definition, both users.

A bare year is not a claim (the gate exempts it), so "in 2025" is left alone.
"""

from __future__ import annotations

import re

from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.repair import Finding, run_repair_stage
from app.services.content_pipeline.writer import DoctrineWriter
from app.services.content_qa import concrete_claim_digits

STAGE = "grounding"

#: Used only to point the operator at WHERE a flagged figure sits. What counts as
#: a claim comes from `concrete_claim_digits`; this just finds it in the text.
_FIGURE = re.compile(
    r"""
    (?P<money>[$£€]\s?\d(?:[\d,]*\d)?(?:\.\d+)?)  # $2,400 (not the comma after it)
    | (?P<pct>\d[\d,]*(?:\.\d+)?\s?%)          # 44%
    | (?P<num>\b\d[\d,]*(?:\.\d+)?\b)          # 10,000 · 4.8 · 412 · 24
    """,
    re.VERBOSE,
)

_INSTRUCTION = (
    "Every figure below appears on the page but in NONE of the supplied facts, so "
    "the page cannot support it.\n"
    "For each one, do exactly ONE of these, and nothing else:\n"
    "  - cut the figure and keep the sentence working without it, or\n"
    "  - replace it with a supplied fact that makes the same point, or\n"
    "  - if the sentence exists only to carry that figure, cut the sentence.\n"
    "Do NOT invent a source, do NOT hedge it ('roughly', 'up to'), and do NOT "
    "swap one invented number for another. A hedged invention is still an "
    "invention. Leave every other sentence exactly as it is."
)


def _digits(text: str) -> str:
    """The comparable core of a figure: digits and decimal points only."""
    return re.sub(r"[^\d.]", "", text).strip(".")


def supplied_figures(facts: tuple[str, ...]) -> set[str]:
    """Every figure the client actually gave us, in comparable form."""
    out: set[str] = set()
    for fact in facts:
        for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", fact):
            core = _digits(raw)
            if core:
                out.add(core)
    return out


def unsourced_figures(text: str, facts: tuple[str, ...]) -> tuple[Finding, ...]:
    """Concrete numeric claims in ``text`` that no supplied fact accounts for.

    The audit set is the GATE's (`concrete_claim_digits`); this function's job is
    to locate each one in the prose so the repair prompt can name a line.
    """
    supplied = supplied_figures(facts)
    audited = set(concrete_claim_digits(text))
    seen: set[str] = set()
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _FIGURE.finditer(line):
            raw = match.group(0).strip()
            core = _digits(raw)
            if not core or core in supplied or raw in seen:
                continue
            # Only what the gate would audit. A bare year, for one, is a temporal
            # reference rather than a quantity claim, and the gate exempts it.
            if core not in audited:
                continue
            # A figure that is PART of a supplied one (a licence number, a phone)
            # is sourced: "41982" inside "M-41982".
            if any(core in s or s in core for s in supplied if len(s) >= len(core)):
                continue
            seen.add(raw)
            findings.append(Finding(
                code="UNSOURCED_FIGURE", line=line_no,
                message=f"'{raw}' is stated as fact but appears in no supplied fact",
            ))
    return tuple(findings)


def run_grounding(
    ctx: PipelineContext, *, writer: DoctrineWriter, model: str | None = None
) -> StageResult:
    """Cut or re-source every figure the supplied facts cannot support."""
    facts = tuple(ctx.facts)
    if not facts:
        # With nothing supplied, EVERY figure is unsourced and a repair would gut
        # the page. That is a grounding failure upstream, not something to fix here.
        return ctx.record(StageResult(
            STAGE, outcome="skipped",
            notes=("no supplied facts to check figures against",),
        ))
    return run_repair_stage(
        ctx, stage=STAGE, writer=writer,
        measure=lambda text: unsourced_figures(text, facts),
        instruction=_INSTRUCTION, model=model,
    )
