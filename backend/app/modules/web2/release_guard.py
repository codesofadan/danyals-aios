"""The last admission check before a property goes live: the rules a SCHEDULE cannot hold.

``M05`` REQ-W2-011 / A4: *"Human-plausible intervals, per-platform daily caps, jitter, and
a global rule that no two properties publish in the same minute."* And A4 asserts it under
load: *"no two properties publish within the same minute; per-platform daily caps hold
under a 200-post campaign."*

``web2_pacing`` already lays out a lawful SCHEDULE - intervals per client, per platform,
per house account, with jitter. This module exists because a schedule is a plan and A4 is
about what actually happens, and three things pull those apart:

1. **A tick releases a batch.** ``plan_release`` folds each release into the running
   history, so per-client caps bite within a tick - but nothing stopped the whole batch
   sharing one minute. Ten properties for ten different clients were all lawful and all
   published at 14:03.
2. **A retry re-publishes later than planned.** The schedule said 14:03; the job failed
   and succeeded at 15:07, where something else was already scheduled.
3. **`scheduled_for` is NULL in this deployment.** The owner's 2026-08-29 decision made an
   approved campaign publish immediately, every property at once - which is precisely the
   "ten properties posting in the same minute" footprint §1 names, and the schedule has no
   say because there is no schedule.

So the same-minute rule cannot live in the planner. It has to be an ADMISSION CHECK at the
moment of publishing, judged against what has ALREADY gone out.

WHY THE MINUTE IS THE UNIT. It is not about rate. Two posts a minute apart is the same
volume as two in one second; what differs is that simultaneous publication across
unrelated properties is a machine signature no human schedule produces, and it is visible
in the platforms' own timestamps without anyone analysing content.

Pure: no DB, no clock, no network. The caller supplies what has recently published and
``now``; this decides. That makes every rule testable at the 200-post scale A4 asks about,
which is not something a scheduler with a live database can easily prove.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

#: The window within which two publishes read as simultaneous. A full minute rather than a
#: few seconds because platform timestamps are usually minute-resolution - two posts in the
#: same displayed minute look simultaneous to anyone reading the profiles, whatever the
#: real gap was.
SAME_MINUTE: Final = timedelta(minutes=1)

#: Per-platform daily ceiling (A4's second half). Deliberately separate from
#: ``PacingCaps.max_publishes_per_client_per_day``, which bounds ONE CLIENT's output: this
#: bounds how much the agency posts to ONE PLATFORM across every client, which is the
#: number that platform's own abuse tooling can see.
DEFAULT_PLATFORM_DAILY_CAP: Final = 10

Verdict = Literal["release", "hold"]


@dataclass(frozen=True)
class RecentPublish:
    """One publish that has already happened - the evidence this check judges against."""

    web2_id: str
    platform: str
    published_at: datetime
    client_id: str = ""


@dataclass(frozen=True)
class Admission:
    """Whether this property may publish right now."""

    verdict: Verdict
    reason: str = ""
    #: When to try again. None means "no specific time" - the caller's normal tick cadence
    #: applies. A concrete time lets the release tick re-arm precisely instead of polling.
    retry_after: datetime | None = None

    @property
    def released(self) -> bool:
        return self.verdict == "release"


def admit(
    *,
    web2_id: str,
    platform: str,
    client_id: str = "",
    now: datetime,
    recent: Sequence[RecentPublish],
    platform_daily_cap: int = DEFAULT_PLATFORM_DAILY_CAP,
    already_admitted: Sequence[datetime] = (),
) -> Admission:
    """Decide whether this property may publish at ``now``.

    ``already_admitted`` carries the times this same tick has handed out. Without it a
    batch of ten due properties would each be judged against the DATABASE alone, all find
    the last publish was an hour ago, and all release into one minute - the exact failure
    A4 describes, reproduced by the check meant to prevent it.
    """
    minute_clash = _same_minute_clash(now, recent, already_admitted)
    if minute_clash is not None:
        retry = minute_clash + SAME_MINUTE
        return Admission(
            "hold",
            "another property published in this minute; publishing two at once is a "
            "machine signature visible in the platforms' own timestamps",
            retry_after=retry,
        )

    if platform_daily_cap > 0:
        today = [
            item for item in recent
            if item.platform == platform and _within_day(item.published_at, now)
        ]
        if len(today) >= platform_daily_cap:
            return Admission(
                "hold",
                f"{platform} has taken {len(today)} placements today across all clients "
                f"(cap {platform_daily_cap}); the platform's own abuse tooling sees this "
                "number, not the per-client one",
                retry_after=_next_day(now),
            )

    return Admission("release")


def admit_batch(
    rows: Sequence[dict[str, Any]],
    *,
    now: datetime,
    recent: Sequence[RecentPublish],
    platform_daily_cap: int = DEFAULT_PLATFORM_DAILY_CAP,
    spacing: timedelta = SAME_MINUTE,
) -> list[tuple[str, Admission]]:
    """Admit a whole tick's worth of due properties, spacing them one per minute.

    THE FUNCTION A4 IS ACTUALLY ABOUT. Given 200 due properties this returns 200 verdicts
    in which no two released times share a minute, rather than 200 independent "is now
    free?" answers that all say yes.

    The first row releases now; each subsequent released row is placed at least ``spacing``
    after the previous one. A row that would be pushed past its platform's daily cap holds
    instead of being scheduled into a violation.
    """
    admitted: list[datetime] = []
    per_platform: dict[str, int] = {}
    for item in recent:
        if _within_day(item.published_at, now):
            per_platform[item.platform] = per_platform.get(item.platform, 0) + 1

    results: list[tuple[str, Admission]] = []
    cursor = now
    for row in rows:
        web2_id = str(row.get("id") or "")
        platform = str(row.get("platform") or "")
        if not web2_id:
            continue
        if platform_daily_cap > 0 and per_platform.get(platform, 0) >= platform_daily_cap:
            results.append(
                (
                    web2_id,
                    Admission(
                        "hold",
                        f"{platform} has reached its daily cap of {platform_daily_cap} "
                        "placements across all clients",
                        retry_after=_next_day(now),
                    ),
                )
            )
            continue

        slot = max(cursor, now)
        if admitted and slot - admitted[-1] < spacing:
            slot = admitted[-1] + spacing
        admitted.append(slot)
        per_platform[platform] = per_platform.get(platform, 0) + 1
        cursor = slot + spacing
        results.append(
            (
                web2_id,
                Admission("release", retry_after=None if slot <= now else slot),
            )
        )
    return results


def _same_minute_clash(
    now: datetime, recent: Sequence[RecentPublish], already_admitted: Sequence[datetime]
) -> datetime | None:
    """The most recent publish inside the same-minute window, if any."""
    stamps = [item.published_at for item in recent] + list(already_admitted)
    clashes = [
        stamp for stamp in stamps
        if stamp is not None and abs(_aware(now) - _aware(stamp)) < SAME_MINUTE
    ]
    return max(clashes) if clashes else None


def _within_day(stamp: datetime, now: datetime) -> bool:
    """Whether ``stamp`` falls on the same UTC calendar day as ``now``.

    A calendar day rather than a rolling 24 hours, deliberately: a platform's own rate
    accounting is almost always daily, and a rolling window would hold work at 00:05 for
    something published at 23:55 the night before under a different day's budget.
    """
    return _aware(stamp).date() == _aware(now).date()


def _next_day(now: datetime) -> datetime:
    start = _aware(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return start + timedelta(days=1)


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC rather than raising.

    The ledger has historical rows written before the columns were consistently
    timezone-aware, and a comparison that raises on one of them would stop the release
    tick entirely - a pacing check that halts publishing is a worse failure than one that
    reads an old row as UTC.
    """
    from datetime import UTC

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
