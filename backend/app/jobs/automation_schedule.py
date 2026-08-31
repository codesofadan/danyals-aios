"""When an automation is next due.

Pure arithmetic over a schedule and a clock, with no database and no Celery, so the
one thing that decides whether work happens on time is testable without either.

TWO SHAPES, DELIBERATELY. An interval ("every 30 minutes") is what most maintenance
wants and is impossible to get wrong. A cron expression is what a human wants when the
time of day matters - "02:00, because that is when nobody is working". Supporting only
intervals would push people to approximate 3am as "every 86400 seconds from whenever I
happened to press save", which drifts every time the automation is paused.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

#: The floor on interval schedules. The dispatcher ticks once a minute, so anything
#: shorter is a promise the platform cannot keep - and a per-second automation is a
#: self-inflicted outage, not a feature.
MIN_INTERVAL_SECONDS = 60


class InvalidScheduleError(ValueError):
    """The schedule cannot be understood, with a reason worth showing a human."""


#: minute, hour, day-of-month, month, day-of-week - with the range each may take.
_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 6),
)


def _parse_field(spec: str, label: str, low: int, high: int) -> set[int]:
    """One cron field -> the set of values it matches. Supports ``*``, ``*/n``,
    ``a-b``, ``a-b/n`` and comma-separated lists of those."""
    allowed: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise InvalidScheduleError(f"Empty {label} in the schedule.")
        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            if not raw_step.isdigit() or int(raw_step) < 1:
                raise InvalidScheduleError(f"'{raw_step}' is not a valid step for {label}.")
            step = int(raw_step)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise InvalidScheduleError(f"'{part}' is not a valid {label} range.")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise InvalidScheduleError(f"'{part}' is not a valid {label}.")
        if start < low or end > high or start > end:
            raise InvalidScheduleError(
                f"{label} must be between {low} and {high}; got '{part}'."
            )
        allowed.update(range(start, end + 1, step))
    if not allowed:
        raise InvalidScheduleError(f"The {label} field matches nothing.")
    return allowed


def parse_cron(expr: str) -> tuple[set[int], ...]:
    """A 5-field cron expression -> the five sets of values it matches.

    PARSED HERE RATHER THAN BY CELERY'S crontab, which was the first attempt. Celery's
    crontab is bound to the app's configured timezone and computes its next occurrence
    from ITS OWN idea of now, so asking "what comes after this instant" returned an
    answer unrelated to the instant given - a schedule set for 02:00 resolved to
    05:38. This is the function that decides when work happens; it must be a pure
    function of the expression and the reference time, and testable as one.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise InvalidScheduleError(
            "A schedule needs five fields: minute hour day-of-month month day-of-week. "
            f'Got {len(fields)} in "{expr}".'
        )
    return tuple(
        _parse_field(spec, label, low, high)
        for spec, (label, low, high) in zip(fields, _FIELDS, strict=True)
    )


def next_due_interval(seconds: int, *, after: datetime | None = None) -> datetime:
    if seconds < MIN_INTERVAL_SECONDS:
        raise InvalidScheduleError(
            f"The shortest interval is {MIN_INTERVAL_SECONDS} seconds - the dispatcher "
            "runs once a minute, so anything shorter would not be honoured."
        )
    return (after or datetime.now(UTC)) + timedelta(seconds=seconds)


def next_due_cron(expr: str, *, after: datetime | None = None) -> datetime:
    """The next firing time of a cron expression, strictly after ``after``, in UTC.

    Days are skipped a day at a time and only matching days are walked minute by
    minute, so the worst case (29 February) is a few hundred steps rather than the
    half-million a naive minute scan would take on every automation, every tick.
    """
    minutes, hours, doms, months, dows = parse_cron(expr)
    now = (after or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    cursor = now + timedelta(minutes=1)

    # Four years covers every 29-February schedule; beyond that the expression
    # matches nothing real and saying so beats looping.
    horizon = cursor + timedelta(days=366 * 4)
    while cursor <= horizon:
        if cursor.month not in months or not _day_matches(cursor, doms, dows):
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cursor.hour not in hours:
            cursor += timedelta(hours=1)
            cursor = cursor.replace(minute=0)
            continue
        if cursor.minute not in minutes:
            cursor += timedelta(minutes=1)
            continue
        return cursor
    raise InvalidScheduleError(f'"{expr}" never occurs.')


def _day_matches(when: datetime, doms: set[int], dows: set[int]) -> bool:
    """Cron's day rule: when BOTH day-of-month and day-of-week are restricted, either
    matching is enough - which is what every cron implementation does, and what an
    operator who has written cron before expects."""
    dom_restricted = doms != set(range(1, 32))
    dow_restricted = dows != set(range(0, 7))
    # Python's Monday=0 vs cron's Sunday=0.
    dow = (when.weekday() + 1) % 7
    if dom_restricted and dow_restricted:
        return when.day in doms or dow in dows
    if dom_restricted:
        return when.day in doms
    if dow_restricted:
        return dow in dows
    return True


def next_due(
    *,
    schedule_kind: str,
    interval_seconds: int | None,
    cron_expr: str | None,
    after: datetime | None = None,
) -> datetime:
    """The next time an automation with this schedule should run."""
    if schedule_kind == "interval":
        if interval_seconds is None:
            raise InvalidScheduleError("An interval schedule needs an interval.")
        return next_due_interval(interval_seconds, after=after)
    if schedule_kind == "cron":
        if not cron_expr:
            raise InvalidScheduleError("A cron schedule needs an expression.")
        return next_due_cron(cron_expr, after=after)
    raise InvalidScheduleError(f"Unknown schedule kind {schedule_kind!r}.")


def humanize(schedule_kind: str, interval_seconds: int | None, cron_expr: str | None) -> str:
    """A cadence a person can read at a glance, for the row in the manager."""
    if schedule_kind == "cron":
        return f"cron: {cron_expr}"
    if interval_seconds is None:
        return "unscheduled"
    for unit, size in (("day", 86_400), ("hour", 3_600), ("minute", 60)):
        if interval_seconds >= size and interval_seconds % size == 0:
            n = interval_seconds // size
            return f"every {n} {unit}{'s' if n != 1 else ''}"
    return f"every {interval_seconds} seconds"


__all__ = [
    "MIN_INTERVAL_SECONDS",
    "InvalidScheduleError",
    "humanize",
    "next_due",
    "next_due_cron",
    "next_due_interval",
    "parse_cron",
]
