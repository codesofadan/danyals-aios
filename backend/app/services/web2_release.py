"""The release tick: publish approved properties when their pacing slot comes due.

WHY THIS EXISTS SEPARATELY FROM THE PUBLISH WORKER. Approval and publication are the
same moment only for an immediate campaign. For a drip, approval says "yes, and over the
next month" - so something has to notice, later, that a slot has arrived. That is this.

THE SHAPE IS COPIED, NOT INVENTED. The content module already solved exactly this
(`0072_content_schedule.sql` + `dispatch_scheduled_content_publishes`): a nullable due
column, an approval that skips the immediate enqueue when the due time is in the future,
and a sweep that claims due rows `for update skip locked`, clears the marker, and
enqueues. Reusing that shape means the drip scheduler is a known quantity rather than new
machinery, and it inherits the concurrency reasoning that has already been tested there.

THE CAPS ARE RE-CHECKED AT RELEASE, NOT ONLY AT PLANNING. A schedule laid out three weeks
ago does not know what has happened since - another campaign, a manual placement, a
retried publish. A property whose slot has arrived but whose caps would now be breached is
DEFERRED (its slot moves), never published anyway. Deferring is the safe direction: the
worst case is a placement going out later than planned, which is invisible to everyone
except the schedule.

PARKED, DELIBERATELY (owner decision 2026-08-29, recorded at web2_campaign.py's
scheduled_for note): approved campaigns publish immediately, `scheduled_for` stays NULL,
and no beat entry runs `web2_release_due` - beat itself is parked by owner instruction.
This module is the preserved half of that decision, kept tested so re-enabling drip is a
wiring task (a beat entry or a self-rescheduling chain - an OWNER decision), not a
rewrite. Do not delete it as dead code; do not wire it up on your own judgement either.

Pure: takes rows and a clock, returns decisions. The worker performs them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from app.services.web2_pacing import PacingCaps, Placement, earliest_slot

Action = Literal["release", "defer", "skip"]


@dataclass(frozen=True)
class ReleaseDecision:
    """What to do with one due property."""

    web2_id: str
    action: Action
    reason: str = ""
    defer_until: datetime | None = None


@dataclass(frozen=True)
class ReleasePlan:
    """The tick's whole verdict, plus when to look again."""

    decisions: list[ReleaseDecision] = field(default_factory=list)
    next_tick_at: datetime | None = None

    @property
    def released(self) -> list[str]:
        return [d.web2_id for d in self.decisions if d.action == "release"]

    @property
    def deferred(self) -> list[str]:
        return [d.web2_id for d in self.decisions if d.action == "defer"]


def plan_release(
    *,
    now: datetime,
    caps: PacingCaps,
    due_rows: Sequence[dict[str, Any]],
    history: Sequence[Placement] = (),
    upcoming: Sequence[datetime] = (),
) -> ReleasePlan:
    """Decide which due properties may publish right now.

    Each release is folded into the running history before the next row is judged, so a
    tick that finds five due properties for one client does not release all five - the
    per-client daily cap applies WITHIN the tick, not merely against what was already
    published. Getting that wrong would turn a paced campaign into a burst at exactly the
    moment the caps were supposed to bite.
    """
    ledger = list(history)
    decisions: list[ReleaseDecision] = []
    deferred_times: list[datetime] = []

    for row in due_rows:
        web2_id = str(row.get("id") or "")
        if not web2_id:
            continue
        status = str(row.get("status") or "")
        if status != "publishing":
            # Approval moves a row to `publishing`; anything else is not ours to release
            # (already published, rejected, or still awaiting review).
            decisions.append(
                ReleaseDecision(web2_id, "skip", f"status={status or 'unknown'}")
            )
            continue

        client_id = str(row.get("client_id") or "")
        platform = str(row.get("platform") or "")
        account_id = str(row.get("account_id") or "") or None
        ownership = str(row.get("ownership") or "per_client")

        allowed_at = earliest_slot(
            now=now, caps=caps, client_id=client_id, platform=platform, web2_id=web2_id,
            account_id=account_id, ownership=ownership, history=ledger, apply_jitter=False,
        )
        if allowed_at > now:
            decisions.append(
                ReleaseDecision(
                    web2_id, "defer",
                    "pacing caps would be breached if this published now",
                    defer_until=allowed_at,
                )
            )
            deferred_times.append(allowed_at)
            continue

        decisions.append(ReleaseDecision(web2_id, "release"))
        ledger.append(
            Placement(
                published_at=now, web2_id=web2_id, client_id=client_id, platform=platform,
                account_id=account_id, ownership=ownership,
            )
        )

    return ReleasePlan(decisions=decisions, next_tick_at=_next_tick(now, deferred_times, upcoming))


# An hour is the longest a tick will sleep. Not a latency choice - a durability one: a
# multi-day ETA parked on the broker is a message that can be lost to a restart with
# `acks_late`, so the chain re-arms hourly and re-derives the real due time from the DB
# each time. The DB is the schedule; the message is only a nudge.
MAX_TICK_INTERVAL = timedelta(hours=1)
# A floor, so a burst of deferrals cannot spin the tick into a hot loop.
MIN_TICK_INTERVAL = timedelta(minutes=1)


def _next_tick(
    now: datetime, deferred: Sequence[datetime], upcoming: Sequence[datetime]
) -> datetime | None:
    """When the campaign should be looked at again, or ``None`` when nothing is left."""
    candidates = [t for t in (*deferred, *upcoming) if t is not None]
    if not candidates:
        return None
    soonest = min(candidates)
    if soonest <= now + MIN_TICK_INTERVAL:
        return now + MIN_TICK_INTERVAL
    return min(soonest, now + MAX_TICK_INTERVAL)
