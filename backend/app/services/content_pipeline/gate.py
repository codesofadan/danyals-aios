"""GATE - the QA verdict, with the judge actually connected (P3, stage 11).

`content_qa` is a genuinely good 14-dimension scorecard that has never been given what
it needs. Two things were missing, and this stage supplies both.

1. THE JUDGE. Five dimensions route through the `Judge` seam - three of them HARD GATE
   dimensions - and `judge` is None on every real run, so all five fall back to
   conservative proxies while the scorecard reports a number that reads like a
   judgment. `ClaudeJudge` fills that seam in one call.

2. A `GeneratedContent` TO SCORE. `score()` expects the shape v1's generator returned.
   This stage ASSEMBLES it from what the pipeline actually produced - headings from the
   outline, prose from the draft, title and meta from stage 9, grounding from the SME
   facts - rather than reconstructing it by guesswork. Anything the pipeline genuinely
   does not have is left EMPTY, never filled with a plausible default: a fabricated
   internal-link list would score the linking dimension on links that do not exist.

DEGRADING HONESTLY. If the judge cannot produce a usable verdict, the page is re-scored
with `judge=None` and the result SAYS the judged dimensions are proxies. The alternative
- letting a broken judge return a number - is a page that passed QA because the QA
broke.

ADVISORY, STILL. `passed=False` does not block publication today (P0-4 / D-4), and the
85 threshold is PROVISIONAL by `content_qa`'s own declaration: not calibrated against
ranking outcomes or a human SEO grade. This stage reports the verdict and says it is
provisional. Turning it into a hard gate is a decision that has to wait for calibration,
because a hard gate on an uncalibrated number blocks good pages for a reason nobody can
defend.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.content_generator import (
    DifferentiationAngle,
    GeneratedContent,
    GroundedClaim,
    Heading,
    InternalLink,
    SourcePack,
)
from app.services.content_lint import analyse_density, strip_markdown
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.judge import (
    JUDGED_DIMENSIONS,
    ClaudeJudge,
    JudgeUnavailableError,
)
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting
from app.services.content_qa import QaScore, score
from app.services.content_research import ResearchBrief

STAGE = "gate"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# A line that is nothing but an image. The IMAGES stage injects the hero photo directly
# under the H1, which is INSIDE the direct-answer block, so `![alt](url)` lands in the
# text `_score_structure_readability` counts against its 40-55 WORD band (ANSWER_MIN_
# WORDS / ANSWER_MAX_WORDS). The alt is the H1, so the markup adds roughly as many
# "words" as the band has slack - enough to fail a correct answer on markup alone.
# An image is not prose.
_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")


def headings_of(draft_md: str) -> list[Heading]:
    """Every markdown heading, in document order."""
    out: list[Heading] = []
    for line in draft_md.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            out.append(Heading(level=len(m.group(1)), text=m.group(2).strip()))
    return out


def answer_block_of(draft_md: str) -> str:
    """The prose between the first heading and the next one.

    A direct-answer block is the paragraph a reader (and an AI overview) reads first.
    Taking it positionally is deliberate: asking a model to identify it would be paying
    to locate something the document structure already fixes.
    """
    lines = draft_md.splitlines()
    start = next((i for i, ln in enumerate(lines) if _HEADING_RE.match(ln.strip())), None)
    if start is None:
        return "\n".join(lines[:4]).strip()
    body: list[str] = []
    for line in lines[start + 1:]:
        text = line.strip()
        if _HEADING_RE.match(text):
            break
        if _IMAGE_LINE_RE.match(text):
            continue
        body.append(line)
    return "\n".join(body).strip()


def _content_for(ctx: PipelineContext, brief: ResearchBrief) -> GeneratedContent:
    """Assemble what the pipeline produced into the shape `score()` reads.

    The measurable fields are MEASURED, with the same ported validators the rest of the
    pipeline uses - a zero passed to `primary_density` would score the keyword-handling
    dimension against a number nobody computed.

    `internal_links` is what the SCHEMA_LINKS stage actually wrote into the page, never
    what it merely planned: a target with no known URL is not on the page, and scoring
    the linking dimension on it would report link coverage a reader cannot click. The
    plan travels separately (`internal_links_planned`) so `run_gate` can explain a low
    score instead of leaving it unexplained.

    `images_plan` stays EMPTY: the IMAGES stage injects finished `![alt](url)` blocks
    into the draft and keeps no ImagePlanItem list here, and no QA dimension reads this
    field - a reconstructed one would be decoration.
    """
    facts = tuple(ctx.facts)
    angle_kind = "first_hand_experience" if facts else "none"

    prose = strip_markdown(ctx.draft_md)
    rows = analyse_density(ctx.draft_md, [ctx.primary_keyword]).rows
    density = rows[0].density if rows else 0.0

    # Table-stakes entities are what the top-10 teardown says this topic must cover.
    # Absent a teardown the lists stay empty - scoring coverage against an empty
    # expectation is not the same as scoring it against nothing.
    wanted = list(brief.teardown.table_stakes_entities) if brief.teardown else []
    lowered = prose.lower()
    covered = [e for e in wanted if e.lower() in lowered]
    missing = [e for e in wanted if e.lower() not in lowered]
    return GeneratedContent(
        title=ctx.title,
        meta_description=ctx.meta_description,
        draft_md=ctx.draft_md,
        page_type=ctx.page_type,
        framework=ctx.framework,  # type: ignore[arg-type]
        target=ctx.primary_keyword,
        headings=headings_of(ctx.draft_md),
        answer_block=answer_block_of(ctx.draft_md),
        section_roles=[],
        differentiation_angle=DifferentiationAngle(
            kind=angle_kind,
            statement=facts[0] if facts else "",
            grounded=bool(facts),
            derived_from=["sme_slots"] if facts else [],
        ),
        internal_links=[
            x for x in (ctx.brief.get("internal_links") or []) if isinstance(x, InternalLink)
        ],
        images_plan=[],
        grounding=[GroundedClaim(claim=f, source="sme_slots") for f in facts],
        needs=[],
        word_count=len(prose.split()),
        primary_density=density,
        entities_covered=covered,
        entities_missing=missing,
        # Cross-page uniqueness lives in `content_outline_shingles` and is enforced at
        # the OUTLINE stage, where a collision can still change the page. Recomputing a
        # number here that nothing acts on would be decoration.
        local_uniqueness={},
        notes=[],
    )


def _source_pack_for(ctx: PipelineContext) -> SourcePack:
    """Only ANSWERED first-party facts. An unanswered slot is a question, not proof."""
    return SourcePack(
        client_name=ctx.client_name,
        proof_points=list(ctx.facts),
    )


def run_gate(
    ctx: PipelineContext,
    *,
    writer: DoctrineWriter | None = None,
    model: str | None = None,
) -> StageResult:
    """Score the finished page, using the LLM judge when one is available."""
    if not ctx.draft_md.strip():
        return ctx.record(StageResult(
            STAGE, outcome="skipped", notes=("no draft to score",),
        ))

    brief = ctx.brief.get("research")
    if not isinstance(brief, ResearchBrief):
        return ctx.record(StageResult(
            STAGE, outcome="degraded",
            notes=("no research brief; QA needs the brief's intent to score "
                   "intent-match and format fit",),
        ))

    content = _content_for(ctx, brief)
    pack = _source_pack_for(ctx)
    schema_result = ctx.brief.get("schema_validation")
    notes: list[str] = []
    accounting = WriteAccounting()
    judged = False

    verdict: QaScore | None = None
    if writer is not None:
        judge = ClaudeJudge(
            writer, page_type=ctx.page_type, vertical=ctx.vertical or None,
            framework=ctx.framework, model=model, accounting=accounting,
        )
        try:
            verdict = score(content, brief, schema_result, pack, judge=judge)
            judged = True
        except JudgeUnavailableError as exc:
            notes.append(
                f"judge unavailable ({exc}); the five judged dimensions "
                f"({', '.join(JUDGED_DIMENSIONS)}) are DETERMINISTIC PROXIES"
            )
        except Exception as exc:
            notes.append(f"judged scoring failed ({type(exc).__name__}); using proxies")
    else:
        notes.append("no writer supplied; judged dimensions are deterministic proxies")

    if verdict is None:
        verdict = score(content, brief, schema_result, pack, judge=None)

    planned_links = [
        x for x in (ctx.brief.get("internal_links_planned") or []) if isinstance(x, InternalLink)
    ]
    unresolved = len(planned_links) - len(content.internal_links)
    if unresolved > 0:
        # Without this the internal_linking dimension reports a bare 40 and the reviewer
        # has no way to tell "nobody built a link plan" from "the plan exists and the
        # sibling pages are not published yet". They need different actions.
        notes.append(
            f"internal_linking is scored on the {len(content.internal_links)} link(s) the "
            f"page carries; {unresolved} more are PLANNED but have no url yet (no "
            "published sibling page is known for them)"
        )

    notes.extend(verdict.notes[:8])
    if verdict.blocked_by:
        notes.append("hard gate tripped: " + ", ".join(verdict.blocked_by))
    if verdict.provisional:
        notes.append(
            "the 85 threshold and the weight vector are PROVISIONAL - not calibrated "
            "against ranking outcomes or a human SEO grade"
        )

    data: dict[str, Any] = {
        # The entity picture the gate already computed on its way to a score. It
        # was thrown away with the local `content` object, so the `entities`
        # column stayed empty for every page this engine wrote and the reviewer's
        # entity tab had nothing in it - while the numbers existed, right here.
        "entity_coverage": {
            "table_stakes": list(getattr(brief.teardown, "table_stakes_entities", []) or []),
            "differentiators": list(
                getattr(brief.teardown, "differentiator_entities", []) or []
            ),
            "covered": list(content.entities_covered),
            "missing": list(content.entities_missing),
            "primary_density": content.primary_density,
            "local_uniqueness": content.local_uniqueness,
        },
        "dimensions": dict(verdict.dimensions),
        "weighted_total": verdict.weighted_total,
        "passed": verdict.passed,
        "blocked_by": list(verdict.blocked_by),
        "provisional": verdict.provisional,
        "judged": judged,
    }
    ctx.brief["qa"] = verdict
    return ctx.record(StageResult(
        STAGE,
        # A failing score is a VERDICT, not a stage failure: the stage did its job.
        # "degraded" is reserved for the gate itself not working properly.
        outcome="ok" if judged else "degraded",
        data=data, notes=tuple(notes),
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        cache_write_tokens=accounting.cache_write_tokens,
        cache_read_tokens=accounting.cache_read_tokens,
        chunk_ids=tuple(accounting.chunk_ids),
    ))
