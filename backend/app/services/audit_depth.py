"""Audit DEPTH - how much of a site one run crawls, and what that will cost.

``depth`` is its OWN axis, and the platform previously had no name for it. Three
concepts were already being conflated under two words:

* ``tier`` (``free`` | ``paid``) is a SPEND authorisation - it selects the engine
  ``--mode``, i.e. whether any paid provider may fire at all.
* ``types`` (the audit-type picker) SCOPES which dimensions run.
* **breadth** - how many pages the crawl covers - had no per-audit representation
  at all. It came from ONE process-wide setting (``audit_max_pages``), so every
  paid audit in the platform's history crawled whatever that global happened to
  be at the time, and the row does not record what that was.

The recovery plan (§3.2) asks for four tiers: a free lead magnet (~10-15 pages),
a Standard macro health read (~15-20), a Deep run (200-300+, "scaled to actual
site size", "estimated and confirmed before running"), and the type-scoped run.
Type-scoping already existed; free/standard/deep did not. This module is the
missing axis.

**Why the estimate lives here and not as a constant.** The pre-flight cost gate
ran on ``settings.audit_paid_cost_estimate`` - a flat $1.50 regardless of whether
the operator asked for 20 pages or 300, and regardless of whether the AI fan-out
would fire. A 300-page deep run and a 20-page on-page-only run were pre-checked
against the same number, so the gate could not tell the cheap request from the
one twenty times its size. ``estimate_audit_cost`` derives the number instead,
from the SAME ``pricing.audit_cost`` function that computes the COMMITTED cost -
so the estimate and the bill are the same arithmetic over planned vs actual
observables, not two independent guesses that can drift apart.
"""

from __future__ import annotations

from typing import get_args

from app.config import Settings
from app.schemas.audits import AuditDepth
from app.services.pricing import audit_cost

# The vocabulary itself lives in ``app.schemas.audits`` beside ``AuditTier``:
# services import schemas in this tree, never the reverse, and depth is part of
# the wire contract before it is a policy.
DEPTHS: tuple[str, ...] = get_args(AuditDepth)

# Depths that may spend. `free` is the unauthenticated lead magnet and the engine
# hard-clears every paid provider on it; the other two are metered.
METERED_DEPTHS: frozenset[str] = frozenset({"standard", "deep"})

# The one depth the plan requires an operator to CONFIRM a cost estimate for
# before it runs. Standard is a routine check-in and does not interrupt.
CONFIRM_REQUIRED_DEPTHS: frozenset[str] = frozenset({"deep"})

# The depths that switch the AI agent fan-out on. This MIRRORS
# `integrations.audit_engine.DEPTH_SCOPE` - the estimate is only honest if it
# prices the run that will actually be launched, so the two are pinned together
# by `tests/test_audit_depth.py::test_agent_fanout_mirrors_build_argv`.
#
# It replaced a per-type rule. The audit-type picker could not deliver what its
# labels promised (the deterministic crawl always ran in full, so "on-page +
# technical" still returned GEO and strategy findings), so the axis it priced
# was not one the engine could honour.
_AGENT_DEPTHS: frozenset[str] = frozenset({"deep"})


def depth_ceiling(settings: Settings, depth: AuditDepth) -> int:
    """The MOST a run of ``depth`` may ever crawl. A hard bound, never exceeded."""
    if depth == "free":
        return max(1, settings.audit_free_max_pages)
    if depth == "standard":
        return max(1, settings.audit_standard_max_pages)
    return max(1, settings.audit_deep_max_pages)


def planned_pages(
    settings: Settings, depth: AuditDepth, *, measured: int | None = None
) -> int:
    """The crawl breadth one run of ``depth`` will ask the engine for.

    The depth's ceiling, narrowed to the site's MEASURED size when we have one
    (recovery plan §3.2: deep is *"scaled to actual site size"*). The engine
    already stopped at whatever a site actually had, so the committed cost was
    never wrong - what was wrong is that the QUOTE said 300 pages for a 40-page
    site, and the pre-flight gate reserved against that.

    ``measured`` is only ever allowed to narrow, never to widen: a site's own
    sitemap is an input we do not control, so it may not raise a ceiling.

    It is also floored at the STANDARD budget. A sitemap that lists one page (a
    stale file, a deliberate subset, a landing-page-only export) is common, and
    without the floor a deep audit of a real site would silently collapse into a
    one-page crawl that the operator paid a deep price to confirm. Crawling
    slightly more than a tiny sitemap claims costs nothing - the engine stops when
    it runs out of pages.
    """
    ceiling = depth_ceiling(settings, depth)
    if measured is None or measured <= 0 or depth != "deep":
        return ceiling
    floor = max(1, settings.audit_standard_max_pages)
    return max(min(ceiling, measured), min(floor, ceiling))


def agent_fanout_enabled(depth: str | None) -> bool:
    """Whether the engine's 21-agent fan-out fires at this depth.

    Mirrors ``build_argv``: only ``deep`` buys the specialists. The fan-out is the
    dominant cost term, so pricing it wrong is what made the flat estimate useless
    in both directions.
    """
    return (depth or "standard") in _AGENT_DEPTHS


def estimate_audit_cost(
    settings: Settings,
    *,
    mode: str,
    depth: AuditDepth,
    pages: int | None = None,
) -> float:
    """The UPFRONT cost estimate for a run, in USD.

    Derived through ``pricing.audit_cost`` with the PLANNED observables (the
    depth's page budget, the agent count this depth will actually trigger) where
    the committed cost passes the REAL ones. Same arithmetic, so
    an estimate and its bill can be compared meaningfully.

    A ``free`` mode run returns 0.0 for the same reason the committed cost does:
    the engine hard-clears every paid provider, so there is nothing to spend.

    ``pages`` overrides the depth's default budget - the caller has already
    resolved it (from a measured site size, or from the budget a quote was issued
    for and the request echoed back). Passing it keeps the quote and the run that
    is created from it priced off ONE number rather than two computations that can
    disagree.
    """
    if mode == "free":
        return 0.0
    return audit_cost(
        settings,
        pages_crawled=pages if pages is not None and pages > 0 else planned_pages(settings, depth),
        mode="paid",
        agent_calls=settings.audit_agent_calls if agent_fanout_enabled(depth) else 0,
    )
