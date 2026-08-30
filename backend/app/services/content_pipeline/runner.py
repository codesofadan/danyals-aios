"""The runner - the stage sequence, and where it is allowed to stop (P3).

v1 is one function call. This is a SEQUENCE, and the sequence is where three policies
that v1 could not express live.

WHERE A HALT IS DIFFERENT FROM A FAILURE. The SME stage refuses to draft a page whose
first-party facts nobody has supplied. That is the system working exactly as designed -
Law 16, and the owner's "hard halt, no exceptions" decision - so it must not be retried,
alerted on, or counted as an error. `StageResult.blocks_pipeline` covers both, and the
runner reports which one happened.

WHERE A DEGRADE IS SURVIVABLE. A degraded research brief still lets a page be written
under a low-confidence flag. A degraded outline does not: everything downstream is built
on it. So the runner stops on a blocking outcome and CONTINUES through a degrade,
carrying the degrade forward into the final outcome instead of losing it.

WHAT ORDER COSTS. The cached doctrine prefix is prefix-matched and its TTL is five
minutes, so the stages of one page must run back-to-back to hit it. Running stage 5 for
fifty pages and then stage 6 for fifty pages would miss the cache on every single call.
Per-page sequential is not just simpler here; it is the cheaper shape.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.content_pipeline.context import PipelineContext, StageResult

# The order pages are produced in. Stage 0 (SCOPE) and stage 1 (KEYWORD DISCOVERY) are
# ENGAGEMENT-level and run once for a batch, not once per page, so they are not here.
PAGE_STAGES: tuple[str, ...] = (
    "sme",           # 3  - the halt
    "research",      # 4
    "outline",       # 5  - the uniqueness gate
    "draft",         # 6
    "convert",       # 7
    "voice",         # 8
    "grounding",     # 8b - cut figures no supplied fact supports
    "claims",        # 8c - delete uncited compliance/third-party/absolute claims
    "images",        # 8d - the hero/section photos, after the text is final
    "title_meta",    # 9
    "schema_links",  # 10 - free
    "gate",          # 11
)

#: The sequence for a REVIEWER'S EDIT, which is not a redraft. The page already
#: exists and the lead has read it; re-running research, outline and draft would
#: throw away the page they commented on and replace it with a different one, at
#: the cost of a full page. So: apply the instruction, then re-run only the checks
#: that must see the change - voice, grounding, the meta that quotes the body, the
#: schema built from it, and the gate that scores it.
EDIT_STAGES: tuple[str, ...] = (
    "guided_edit",
    "voice",
    "grounding",
    "claims",
    "title_meta",
    "schema_links",
    "gate",
)


# Stages whose degrade poisons everything after them. A page whose OUTLINE degraded has
# no reliable structure to draft against, so continuing spends real money producing
# prose nobody should publish.
FATAL_ON_DEGRADE: frozenset[str] = frozenset({"outline"})


@dataclass
class PipelineRun:
    """What happened to one page."""

    ctx: PipelineContext
    outcome: str = "ok"
    stopped_at: str | None = None
    reason: str = ""
    results: list[StageResult] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(r.cost for r in self.results)

    @property
    def llm_calls(self) -> int:
        return sum(r.llm_calls for r in self.results)

    @property
    def halted(self) -> bool:
        """True when the system correctly refused, not when something broke."""
        return self.outcome == "halted"

    def summary(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "stopped_at": self.stopped_at,
            "reason": self.reason,
            "cost": round(self.cost, 4),
            "llm_calls": self.llm_calls,
            "stages": {r.stage: r.outcome for r in self.results},
        }


def run_page(
    ctx: PipelineContext,
    stages: dict[str, Callable[[PipelineContext], StageResult]],
    *,
    order: tuple[str, ...] = PAGE_STAGES,
    fatal_on_degrade: frozenset[str] = FATAL_ON_DEGRADE,
) -> PipelineRun:
    """Run one page through the stages, stopping where stopping is correct.

    ``stages`` maps a stage name to an already-bound callable, so this function never
    constructs a writer, a store or a provider - which is what lets the whole sequence
    be tested against fakes without touching a network or a database.

    A stage missing from ``stages`` is SKIPPED, not an error: a shape that legitimately
    has no research step should not have to supply a no-op.
    """
    run = PipelineRun(ctx=ctx)
    degraded: list[str] = []

    for name in order:
        stage = stages.get(name)
        if stage is None:
            continue

        try:
            result = stage(ctx)
        except Exception as exc:
            # A stage that raises is a bug, not a business outcome. Record it as this
            # stage's failure so the run reports WHERE it broke rather than vanishing.
            result = ctx.record(StageResult(
                name, outcome="failed",
                notes=(f"stage raised {type(exc).__name__}: {exc}",),
            ))
        run.results.append(result)

        if result.blocks_pipeline:
            run.outcome = "halted" if result.outcome == "halted" else "failed"
            run.stopped_at = name
            run.reason = result.notes[0] if result.notes else result.outcome
            return run

        if result.outcome == "degraded":
            degraded.append(name)
            if name in fatal_on_degrade:
                run.outcome = "degraded"
                run.stopped_at = name
                run.reason = (
                    f"{name} degraded, and everything after it is built on it; "
                    "stopping rather than spending on a page nobody should publish"
                )
                return run

    if degraded:
        run.outcome = "degraded"
        run.reason = "degraded stages: " + ", ".join(degraded)
    return run
