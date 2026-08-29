"""What a lead asked for, applied to the page they asked about.

THE HOLE THIS FILLS, reproduced through the real API before it was written: a
lead opens a drafted page, clicks "Request edits" and types what they want
changed. The row moves to `drafting`, the instruction is saved, and the pipeline
is re-enqueued. This engine then returned `noop - job is drafting, not queued`
and the page sat at "Edit requested" FOREVER. The instruction was stored and
nothing ever read it; the reviewer's only feedback channel was a dead end.

The v1 generator has an equivalent (`content_guard.apply_edit_instruction`), but
it is built around v1's writer interface and its `GeneratedContent` shape. This
is the same job in this package's idiom: one stage, its own doctrine, working on
`ctx.draft_md`.

AN EDIT IS NOT A REDRAFT. Re-running research, outline and draft would throw away
the page the lead just read and replace it with a different one - which is not
what "cut the second section" means, and would spend a full page's budget to
ignore the request. So the edit path reuses the STORED draft and runs only the
checks that must see the change (`runner.EDIT_STAGES`).
"""

from __future__ import annotations

from app.services.content_generator import _MAX_TOKENS_PER_WORD
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.draft import THINKING_ALLOWANCE
from app.services.content_pipeline.repair import MIN_REPAIR_WORDS
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

STAGE = "guided_edit"

#: A revision that comes back a fraction of the original is a truncation or a
#: refusal, not an edit. Keeping it would silently delete most of the page.
_MIN_KEPT_RATIO = 0.5


def run_guided_edit(
    ctx: PipelineContext,
    *,
    writer: DoctrineWriter,
    instruction: str,
    model: str | None = None,
) -> StageResult:
    """Apply one reviewer instruction to the existing draft, or keep the original."""
    accounting = WriteAccounting()
    asked = instruction.strip()

    if not ctx.draft_md.strip():
        return ctx.record(StageResult(
            STAGE, outcome="skipped", notes=("no draft to edit",),
        ))
    if not asked:
        # The reviewer may send "request edits" with no note. That is a rejection
        # back to drafting, not an instruction, and guessing at what they meant is
        # exactly how a page comes back changed in ways nobody asked for.
        return ctx.record(StageResult(
            STAGE, outcome="skipped",
            notes=("edits were requested with no instruction; draft left as written",),
        ))

    words = max(MIN_REPAIR_WORDS, len(ctx.draft_md.split()))
    prompt = "\n".join((
        "A reviewer has read this page and asked for one specific change.",
        "",
        "WHAT THEY ASKED FOR:",
        f"  {asked}",
        "",
        "Rules:",
        "  - Do exactly what was asked, and nothing else. Every other sentence stays "
        "as it is, word for word.",
        "  - Do not add a fact, number, name, date or claim that is not already in "
        "the draft. If the request needs a fact nobody supplied, make the change "
        "without it rather than inventing one.",
        "  - Keep the heading structure unless the request is explicitly about it.",
        "  - Do not 'improve' prose you were not asked to touch.",
        "",
        "Return the COMPLETE page in markdown. No preamble, no commentary, no note "
        "about what you changed.",
        "",
        "--- THE PAGE ---",
        ctx.draft_md,
    ))

    try:
        revised = writer.write(
            STAGE, prompt,
            page_type=ctx.page_type, vertical=ctx.vertical or None,
            framework=ctx.framework,
            max_tokens=THINKING_ALLOWANCE + max(1, round(words * _MAX_TOKENS_PER_WORD)),
            expected_calls=1, model=model, accounting=accounting,
        )
    except Exception as exc:
        return ctx.record(StageResult(
            STAGE, outcome="degraded",
            notes=(f"edit unavailable ({type(exc).__name__}: {exc}); "
                   "draft left exactly as the reviewer saw it",),
            cost=accounting.cost, llm_calls=accounting.calls,
            input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        ))

    kept = revised.strip()
    if not kept or len(kept.split()) < words * _MIN_KEPT_RATIO:
        # Truncated or refused. The page the lead read is better than half of it.
        return ctx.record(StageResult(
            STAGE, outcome="degraded",
            data={"returned_words": len(kept.split())},
            notes=("the edit came back too short to be the same page; original kept",),
            cost=accounting.cost, llm_calls=accounting.calls,
            input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        ))

    ctx.draft_md = kept
    return ctx.record(StageResult(
        STAGE, outcome="ok",
        data={"instruction": asked, "words_before": words, "words_after": len(kept.split())},
        notes=(f"applied: {asked[:120]}",),
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
    ))
