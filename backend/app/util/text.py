"""Text helpers for building frontend-shaped responses."""

from __future__ import annotations


def initials(name: str) -> str:
    """Two-letter avatar initials from a display name (e.g. "Jane Doe" -> "JD")."""
    parts = name.split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()
