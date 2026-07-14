"""Timestamp formatting for frontend-shaped responses (relative + calendar)."""

from __future__ import annotations

from datetime import UTC, date, datetime


def _as_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def relative_ago(value: datetime | str | None, *, empty: str = "never") -> str:
    """Humanize a past timestamp as "just now" / "5m ago" / "2h ago" / "3d ago"."""
    dt = _as_datetime(value)
    if dt is None:
        return empty
    seconds = (datetime.now(UTC) - dt).total_seconds()
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def format_date(value: date | str | None, *, empty: str = "—") -> str:
    """Format a date as the frontend's "Aug 14, 2026" (default em-dash if unset)."""
    if value is None:
        return empty
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%b %d, %Y")
    dt = _as_datetime(value if isinstance(value, str) else str(value))
    return dt.strftime("%b %d, %Y") if dt else empty


def format_runtime(seconds: int | float | None, *, empty: str = "—") -> str:
    """Format an elapsed wall-clock duration as the frontend's "6m 12s".

    Returns ``empty`` (an em-dash) while a job is still pending (``None`` or a
    negative value). Seconds are zero-padded within a minute ("1m 06s").
    """
    if seconds is None:
        return empty
    total = int(seconds)
    if total < 0:
        return empty
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_when(value: datetime | str | None, *, empty: str = "—") -> str:
    """Format a timestamp as the frontend's "Today · 09:14" / "Jul 08 · 16:10".

    Same calendar day -> "Today", the day before -> "Yesterday", otherwise the
    calendar date ("Jul 08"); always suffixed with 24-hour ``HH:MM`` (UTC).
    """
    dt = _as_datetime(value)
    if dt is None:
        return empty
    now = datetime.now(UTC)
    delta_days = (now.date() - dt.date()).days
    if delta_days == 0:
        day = "Today"
    elif delta_days == 1:
        day = "Yesterday"
    else:
        day = dt.strftime("%b %d")
    return f"{day} · {dt.strftime('%H:%M')}"
