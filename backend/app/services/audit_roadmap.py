"""Turn 461 findings into a sequenced plan of work - with no invented numbers.

An audit that ends at "here are 461 problems" hands the prioritisation problem
back to the client. This module answers the next question: *what do we do first,
and what do the next twelve months look like?*

EVERY NUMBER HERE IS EITHER MEASURED OR AN OPERATOR INPUT. Nothing is estimated
by a model, because none of the quantities a roadmap wants - effort, duration,
"results in 90 days" - are derivable from anything an audit measures.

    impact    = severity weight x reach x confidence      (all three measured)
    effort    = fix locus + fix surface + volume           (a published table)
    priority  = impact / effort
    phase     = greedy bin-pack into windows sized by ONE operator input

`capacity_points_per_month` is that input. It is the single origin of every
timeline number in the plan, it is stored on the roadmap so a later reader cannot
silently re-interpret it, and it defaults rather than being guessed per client.

PHASES ARE RELATIVE WINDOWS, NEVER DATES. `p1_90d` means "the second and third
months of work", not a calendar quarter. Dates appear only when an operator sets
`start_date`, and are then arithmetic on that input.

Work that does not fit twelve months goes to `backlog` EXPLICITLY. Silently
dropping it would make an under-planned engagement look complete.

Pure: no database, no clock, no network, no model. The DB write and the optional
one-field narrative live outside.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.services.audit_sheets import role_for_section

SCORING_MODEL_VERSION = "impact-over-effort-v1"

PHASE_P0 = "p0_30d"
PHASE_P1 = "p1_90d"
PHASE_P2 = "p2_180d"
PHASE_P3 = "p3_365d"
PHASE_BACKLOG = "backlog"

#: Each phase's own capacity, in MONTHS of the operator's stated throughput.
#: p0 is month 1, p1 is months 2-3, p2 is months 4-6, p3 is months 7-12. They sum
#: to twelve, so the horizon is a year and anything past it is backlog.
PHASE_MONTHS: tuple[tuple[str, int], ...] = (
    (PHASE_P0, 1), (PHASE_P1, 2), (PHASE_P2, 3), (PHASE_P3, 6),
)

PHASE_LABEL = {
    PHASE_P0: "Now - first 30 days",
    PHASE_P1: "Next - through 90 days",
    PHASE_P2: "Then - through 6 months",
    PHASE_P3: "Later - through 12 months",
    PHASE_BACKLOG: "Backlog - beyond the planned horizon",
}

DEFAULT_CAPACITY_POINTS_PER_MONTH = 40

_SEVERITY_WEIGHT = {"critical": 3.0, "major": 2.0, "minor": 1.0, "info": 0.5}

#: EFFORT TABLE - published here and printed in the deliverable's methodology so
#: a client can disagree with it explicitly rather than wonder where it came from.
#:
#: Fix LOCUS: how many places the fix has to be made.
_LOCUS_EFFORT = {
    "site": 1.0,      # one config / one file - robots.txt, a header, a redirect rule
    "template": 2.0,  # one template edit that resolves every page using it
    "entity": 3.0,    # an off-site object: a directory listing, a GBP field
    "url": 3.0,       # genuinely per-page work
}

#: Fix SURFACE: who has to do it and what they have to touch.
_SURFACE_EFFORT = {
    "technical": 2.0,   # usually a developer, often a deploy
    "off-page": 3.0,    # depends on third parties; the slowest surface we have
    "local-seo": 1.5,   # profile and listing work
    "on-page": 1.0,     # content and markup
}

#: Dimension -> the section vocabulary `audit_sheets` already owns, so the
#: roadmap and the remediation sheets assign the same work to the same person.
#: Keyed on DIMENSION rather than pillar because that is the axis the roles were
#: defined against: GEO work goes to the blog writer and strategy to the SEO
#: lead, wherever those checks physically live in the checklists.
_DIMENSION_TO_SECTION = {
    "onpage": "on-page",
    "technical": "technical",
    "offpage": "off-page",
    "local": "local",
    "geo": "geo",
    "strategy": "strategy",
}


@dataclass(slots=True)
class RoadmapItem:
    finding_id: str
    title: str
    check_id: str
    pillar: str
    subcategory: str
    dimension: str
    owner_role: str
    locus_kind: str
    locus_value: str
    severity: str
    instance_count: int
    pages_affected: int
    impact_score: float
    effort_points: float
    priority: float
    exit_criterion: str
    verification_check: str
    phase: str = PHASE_BACKLOG
    sequence: int = 0
    depends_on: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Roadmap:
    capacity_points_per_month: int
    items: list[RoadmapItem]
    scoring_model_version: str = SCORING_MODEL_VERSION

    @property
    def planned(self) -> list[RoadmapItem]:
        return [i for i in self.items if i.phase != PHASE_BACKLOG]

    @property
    def backlog(self) -> list[RoadmapItem]:
        return [i for i in self.items if i.phase == PHASE_BACKLOG]

    def by_phase(self) -> dict[str, list[RoadmapItem]]:
        out: dict[str, list[RoadmapItem]] = {p: [] for p, _ in PHASE_MONTHS}
        out[PHASE_BACKLOG] = []
        for i in self.items:
            out[i.phase].append(i)
        for v in out.values():
            v.sort(key=lambda i: i.sequence)
        return out


def compute_impact(
    *, severity: str, pages_affected: int, pages_crawled: int, confidence: float | None,
) -> float:
    """Measured reach x measured severity x measured confidence.

    Reach is the share of the crawled site the problem touches. A site-scoped
    finding (no pages) reaches the whole site by definition, so it takes 1.0
    rather than 0 - otherwise a broken robots.txt would rank below a typo.
    """
    weight = _SEVERITY_WEIGHT.get((severity or "").lower(), 1.0)
    if pages_crawled > 0 and pages_affected > 0:
        reach = min(1.0, pages_affected / pages_crawled)
    else:
        reach = 1.0
    conf = 1.0 if confidence is None else max(0.0, min(1.0, float(confidence)))
    return round(weight * reach * conf, 4)


def compute_effort(
    *, locus_kind: str, pillar: str, instance_count: int,
) -> float:
    """Locus + surface + a volume term that only applies to per-page work.

    A template fix is one edit whether it resolves 4 pages or 400, so volume must
    NOT scale it - that is the whole reason the cause/instance split exists. Only
    `url`-locus work, which is genuinely repeated per page, carries a volume term,
    and it is bucketed (log-ish) rather than linear so 200 pages is not scored as
    fifty times 4 pages.
    """
    base = _LOCUS_EFFORT.get(locus_kind, 3.0) + _SURFACE_EFFORT.get(pillar, 2.0)
    if locus_kind == "url" and instance_count > 1:
        if instance_count >= 100:
            base += 4.0
        elif instance_count >= 25:
            base += 2.0
        elif instance_count >= 5:
            base += 1.0
    return round(base, 2)


def _exit_criterion(check_id: str, check_name: str, locus_kind: str, locus_value: str) -> str:
    where = {
        "site": "site-wide",
        "template": f"on every page of {locus_value}" if locus_value else "on the template",
        "url": f"on {locus_value}" if locus_value else "on the page",
        "entity": "on the listed profile",
    }.get(locus_kind, "")
    return f"{check_id} ({check_name}) returns pass {where}".strip()


def build(
    findings: Iterable[dict[str, Any]],
    *,
    pages_crawled: int,
    capacity_points_per_month: int = DEFAULT_CAPACITY_POINTS_PER_MONTH,
) -> Roadmap:
    """Score, rank and pack findings into phases.

    Deterministic: ordering breaks ties on `check_id` then `fingerprint`, so the
    same findings always produce the same plan in the same order.
    """
    capacity = max(1, int(capacity_points_per_month))
    items: list[RoadmapItem] = []

    for f in findings:
        pillar = f.get("pillar") or ""
        locus_kind = f.get("locus_kind") or "site"
        instance_count = int(f.get("instance_count") or 0)
        impact = compute_impact(
            severity=f.get("severity") or "",
            pages_affected=int(f.get("pages_affected") or 0),
            pages_crawled=pages_crawled,
            confidence=f.get("confidence"),
        )
        effort = compute_effort(
            locus_kind=locus_kind, pillar=pillar, instance_count=instance_count,
        )
        check_id = f.get("check_id") or ""
        check_name = f.get("check_name") or check_id
        scope = (
            f"{instance_count} pages" if instance_count > 1
            else "site-wide" if locus_kind == "site" else "1 page"
        )
        items.append(RoadmapItem(
            finding_id=str(f.get("id") or ""),
            title=f"{check_name} - {scope}",
            check_id=check_id,
            pillar=pillar,
            subcategory=f.get("subcategory") or "",
            dimension=f.get("dimension") or "",
            owner_role=role_for_section(
                _DIMENSION_TO_SECTION.get(f.get("dimension") or "", "")
            ),
            locus_kind=locus_kind,
            locus_value=f.get("locus_value") or "",
            severity=f.get("severity") or "",
            instance_count=instance_count,
            pages_affected=int(f.get("pages_affected") or 0),
            impact_score=impact,
            effort_points=effort,
            priority=round(impact / effort, 6) if effort else 0.0,
            exit_criterion=_exit_criterion(
                check_id, check_name, locus_kind, f.get("locus_value") or ""),
            verification_check=check_id,
        ))

    # Highest value per unit of work first. Ties break deterministically.
    items.sort(key=lambda i: (-i.priority, -i.impact_score, i.check_id, i.finding_id))

    # Greedy pack. An item larger than a whole phase still goes in - refusing to
    # schedule the single biggest problem would be worse than overfilling by one.
    idx = 0
    for phase, months in PHASE_MONTHS:
        budget = capacity * months
        seq = 1
        while idx < len(items):
            item = items[idx]
            if item.effort_points > budget and seq > 1:
                break
            item.phase = phase
            item.sequence = seq
            budget -= int(item.effort_points)
            seq += 1
            idx += 1
            if budget <= 0:
                break

    for seq, item in enumerate(items[idx:], start=1):
        item.phase = PHASE_BACKLOG
        item.sequence = seq

    return Roadmap(capacity_points_per_month=capacity, items=items)


def effort_table() -> dict[str, Any]:
    """The published effort model, for the deliverable's methodology page.

    A client who disagrees with a priority ordering must be able to see the table
    that produced it rather than being told the number is simply correct.
    """
    return {
        "scoring_model_version": SCORING_MODEL_VERSION,
        "impact": "severity_weight x reach x confidence",
        "severity_weight": dict(_SEVERITY_WEIGHT),
        "effort": "locus + surface (+ volume, url-locus only)",
        "locus": dict(_LOCUS_EFFORT),
        "surface": dict(_SURFACE_EFFORT),
        "volume_url_locus": {">=5": 1.0, ">=25": 2.0, ">=100": 4.0},
        "priority": "impact / effort",
        "phases": {p: m for p, m in PHASE_MONTHS},
    }
