"""RESEARCH - one SERP, and no invented numbers (P3, stage 4).

A THIN WRAPPER, ON PURPOSE. `content_research.build_research_brief` already does the
work - intent classification, term sets, clustering, format decision, the top-10
teardown - behind a gated `ResearchPort`, and it already degrades rather than crashing
when the cost gate blocks. Rewriting that would be rewriting the one part of v1's
research that is genuinely good.

WHAT THIS STAGE CHANGES IS WHERE THE NUMBERS COME FROM.

`integrations/content_research.py:136-164` computes `difficulty = log10(totalResults) *
8` and `volume = 10 ** (log10(totalResults) / 2)`. Those are invented, dressed as vendor
data, and each one costs a paid Serper credit to invent. Search volume originates in
Google's ad auction; there is no offline derivation of it, so any "we compute it
ourselves" here is not thrift, it is a fabrication with a bill attached.

Stage 1 (KEYWORD DISCOVERY) already bought the real numbers ONCE for the whole
engagement - roughly ten DataForSEO calls amortised across every page. So this stage
prefers that plan and marks anything it could not find as `estimated`, rather than
paying per page to manufacture a number that was never real.

The honesty is structural: a term carries `estimated` all the way to the deliverable's
`Method & Sources` tab, so a reader months later can see which figures were bought and
which were guessed. That distinction is the whole reason the column exists.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_research import (
    ContentSpendBlocked,
    ResearchBrief,
    ResearchPort,
    build_research_brief,
)

STAGE = "research"


class KeywordPlanLookup(Protocol):
    """Reads the metrics stage 1 already bought for this engagement."""

    def metrics_for(self, engagement_id: str | None, keyword: str) -> dict[str, Any] | None: ...


def run_research(
    ctx: PipelineContext,
    *,
    researcher: ResearchPort,
    plan: KeywordPlanLookup | None = None,
    client_da: float | None = None,
    serp_date: str | None = None,
) -> StageResult:
    """Build the research brief for this page's target keyword."""
    if not ctx.primary_keyword.strip():
        return ctx.record(StageResult(
            STAGE, outcome="failed", notes=("no target keyword to research",),
        ))

    notes: list[str] = []
    try:
        brief: ResearchBrief = build_research_brief(
            ctx.primary_keyword,
            researcher=researcher,
            geo=ctx.geo or None,
            client_da=client_da,
            serp_date=serp_date,
        )
    except ContentSpendBlocked as blocked:
        # build_research_brief degrades internally rather than raising, so reaching
        # here means the gate blocked before any of it ran.
        return ctx.record(StageResult(
            STAGE, outcome="degraded",
            notes=(f"research blocked by the cost gate ({blocked.outcome})",),
        ))
    except Exception as exc:
        # The MESSAGE, not just the type. "research unavailable (AttributeError)" is
        # what this said first, and it was useless: the actual cause was a fake missing
        # a `teardown` method, which the type alone never points at.
        return ctx.record(StageResult(
            STAGE, outcome="degraded",
            notes=(f"research unavailable ({type(exc).__name__}: {exc})",),
        ))

    # The bought numbers, if stage 1 has them for this term.
    metrics = None
    if plan is not None:
        try:
            metrics = plan.metrics_for(ctx.engagement_id, ctx.primary_keyword)
        except Exception as exc:  # a lookup failure must not lose the brief
            notes.append(f"keyword plan lookup failed ({type(exc).__name__})")
    if metrics:
        notes.append("volume/difficulty read from the engagement's keyword plan")
    else:
        notes.append(
            "no keyword-plan row for this term; volume and difficulty are ESTIMATED "
            "and must be reported as such"
        )

    if brief.degraded:
        notes.append("brief is a shell: the SERP pull did not complete")
    if brief.low_confidence:
        notes.append("brief is low-confidence: part of the research degraded")

    ctx.brief["research"] = brief
    ctx.brief["keyword_metrics"] = metrics
    ctx.brief["metrics_estimated"] = metrics is None

    return ctx.record(StageResult(
        STAGE,
        outcome="degraded" if (brief.degraded or brief.low_confidence) else "ok",
        data={
            "intent": brief.intent,
            "intent_confidence": round(brief.intent_confidence, 3),
            "secondary_terms": len(brief.terms.secondary),
            "questions": len(brief.terms.questions),
            "teardown": len(brief.teardown.pages) if brief.teardown else 0,
            "metrics_estimated": metrics is None,
        },
        notes=tuple(notes),
    ))
