"""Shared analyzer helpers.

Every analyzer returns (status, score, evidence) tuples or full Finding rows.
The orchestrator wraps these into Finding objects with run_id + check metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Status = Literal["pass", "warn", "fail", "n_a"]
Severity = Literal["critical", "major", "minor", "info"]


@dataclass
class Verdict:
    """One analyzer output before DB persistence."""

    status: Status
    score: float            # 0-10
    severity: Severity
    confidence: float       # 0.0-1.0
    evidence: dict[str, Any]
    remediation: str | None = None
    references: list[str] | None = None


def status_from_score(score: float) -> Status:
    if score >= 9:
        return "pass"
    if score >= 6:
        return "warn"
    if score >= 0:
        return "fail"
    return "n_a"


def length_score(value: int, *, ideal_min: int, ideal_max: int, hard_max: int) -> float:
    """Generic length-band scorer used by titles, meta descriptions, paragraphs.
    Returns 0-10. Below ideal_min or above hard_max scores down; inside the
    ideal band scores 10."""
    if value <= 0:
        return 0.0
    if ideal_min <= value <= ideal_max:
        return 10.0
    if value < ideal_min:
        ratio = value / ideal_min
        return round(ratio * 9, 1)
    # value > ideal_max
    if value <= hard_max:
        # Linear decay from 9 at ideal_max to 5 at hard_max
        return round(9.0 - 4.0 * (value - ideal_max) / max(1, hard_max - ideal_max), 1)
    return 3.0
