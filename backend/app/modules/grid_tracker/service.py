"""The pure grid maths: fold a run's probes into the numbers an operator reads.

Pure + deterministic (stdlib only, no network / DB / clock / randomness), exactly like
``app.modules.local_seo.service.rank_delta`` and ``app.services.site_plan`` - so the
statistics are unit-tested against hand-built probe lists rather than against a live
provider.

THE ONE RULE THIS FILE EXISTS TO ENFORCE: **every ratio divides by MEASURED points.**

A grid run has three kinds of point (``0138``'s three-state contract): ranked, absent,
and error - where 'error' means the provider never answered, not that the business was
missing. Dividing by the TOTAL point count silently treats every unmeasured point as a
place the business does not rank:

    17-point grid, 5 probes rate-limited, 6 of the remaining 12 in the top 3
      by total    -> 6/17 = 35% coverage   (wrong, and always pessimistic)
      by measured -> 6/12 = 50% coverage   (true, over what was actually seen)

The first number is not a rounding difference - it is a fabricated decline that gets
worse the flakier the provider is, and it would be charted to a client as lost
visibility. So ``points_error`` is reported as its own count, never folded into a
denominator, and a run that lost any point is ``degraded`` rather than ``completed``
so the number is never read without its caveat.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.grid_tracker.provider import GridProbeResult
from app.modules.local_seo.provider import MAP_PACK_SIZE


@dataclass(frozen=True)
class GridSummary:
    """The derived counters ``0138``'s ``grid_runs`` stores, plus the run's verdict."""

    points_total: int
    points_ranked: int
    points_absent: int
    points_error: int
    #: Mean position over RANKED points only. None when nothing ranked - an absent
    #: business has no position to average, and averaging it as some sentinel (100,
    #: or the pack size) would invent a number the provider never reported.
    avg_rank: float | None
    #: Share of MEASURED points in the top 3. None when NOTHING was measured, which is
    #: different from 0.0 ("measured everywhere, in the pack nowhere").
    share_top3: float | None
    #: 'completed' | 'degraded' | 'failed', matching the job contract's vocabulary.
    status: str
    #: Required by ``0138``'s reason-required CHECK for any non-completed status.
    reason: str

    @property
    def points_measured(self) -> int:
        return self.points_ranked + self.points_absent


def summarize(probes: list[GridProbeResult], *, points_total: int) -> GridSummary:
    """Fold this run's probes into its stored counters and its honest verdict.

    ``points_total`` is the geometry's point count, passed in rather than taken as
    ``len(probes)`` so a run that never got to probe every point still reports the
    size of the grid it was SUPPOSED to cover. A point the worker never reached is
    counted as an error, because "we did not look there" and "we looked and found
    nothing" are the distinction this whole module is built around.
    """
    ranked = [p for p in probes if p.status == "ranked" and p.rank is not None]
    absent = [p for p in probes if p.status == "absent"]
    errored = [p for p in probes if p.status == "error"]

    # Points the worker never reached at all are errors, not absences.
    unreached = max(points_total - len(probes), 0)
    error_count = len(errored) + unreached

    measured = len(ranked) + len(absent)
    avg_rank = (
        round(sum(int(p.rank or 0) for p in ranked) / len(ranked), 1) if ranked else None
    )
    in_pack = sum(1 for p in ranked if int(p.rank or 0) <= MAP_PACK_SIZE)
    share_top3 = round(in_pack / measured, 3) if measured else None

    status, reason = _verdict(measured=measured, error_count=error_count, total=points_total)
    return GridSummary(
        points_total=points_total,
        points_ranked=len(ranked),
        points_absent=len(absent),
        points_error=error_count,
        avg_rank=avg_rank,
        share_top3=share_top3,
        status=status,
        reason=reason,
    )


def _verdict(*, measured: int, error_count: int, total: int) -> tuple[str, str]:
    """The run's terminal state and, when it is not clean, why.

    Three outcomes, and the middle one is the point: a partially-measured grid is a
    USABLE result that must not be presented as a whole one. It is kept (the measured
    points are real observations) and labelled, rather than discarded - discarding it
    would throw away paid probes - and rather than silently completed, which is how a
    half-measured heat map becomes a client-facing claim about a service area.
    """
    if measured == 0:
        return (
            "failed",
            f"no point could be measured: all {error_count} probe(s) failed",
        )
    if error_count:
        return (
            "degraded",
            f"{error_count} of {total} probe(s) could not be measured; every "
            f"percentage below is over the {measured} point(s) actually seen",
        )
    return "completed", ""


def coverage_band(share_top3: float | None) -> str:
    """A share of top-3 coverage as a label the UI can colour a legend by.

    Bands, not a gradient, because an operator acts on "most of the area" vs "a
    pocket" - and because a continuous colour ramp invites reading precision into a
    number derived from as few as 17 probes. ``None`` (nothing measured) is its OWN
    band and must never render as the worst one: no data is not bad data.
    """
    if share_top3 is None:
        return "unmeasured"
    if share_top3 >= 0.75:
        return "strong"
    if share_top3 >= 0.40:
        return "mixed"
    if share_top3 > 0.0:
        return "weak"
    return "absent"
