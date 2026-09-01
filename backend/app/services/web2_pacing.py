"""Publish pacing: when a Web 2.0 property may actually go live (R2-13).

WHY THIS IS A SAFETY CONTROL AND NOT A PREFERENCE. A property is defensible while it
reads as a real, low-volume brand blog. Thirty articles appearing across one client's
properties in an afternoon does not read that way no matter how good each one is: the
PATTERN is the tell, it is independent of the prose, and no content-level check can see
it. The similarity gate stops two properties looking alike; this stops the whole set
looking manufactured.

WHAT IT MEANS FOR THE PRODUCT. The operator still chooses how aggressive to be - that is
their call and the caps are tunable without a deploy. What the system will not do is
pretend an instant 30-property burst is safe. Choosing "publish now" packs the schedule
as tightly as the caps allow and shows the resulting completion date UP FRONT, so the
honest timeline is visible before the campaign is committed rather than discovered
afterwards.

Pure and deterministic: takes the current ledger plus the caps, returns the earliest
lawful slot. No DB, no clock of its own - ``now`` is passed in, so a test can place a
property at any point in a schedule and assert exactly where the next one lands.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class PacingCaps:
    """The agency-policy caps (mirrors ``public.web2_pacing_settings``)."""

    min_interval_same_property_days: int = 7
    min_interval_same_client_platform_h: int = 72
    min_interval_same_client_h: int = 24
    max_publishes_per_client_per_day: int = 1
    max_publishes_per_house_account_day: int = 3
    max_publishes_per_house_account_30d: int = 20
    max_properties_per_house_account: int = 10
    max_properties_per_client_campaign: int = 4
    min_days_between_client_properties: int = 14
    publish_jitter_max_hours: int = 36

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> PacingCaps:
        """Build from the settings row, falling back to the conservative defaults.

        A missing settings row must NOT mean "no limits" - that would turn a failed read
        into an uncapped burst, which is the single worst way for this to fail.
        """
        if not row:
            return cls()
        fields = {f: row[f] for f in cls.__dataclass_fields__ if row.get(f) is not None}
        return cls(**fields)


@dataclass(frozen=True)
class Placement:
    """One prior or planned publish, as the pacing rules see it."""

    published_at: datetime
    web2_id: str = ""
    client_id: str = ""
    platform: str = ""
    account_id: str | None = None
    ownership: str = "per_client"


def _jitter(seed: str, max_hours: int) -> timedelta:
    """A stable 0..max_hours offset for one property.

    Deterministic on the property, not random: a redraft or a retry must not shuffle an
    already-communicated schedule. blake2b rather than ``hash()`` because PYTHONHASHSEED
    is randomised per process, so two workers would otherwise compute different slots for
    the same property.
    """
    if max_hours <= 0:
        return timedelta(0)
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    minutes = int.from_bytes(digest, "big") % (max_hours * 60)
    return timedelta(minutes=minutes)


def earliest_slot(
    *,
    now: datetime,
    caps: PacingCaps,
    client_id: str,
    platform: str,
    web2_id: str,
    account_id: str | None = None,
    ownership: str = "per_client",
    history: Sequence[Placement] = (),
    apply_jitter: bool = True,
) -> datetime:
    """The earliest moment this property may lawfully publish.

    Every rule is expressed as "not before X"; the answer is the latest of them, so
    adding a rule can only ever push a placement later. That direction matters: a bug in
    a new rule delays a publish, it does not release a burst.
    """
    floors = [now]
    same_client = [p for p in history if p.client_id == client_id]

    # Same property: a blog that posts weekly reads as a blog.
    for prior in (p for p in same_client if p.web2_id == web2_id):
        floors.append(prior.published_at + timedelta(days=caps.min_interval_same_property_days))

    # Same client on the same platform.
    for prior in (p for p in same_client if p.platform == platform):
        floors.append(prior.published_at + timedelta(hours=caps.min_interval_same_client_platform_h))

    # Same client anywhere.
    for prior in same_client:
        floors.append(prior.published_at + timedelta(hours=caps.min_interval_same_client_h))

    # Per-client daily ceiling: roll forward past any day already at its limit.
    if caps.max_publishes_per_client_per_day > 0:
        candidate = max(floors)
        for _ in range(370):  # bounded: a year of rolling forward, never an open loop
            day_count = sum(1 for p in same_client if _same_day(p.published_at, candidate))
            if day_count < caps.max_publishes_per_client_per_day:
                break
            candidate = _next_day(candidate)
        floors.append(candidate)

    # House accounts carry their own ceilings: a suspension there costs every client on
    # the account at once, so the shared resource is metered separately.
    if ownership == "house" and account_id:
        on_account = [p for p in history if p.account_id == account_id]
        if caps.max_publishes_per_house_account_day > 0:
            candidate = max(floors)
            for _ in range(370):
                day_count = sum(1 for p in on_account if _same_day(p.published_at, candidate))
                if day_count < caps.max_publishes_per_house_account_day:
                    break
                candidate = _next_day(candidate)
            floors.append(candidate)
        if caps.max_publishes_per_house_account_30d > 0:
            candidate = max(floors)
            for _ in range(24):  # bounded roll-forward in 30-day windows
                window = sum(
                    1 for p in on_account if candidate - p.published_at < timedelta(days=30)
                )
                if window < caps.max_publishes_per_house_account_30d:
                    break
                oldest = min(
                    (p.published_at for p in on_account
                     if candidate - p.published_at < timedelta(days=30)),
                    default=candidate,
                )
                candidate = oldest + timedelta(days=30)
            floors.append(candidate)

    slot = max(floors)
    if apply_jitter:
        slot += _jitter(f"{web2_id}|{client_id}|{platform}", caps.publish_jitter_max_hours)
    return slot


def schedule_campaign(
    *,
    now: datetime,
    caps: PacingCaps,
    client_id: str,
    properties: Sequence[tuple[str, str]],
    history: Sequence[Placement] = (),
    account_for: dict[str, str] | None = None,
    ownership_for: dict[str, str] | None = None,
) -> list[tuple[str, datetime]]:
    """Lay out a whole campaign, one lawful slot per property.

    Each placement is folded into the running history before the next is scheduled, so
    the caps apply WITHIN the campaign and not merely against what was already published.
    Scheduling every property against the same starting ledger is the obvious bug here:
    it would hand thirty properties the identical "earliest" slot and publish them
    together - which is the burst these caps exist to prevent.
    """
    accounts = account_for or {}
    ownerships = ownership_for or {}
    ledger = list(history)
    out: list[tuple[str, datetime]] = []
    for web2_id, platform in properties:
        account_id = accounts.get(web2_id)
        ownership = ownerships.get(web2_id, "per_client")
        slot = earliest_slot(
            now=now, caps=caps, client_id=client_id, platform=platform, web2_id=web2_id,
            account_id=account_id, ownership=ownership, history=ledger,
        )
        out.append((web2_id, slot))
        ledger.append(
            Placement(
                published_at=slot, web2_id=web2_id, client_id=client_id, platform=platform,
                account_id=account_id, ownership=ownership,
            )
        )
    return out


def projected_completion(schedule: Sequence[tuple[str, datetime]]) -> datetime | None:
    """When the last property in a campaign publishes.

    Surfaced in the wizard BEFORE the campaign is committed. A 30-article campaign at one
    publish per client per day genuinely takes about a month, and an operator who learns
    that up front can decide; one who learns it afterwards has been misled by the tool.
    """
    return max((slot for _id, slot in schedule), default=None)


def burst_refusal(
    *, now: datetime, history: Sequence[Placement], caps: PacingCaps
) -> str | None:
    """Why one MORE single property may not be created for this client right now.

    The campaign door caps one request at ``max_properties_per_client_campaign``; the
    single-property door had no cap at all, so calling it N times recreated exactly the
    burst the campaign cap exists to stop. Same ceiling, expressed per rolling window:
    at most the campaign cap within ``min_days_between_client_properties`` days.

    Counts only placements carrying a timestamp (the caller's history already drops
    unstamped drafts), so the cap guards the LIVE footprint; drafting spend is gated
    separately. A future-scheduled placement counts - it is part of the same burst.
    Returns the refusal string, or ``None`` when the property may be created.
    """
    cap = caps.max_properties_per_client_campaign
    if cap <= 0:  # the cap is lifted deliberately (settings), not silently
        return None
    window_days = caps.min_days_between_client_properties
    floor = _utc(now) - timedelta(days=window_days)
    recent = sum(1 for p in history if _utc(p.published_at) >= floor)
    if recent < cap:
        return None
    return (
        f"This client already has {recent} Web 2.0 propert"
        f"{'y' if recent == 1 else 'ies'} placed or scheduled in the last {window_days} "
        f"days - the same ceiling a campaign is held to ({cap} per {window_days} days). "
        "A burst of singles reads exactly like an unpaced campaign. Raise the pacing cap "
        "deliberately in settings if this client genuinely warrants more."
    )


def _same_day(a: datetime, b: datetime) -> bool:
    return _utc(a).date() == _utc(b).date()


def _next_day(value: datetime) -> datetime:
    nxt = _utc(value) + timedelta(days=1)
    return nxt.replace(hour=0, minute=0, second=0, microsecond=0)


def _utc(value: datetime) -> datetime:
    """Normalise to UTC. A naive datetime is TREATED as UTC rather than rejected: these
    values come from Postgres timestamptz and from `datetime.now(UTC)`, and refusing a
    naive one would crash the scheduler over a formatting detail."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
