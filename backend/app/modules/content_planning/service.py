"""Engagement shapes - what each one actually runs, and what it may spend (P4).

v1 had ONE shape. Every job was a single page, and the owner's real work is not:
"it will not be about four pages per client per month... it all depends upon the need
of the client". A whole-site build, a set of service pages, and picking up an
engagement that is already three months in are different pieces of work, and the
difference is not a parameter - it is which stages run, in what order, against what
budget.

THE THREE THINGS A SHAPE DECIDES:

1. WHICH STAGES RUN AT ALL. `single_page` has no keyword-discovery stage to run: the
   operator named the target. `full_site` cannot start without a brand kit, because
   fifty pages that each invent their own look is the thing the owner explicitly does
   not want. `continue_existing` has to read the audit BEFORE planning, or it will
   cheerfully re-commission pages the client already has.

2. WHAT ORDER PAGES ARE PRODUCED IN. The doctrine prefix is prefix-matched with a
   five-minute cache TTL, and the page-type/vertical block is the largest variable part
   of it. Producing pages grouped by (vertical, page_type) hits that cache; producing
   them in the order somebody happened to type them does not. This is a free saving -
   a sort - and on a fifty-page build it is the difference between paying the cache
   write once per group and once per page.

3. WHAT IT MAY SPEND BEFORE SOMEBODY LOOKS. `_estimate_full_cost` bounds a job once,
   up front. Nothing bounds an ENGAGEMENT, so fifty pages of retries can walk past any
   estimate while every individual job looks reasonable. The ceiling here is checked
   before each page is enqueued, against spend that already happened.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.modules.content_planning.schemas import Engagement, EngagementShape, MapNode

# Per-page stages, from `content_pipeline.runner.PAGE_STAGES`.
PAGE_STAGES: tuple[str, ...] = (
    "sme", "research", "outline", "draft", "convert", "voice",
    "title_meta", "schema_links", "gate",
)

# Engagement-level stages. These run ONCE for a batch, not once per page - which is
# the single biggest cost difference between this and v1. Keyword discovery is roughly
# ten DataForSEO calls whether the engagement is one page or fifty; amortised across
# fifty it is 0.2 calls per page.
ENGAGEMENT_STAGES: tuple[str, ...] = ("scope", "keyword_discovery", "topical_map")

Prerequisite = Literal["brand_kit", "source_audit", "named_targets"]


@dataclass(frozen=True)
class ShapePlan:
    """What one engagement shape runs, needs, and is allowed to do."""

    shape: EngagementShape
    engagement_stages: tuple[str, ...]
    page_stages: tuple[str, ...] = PAGE_STAGES
    requires: tuple[Prerequisite, ...] = ()
    recurring: bool = False
    description: str = ""


SHAPE_PLANS: dict[EngagementShape, ShapePlan] = {
    # The operator named the keyword, so there is nothing to discover and no map to
    # build. Running discovery here would buy an engagement's worth of keyword data to
    # write one page.
    "single_page": ShapePlan(
        shape="single_page",
        engagement_stages=("scope",),
        requires=("named_targets",),
        description="one page against a keyword the operator supplies",
    ),
    # Discovery and a map, both scoped to the named services and cities rather than the
    # whole niche. This is where the doctrine cache pays best: many pages, one vertical,
    # usually one page type.
    "page_set": ShapePlan(
        shape="page_set",
        engagement_stages=ENGAGEMENT_STAGES,
        requires=("named_targets",),
        description="a defined set of service or location pages",
    ),
    # The 50+ page case. A brand kit is a PREREQUISITE, not a nicety: without one, every
    # page picks its own look and the site reads as assembled by different people.
    "full_site": ShapePlan(
        shape="full_site",
        engagement_stages=ENGAGEMENT_STAGES,
        requires=("brand_kit",),
        description="a whole site, built against one extracted brand identity",
    ),
    # The audit is read FIRST. Planning without it re-commissions pages the client
    # already has, which is worse than useless - it is billable duplication.
    "continue_existing": ShapePlan(
        shape="continue_existing",
        engagement_stages=("scope", "read_audit", *ENGAGEMENT_STAGES[1:]),
        requires=("source_audit",),
        description="pick up an engagement already in progress, audit first",
    ),
    # Beat is parked by owner instruction, so a cycle is started by a person pressing a
    # button. Modelled as recurring here, but nothing schedules it.
    "retainer": ShapePlan(
        shape="retainer",
        engagement_stages=ENGAGEMENT_STAGES,
        recurring=True,
        description="an ongoing engagement, one operator-triggered cycle at a time",
    ),
}


@dataclass(frozen=True)
class Readiness:
    """Whether an engagement can start, and what is missing if it cannot."""

    ready: bool
    missing: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


_PREREQUISITE_REASONS: dict[Prerequisite, str] = {
    "brand_kit": (
        "a full-site build needs an extracted brand kit first; without one every page "
        "chooses its own typography and palette and the site reads as assembled by "
        "different people"
    ),
    "source_audit": (
        "continuing an existing engagement needs its audit; planning without it "
        "re-commissions pages the client already has"
    ),
    "named_targets": (
        "this shape needs the operator's named services or cities in scope; there is "
        "no discovery stage to infer them"
    ),
}


def plan_for(shape: EngagementShape) -> ShapePlan:
    """The plan for a shape. Unknown shapes fall back to the safest real one."""
    return SHAPE_PLANS.get(shape, SHAPE_PLANS["single_page"])


def check_readiness(
    engagement: Engagement, *, has_brand_kit: bool = False
) -> Readiness:
    """Can this engagement start producing pages?

    Deliberately separate from the SME halt. That halt is per-CLUSTER and blocks
    drafting; this is per-ENGAGEMENT and blocks the whole thing from starting. Both
    exist because both failures are real and they are not the same failure.
    """
    plan = plan_for(engagement.shape)
    missing: list[str] = []
    reasons: list[str] = []

    for need in plan.requires:
        satisfied = {
            "brand_kit": has_brand_kit,
            "source_audit": bool(engagement.source_audit_id),
            "named_targets": bool(
                engagement.scope.get("services") or engagement.scope.get("cities")
            ),
        }[need]
        if not satisfied:
            missing.append(need)
            reasons.append(_PREREQUISITE_REASONS[need])

    if engagement.status == "cancelled":
        missing.append("status")
        reasons.append("the engagement is cancelled")

    return Readiness(ready=not missing, missing=tuple(missing), reasons=tuple(reasons))


def order_for_cache(
    nodes: Iterable[MapNode], *, vertical: str = ""
) -> list[MapNode]:
    """Group pages so the doctrine cache actually hits.

    The system prompt is three blocks: a constitution that never varies, a stage role,
    and a PAGE PACK keyed on page type and vertical. That third block is the biggest
    variable one, and the cache is prefix-matched - so two consecutive pages sharing a
    page type reuse it, and two that do not each pay the write.

    Sorting by (page_type, cluster, priority) is free and does nothing else: the set of
    pages produced is identical, only the order changes. Priority is preserved WITHIN a
    group so the most important page of each type still comes first.
    """
    return sorted(
        nodes,
        key=lambda n: (
            n.page_type or "",
            n.cluster_key or "",
            -n.priority,
            n.primary_keyword or "",
        ),
    )


def cache_groups(nodes: Sequence[MapNode]) -> list[tuple[str, int]]:
    """(page_type, run-length) for an ordered node list - what the ordering bought.

    Reported rather than assumed: an engagement whose pages are all different types
    gains nothing from the sort, and saying so is better than implying a saving.
    """
    out: list[tuple[str, int]] = []
    for node in nodes:
        key = node.page_type or ""
        if out and out[-1][0] == key:
            out[-1] = (key, out[-1][1] + 1)
        else:
            out.append((key, 1))
    return out


@dataclass
class BudgetLedger:
    """Spend against an engagement's cap, checked BEFORE each page is enqueued.

    `_estimate_full_cost` bounds one job once, up front, against an estimate. Nothing
    bounds the engagement, so a retry loop across fifty pages can walk far past any
    per-job estimate while every individual job still looks reasonable. This counts
    what was ACTUALLY spent.
    """

    cap: float | None = None
    spent: float = 0.0
    pages_done: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> float | None:
        return None if self.cap is None else max(0.0, self.cap - self.spent)

    @property
    def exhausted(self) -> bool:
        return self.cap is not None and self.spent >= self.cap

    def record(self, cost: float) -> None:
        self.spent += max(0.0, cost)
        self.pages_done += 1

    def can_start_page(self, *, estimate: float) -> tuple[bool, str]:
        """Whether the next page fits, given what has already been spent.

        The estimate is checked against what REMAINS, not against the cap. A page that
        would take the engagement past its ceiling does not start - stopping with the
        pages so far intact beats stopping halfway through page thirty-one with a
        half-written page and no budget to finish it.
        """
        if self.cap is None:
            return True, ""
        if self.exhausted:
            return False, (
                f"engagement budget of ${self.cap:.2f} is spent "
                f"(${self.spent:.2f} across {self.pages_done} pages)"
            )
        remaining = self.remaining or 0.0
        if estimate > remaining:
            return False, (
                f"the next page is estimated at ${estimate:.2f} but only "
                f"${remaining:.2f} of the ${self.cap:.2f} engagement budget remains; "
                f"{self.pages_done} pages completed"
            )
        return True, ""


@dataclass(frozen=True)
class WorkPlan:
    """Everything needed to produce one engagement, in the order it should happen."""

    engagement_id: str
    shape: EngagementShape
    engagement_stages: tuple[str, ...]
    page_stages: tuple[str, ...]
    nodes: tuple[MapNode, ...]
    readiness: Readiness
    recurring: bool = False
    notes: tuple[str, ...] = ()

    @property
    def page_count(self) -> int:
        return len(self.nodes)

    @property
    def can_start(self) -> bool:
        return self.readiness.ready and bool(self.nodes)


def build_work_plan(
    engagement: Engagement,
    nodes: Sequence[MapNode],
    *,
    has_brand_kit: bool = False,
) -> WorkPlan:
    """Turn an engagement and its map into an ordered, checked plan of work."""
    plan = plan_for(engagement.shape)
    readiness = check_readiness(engagement, has_brand_kit=has_brand_kit)
    pending = [n for n in nodes if n.status in ("planned", "queued")]
    ordered = order_for_cache(pending)

    notes: list[str] = [plan.description]
    if not pending and nodes:
        notes.append(f"all {len(nodes)} mapped pages are already produced")
    groups = cache_groups(ordered)
    if groups and max(count for _t, count in groups) > 1:
        notes.append(
            "pages ordered by type so the doctrine page-pack cache is reused: "
            + ", ".join(f"{t or 'untyped'} x{c}" for t, c in groups)
        )
    elif ordered:
        notes.append(
            "every page is a different type, so the ordering buys no cache reuse here"
        )
    if plan.recurring:
        notes.append(
            "retainer: one cycle per operator action - beat is parked, so nothing "
            "starts the next cycle on its own"
        )
    notes.extend(readiness.reasons)

    return WorkPlan(
        engagement_id=engagement.id,
        shape=engagement.shape,
        engagement_stages=plan.engagement_stages,
        page_stages=plan.page_stages,
        nodes=tuple(ordered),
        readiness=readiness,
        recurring=plan.recurring,
        notes=tuple(notes),
    )
