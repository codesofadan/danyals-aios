"""Shared shape for the post-draft repair stages (P3).

CONVERT and VOICE both do the same three things, and both of v1's equivalents got all
three wrong:

1. MEASURE FIRST, AND SPEND NOTHING IF THE DRAFT IS ALREADY CLEAN. A stage that always
   calls is a stage that always bills. These linters are stdlib and run in microseconds,
   so the check that decides whether to spend costs nothing. On a good draft the whole
   stage is free.

2. REPAIR WHAT WAS MEASURED, BY NAME. Blind self-critique ("improve this page") is how
   a model rewrites prose that was fine and drops facts on the way through. The prompt
   carries the linter's own findings - code, line, message - so the call has somewhere
   specific to go.

3. VERIFY THE REPAIR, AND KEEP THE ORIGINAL IF IT LOST. Nothing guarantees a rewrite is
   better; a self-repair loop that assumes it is will happily walk a page downhill one
   confident pass at a time. Re-lint, compare, and if the repair did not reduce the
   finding count, discard it and say so. The spend is real either way and is recorded
   either way - a paid-for repair that lost is not free.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.services.content_generator import _MAX_TOKENS_PER_WORD
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.draft import THINKING_ALLOWANCE
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

# A repair returns the WHOLE document, not a fragment, so the budget is the draft's own
# length - not a section's. Under-budgeting here truncates the page mid-repair, which is
# strictly worse than the defect being repaired.
MIN_REPAIR_WORDS = 200


@dataclass(frozen=True)
class Finding:
    """One thing a linter objected to, in a form a prompt can act on."""

    code: str
    line: int
    message: str

    def render(self) -> str:
        where = f"line {self.line}" if self.line else "the page as a whole"
        return f"  - [{self.code}] {where}: {self.message}"


def run_repair_stage(
    ctx: PipelineContext,
    *,
    stage: str,
    writer: DoctrineWriter,
    measure: Callable[[str], Sequence[Finding]],
    instruction: str,
    model: str | None = None,
) -> StageResult:
    """Measure the draft, repair only what was found, and keep the better version.

    ``measure`` is the linter adapter: draft text in, findings out. It is called twice -
    once to decide whether to spend, once to judge whether the spend helped.
    """
    accounting = WriteAccounting()

    if not ctx.draft_md.strip():
        return ctx.record(StageResult(
            stage, outcome="skipped", notes=("no draft to work on",),
        ))

    before = tuple(measure(ctx.draft_md))
    if not before:
        # The whole point of measuring first. No finding, no call, no bill.
        return ctx.record(StageResult(
            stage, outcome="skipped", data={"findings_before": 0},
            notes=("draft already passes this check; no repair call made",),
        ))

    words = max(MIN_REPAIR_WORDS, len(ctx.draft_md.split()))
    prompt = "\n".join((
        instruction,
        "",
        "What the check found - fix EXACTLY these, and change nothing else:",
        *(f.render() for f in before),
        "",
        "Rules for the rewrite:",
        "  - Do not add a fact, number, name, date or claim that is not already in the "
        "draft. A repair that invents evidence is worse than the defect it fixes.",
        "  - Do not drop a heading, and do not renumber or reorder sections.",
        "  - Leave prose that was not flagged alone. This is a repair, not a rewrite.",
        "",
        "Return the COMPLETE corrected page in markdown. No preamble, no commentary.",
        "",
        "--- THE DRAFT ---",
        ctx.draft_md,
    ))

    try:
        repaired = writer.write(
            stage, prompt,
            page_type=ctx.page_type, vertical=ctx.vertical or None,
            framework=ctx.framework,
            max_tokens=THINKING_ALLOWANCE + max(1, round(words * _MAX_TOKENS_PER_WORD)),
            expected_calls=1, model=model, accounting=accounting,
        )
    except Exception as exc:
        return ctx.record(StageResult(
            stage, outcome="degraded",
            data={"findings_before": len(before)},
            notes=(f"repair unavailable ({type(exc).__name__}); draft left as written",),
            cost=accounting.cost, llm_calls=accounting.calls,
            input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
            cache_write_tokens=accounting.cache_write_tokens,
            cache_read_tokens=accounting.cache_read_tokens,
            chunk_ids=tuple(accounting.chunk_ids),
        ))

    def _result(outcome: str, after: int, notes: tuple[str, ...]) -> StageResult:
        return ctx.record(StageResult(
            stage, outcome=outcome,  # type: ignore[arg-type]
            data={"findings_before": len(before), "findings_after": after},
            notes=notes,
            cost=accounting.cost, llm_calls=accounting.calls,
            input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
            cache_write_tokens=accounting.cache_write_tokens,
            cache_read_tokens=accounting.cache_read_tokens,
            chunk_ids=tuple(accounting.chunk_ids),
        ))

    if not repaired.strip():
        return _result("degraded", len(before), (
            "repair returned nothing; draft left as written",))

    after = tuple(measure(repaired))
    if len(after) >= len(before):
        # Point 3. The spend happened and is recorded; the OUTPUT is discarded.
        return _result("degraded", len(after), (
            f"repair did not help ({len(before)} findings -> {len(after)}); "
            "original draft kept",))

    ctx.draft_md = repaired
    return _result("ok", len(after), (
        f"{len(before)} findings -> {len(after)}",))
