"""Composite scores, computed over checks that actually ran.

Twenty-two declared checks are scores over other checks. Left ungated they are
the most dangerous rows in the system: ``OFF-074`` "Authority score" declares
``data_sources: [computed]``, which classes as zero-cost, so it ran on a FREE
tier while all 33 backlink checks it aggregates were skipped - publishing an
authority score computed over no link data.

Two decisions make these buildable without inventing anything:

**Which checks a rollup aggregates comes from the checklist taxonomy**, not from
a hand-written list. "Title tag overall score" is the ``titles`` subpoint;
"Overall technical SEO score" is the technical pillar minus its own scoring
subpoint. Where the taxonomy does not answer it, the rollup is NOT built - see
the note at the foot of this module.

**The weighting is the one the engine already publishes.**
``scorers.aggregator.SEVERITY_WEIGHT`` is applied at every other level, so
reusing it means a rollup cannot disagree with the pillar score above it. This
is what O-1 was asking for, and it turns out not to need judgement: inventing a
second weighting scheme is what would have needed defending.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import rollup
from audit_engine.checklist import load_registry
from audit_engine.scorers.aggregator import SEVERITY_WEIGHT

#: Subpoints that hold the rollups themselves. A pillar rollup must exclude
#: them or it would aggregate its own output.
SCORING_SUBPOINT = "scoring"

#: Every check that IS a rollup. Almost all live in the `scoring` subpoint, but
#: ON-004 "Search intent alignment score" does not - it sits in `search-intent`
#: alongside the checks it aggregates. Excluding only the scoring subpoint made
#: ON-004 aggregate itself and made ON-118 fold ON-004's output back in.
def _rollup_ids() -> frozenset[str]:
    reg = load_registry()
    return frozenset(
        {c for c, s in reg.items() if s.subcategory == SCORING_SUBPOINT} | {"ON-004"}
    )


@dataclass
class RollupContext:
    """Every verdict produced so far in this run, by check id.

    A check can appear many times (once per page), so each id maps to a list.

    Accepts anything carrying ``status``, ``score`` and ``severity`` - both a
    ``Verdict`` and a persisted ``Finding`` qualify. That matters: most on-page
    checks still come from the legacy generators, and a rollup that saw only
    registry-dispatched findings would compute an on-page score over a tenth of
    the on-page checks and never say so.
    """

    verdicts: dict[str, list[Any]] = field(default_factory=dict)

    def add(self, check_id: str, verdict: Any) -> None:
        self.verdicts.setdefault(check_id, []).append(verdict)

    @classmethod
    def from_findings(cls, findings: Any) -> RollupContext:
        ctx = cls()
        for f in findings or ():
            cid = getattr(f, "check_id", None)
            if cid:
                ctx.add(cid, f)
        return ctx

    @property
    def ran(self) -> set[str]:
        """Check ids that produced at least one MEASURED verdict.

        An n_a is not a run: it is the check saying it could not measure. A
        rollup gated on "did this run" must not count them, or it would treat
        a page full of "not applicable" as evidence.
        """
        return {
            cid for cid, vs in self.verdicts.items()
            if any(v.status != "n_a" for v in vs)
        }

    def score_over(self, check_ids: tuple[str, ...]) -> tuple[float | None, dict[str, Any]]:
        """Severity-weighted mean of every measured verdict for these checks.

        Returns (score 0-10, provenance). Mirrors scorers.aggregator._team_score
        exactly, at 0-10 rather than 0-100, so a rollup and the pillar score
        above it can never disagree about the same set of findings.
        """
        weighted = 0.0
        total_w = 0.0
        counted = 0
        by_status: dict[str, int] = {}
        for cid in check_ids:
            for v in self.verdicts.get(cid, ()):
                by_status[v.status] = by_status.get(v.status, 0) + 1
                if v.status == "n_a" or v.score is None:
                    continue
                w = SEVERITY_WEIGHT.get(v.severity, 1.0)
                weighted += v.score * w
                total_w += w
                counted += 1
        provenance = {
            "verdicts_counted": counted,
            "status_breakdown": by_status,
            "weighting": "severity-weighted mean, the same weights "
                         "scorers.aggregator applies at every other level",
        }
        if not total_w:
            return None, provenance
        return round(weighted / total_w, 2), provenance


# --------------------------------------------------------------------------
# Input sets, derived from the checklist rather than hand-written
# --------------------------------------------------------------------------

def _in_subpoints(pillar: str, *subcategories: str) -> tuple[str, ...]:
    reg = load_registry()
    rollup_ids = _rollup_ids()
    return tuple(sorted(
        c for c, s in reg.items()
        if s.pillar == pillar and s.subcategory in subcategories and c not in rollup_ids
    ))


def _in_pillar(pillar: str) -> tuple[str, ...]:
    """Every check in a pillar EXCEPT the rollups, wherever they live."""
    reg = load_registry()
    rollup_ids = _rollup_ids()
    return tuple(sorted(
        c for c, s in reg.items() if s.pillar == pillar and c not in rollup_ids
    ))


def _semantic_subpoints() -> tuple[str, ...]:
    reg = load_registry()
    rollup_ids = _rollup_ids()
    return tuple(sorted(
        c for c, s in reg.items()
        if s.pillar == "on-page" and (s.subcategory or "").startswith("semantic-")
        and c not in rollup_ids
    ))


def _verdict(
    ctx: RollupContext, inputs: tuple[str, ...], *, label: str, low_advice: str
) -> Verdict:
    """Shared body. The dispatcher has already applied the inputs_ran gate, so
    reaching here means enough inputs ran to say something."""
    score, prov = ctx.score_over(inputs)
    ev = {"inputs_declared": len(inputs), **prov}
    if score is None:
        return Verdict("n_a", 0.0, "info", 0.0,
                       {**ev, "reason": f"no measured verdict among the {len(inputs)} "
                                        f"checks {label} aggregates"})
    # A composite is INFORMATIONAL. It restates checks that already reported
    # their own severity; raising an alarm here would double-count them.
    if score >= 8.0:
        return Verdict("pass", score, "info", 0.9, ev)
    if score >= 6.0:
        return Verdict("warn", score, "minor", 0.9, ev, low_advice)
    return Verdict("warn", score, "major", 0.9, ev, low_advice)


def _make(check_id: str, inputs: tuple[str, ...], label: str, advice: str, minimum: int):
    """Register one rollup. Kept as a factory so the twenty-two below read as a
    table rather than twenty-two near-identical function bodies."""

    def _fn(ctx: RollupContext, _i=inputs, _l=label, _a=advice) -> Verdict:
        return _verdict(ctx, _i, label=_l, low_advice=_a)

    # Name it BEFORE registering. The registry records __qualname__ as the
    # check's dotted path, and a factory-made closure reports
    # `rollups._make.<locals>._fn` for all eighteen - which is useless in a
    # coverage sheet and cannot be matched against the checklist.
    _fn.__name__ = f"check_{check_id.lower().replace('-', '_')}"
    _fn.__qualname__ = _fn.__name__
    _fn.__doc__ = f"{check_id} - {label}, over {len(inputs)} declared inputs."
    return rollup(check_id, inputs=inputs, min_inputs_ran=minimum)(_fn)


# --------------------------------------------------------------------------
# On-page
# --------------------------------------------------------------------------

check_on_116 = _make(
    "ON-116", _in_subpoints("on-page", "titles"), "title tag health",
    "Title tags score below target. Titles are the single highest-leverage "
    "on-page element: they are the headline in every search result.", 2)

check_on_117 = _make(
    "ON-117", _in_subpoints("on-page", "meta-description"), "meta tag health",
    "Meta descriptions score below target. They do not rank the page but they "
    "decide whether the result gets clicked.", 2)

check_on_113 = _make(
    "ON-113", _in_subpoints("on-page", "topics", "entities"), "topical relevance",
    "Topical coverage is thin. Depth across related subtopics is what earns a "
    "page authority for a subject rather than a single query.", 3)

check_on_114 = _make(
    "ON-114", _semantic_subpoints(), "semantic SEO",
    "Semantic structure scores below target. Entity clarity and topical "
    "coverage are what let a search engine place the page in a subject.", 4)

check_on_115 = _make(
    "ON-115", _in_subpoints("on-page", "content-quality", "readability"),
    "content quality",
    "Content quality scores below target across depth, readability and "
    "originality.", 4)

check_on_004 = _make(
    "ON-004", _in_subpoints("on-page", "search-intent"), "search intent alignment",
    "The page does not clearly serve one search intent. A page answering "
    "several intents ranks for none of them well.", 2)

check_on_118 = _make(
    "ON-118", _in_pillar("on-page"), "overall on-page SEO",
    "On-page SEO scores below target. The pillar detail lists which subpoints "
    "are dragging it down.", 10)

# --------------------------------------------------------------------------
# Technical
# --------------------------------------------------------------------------

check_tech_101 = _make(
    "TECH-101", _in_pillar("technical"), "overall technical SEO",
    "Technical SEO scores below target. Technical defects cap what every other "
    "improvement can achieve, so these come first.", 10)

# --------------------------------------------------------------------------
# Off-page
# --------------------------------------------------------------------------

check_off_076 = _make(
    "OFF-076", _in_subpoints("off-page", "toxicity", "pbn"), "toxicity risk",
    "Backlink toxicity signals are elevated. Review the flagged domains before "
    "considering a disavow; disavowing healthy links is the more common mistake.", 2)

check_off_077 = _make(
    "OFF-077", _in_subpoints("off-page", "link-quality", "link-attributes"),
    "link quality",
    "Backlink quality scores below target.", 3)

check_off_079 = _make(
    "OFF-079", _in_subpoints("off-page", "brand-signals"), "brand popularity",
    "Brand signals are weak. Branded search volume and unlinked mentions are "
    "what separate a brand from a website.", 3)

check_off_074 = _make(
    "OFF-074", _in_subpoints("off-page", "authority", "backlinks"),
    "authority (composite)",
    "Domain authority signals score below target.", 3)

check_off_078 = _make(
    "OFF-078", _in_subpoints("off-page", "topical-authority", "diversity"),
    "backlink relevance",
    "Backlinks are not topically relevant enough. Relevance now matters more "
    "than raw count.", 2)

check_off_080 = _make(
    "OFF-080", _in_pillar("off-page"), "overall off-page SEO",
    "Off-page SEO scores below target.", 8)

# --------------------------------------------------------------------------
# Local
# --------------------------------------------------------------------------

check_loc_038 = _make(
    "LOC-038", _in_subpoints("local-seo", "gbp"), "Google Business Profile health",
    "The Business Profile is incomplete. It is the single largest local ranking "
    "factor and the cheapest to fix.", 4)

check_loc_039 = _make(
    "LOC-039", _in_subpoints("local-seo", "citations", "nap"), "citation strength",
    "Citation coverage or NAP consistency scores below target. Inconsistent "
    "name, address or phone data across directories dilutes the local signal.", 3)

check_loc_037 = _make(
    "LOC-037", _in_subpoints("local-seo", "local-pack", "reviews"),
    "local prominence",
    "Local prominence scores below target. Prominence is one of Google's three "
    "stated local ranking factors, alongside relevance and distance.", 4)

check_loc_040 = _make(
    "LOC-040", _in_pillar("local-seo"), "overall local SEO",
    "Local SEO scores below target.", 6)


# --------------------------------------------------------------------------
# NOT built, and why.
#
# Four rollups have no input set the checklist can answer for, and guessing one
# would be exactly the kind of invention this module was written to avoid:
#
#   ON-112  "User value score"        - no matching subpoint. Which checks
#                                       constitute "user value" is a product
#                                       decision, not a taxonomy lookup.
#   OFF-072 "Link trust score"        - indistinguishable from OFF-074
#                                       Authority given the current subpoints.
#   OFF-073 "Brand trust score"       - indistinguishable from OFF-079 Brand
#                                       popularity.
#   OFF-075 "Off page SEO score
#            (sub-rollup)"            - a sub-rollup of what? OFF-080 already
#                                       covers the pillar.
#
# These stay ledgered under owner_decision. Building them by picking a
# plausible-looking subpoint would produce a number a client could not trace
# back to anything.
# --------------------------------------------------------------------------
