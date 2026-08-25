"""CONVERT - the page has to ask for the business (P3, stage 7).

v1 had no conversion stage at all. `content_qa`'s cta_ux dimension was scored by
`_proxy_cta_ux`, a heuristic looking for a phone number or the word "call" - which a
page can satisfy while giving the reader no reason and no moment to act.

`content_lint.conversion` is the ported `conversion_linter.py` and objects to the real
failures: no CTA above the fold, a CTA that is mechanical rather than specific ("click
here"), objections raised and never answered, proof that appears nowhere near the ask.

Those are prose problems, so a model fixes them - but only the ones actually found, and
only if any were. See `repair.py` for why all three of those conditions are load-bearing.
"""

from __future__ import annotations

from app.services.content_lint import lint_conversion
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.repair import Finding, run_repair_stage
from app.services.content_pipeline.writer import DoctrineWriter

STAGE = "convert"

_INSTRUCTION = (
    "This page reads well but does not yet ask for the business properly. Repair the "
    "conversion problems listed below.\n"
    "A good ask on a local service page is specific and low-friction: it names the next "
    "step, says what happens after the reader takes it, and sits next to the proof that "
    "makes it credible. 'Contact us today' is not an ask; it is a placeholder."
)


def _measure(text: str) -> tuple[Finding, ...]:
    """Only ERRORs drive a paid repair.

    WARNs are advisory by the linter's own definition and do not fail G13. Repairing
    them would mean paying to satisfy a check that was never going to block the page.
    """
    return tuple(
        Finding(code=i.code, line=i.line, message=i.message)
        for i in lint_conversion(text).errors
    )


def run_convert(
    ctx: PipelineContext, *, writer: DoctrineWriter, model: str | None = None
) -> StageResult:
    """Give the page a credible ask, or leave it alone if it already has one."""
    return run_repair_stage(
        ctx, stage=STAGE, writer=writer, measure=_measure,
        instruction=_INSTRUCTION, model=model,
    )
