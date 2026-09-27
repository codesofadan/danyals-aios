"""What changed since the last audit: fixed, new, and still there.

WHY THIS IS THE MOST VALUABLE THING THE AUDIT MODULE CAN SAY. An audit answers "what is
wrong". A retainer is renewed on the answer to a different question - "what did you fix" -
and until now the platform could not answer it at all. Two reports side by side is not an
answer; it is homework for the client.

EVERYTHING IT NEEDS ALREADY EXISTED. Migration 0094 keyed a finding on
``(scope_type, scope_key, check_id, fingerprint)`` - an identity that deliberately excludes
the URL, the evidence value, the page id, the run id and the count, precisely so it stays
stable while the site changes - and gave it ``first_seen_audit`` / ``last_seen_audit``. Its
own comment says those columns exist to make a delta possible. Nothing read them. This
module is the read.

THE THREE ANSWERS, and what each one is allowed to claim:

    fixed       present in the earlier run, absent from the later one
    new         absent from the earlier run, present in the later one
    persisting  in both

"Fixed" is the word a client hears as a promise, so it is the one to be careful about: a
cause is only reported fixed when the later run ACTUALLY RAN the check it belongs to.
Otherwise a finding that vanished because we stopped looking - a shallower depth, a lapsed
provider key, an agent that did not fire - would be presented as work completed. That
distinction is the whole reason this takes the two runs' coverage as an input and not just
their findings, and it is kept as its own answer:

    unchecked   present earlier, and the later run did not run that check at all

SCORES ARE THE FRAGILE PART, AND THEY ARE GATED. Two scores are comparable only when the
measurement basis matches (0094's ``basis_hash``: the tier, the check set, the fingerprint
version). A free run against a deep run is two different measurements, and subtracting them
produces a number that describes our configuration rather than the client's site. So a
score delta is emitted only on a basis match, and when it is withheld the reason is
returned in its place. ``url_health_pct`` is always emitted: its denominator is PAGES, not
checks, which is exactly why 0094 introduced it.

Pure: no database, no network, no clock, no model. Two runs' rows in, one comparison out -
so the same pair always yields the same answer, which is what lets a client report quote it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Severity order for "what got worse", worst first.
_SEV_RANK: dict[str, int] = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def _rank(severity: str) -> int:
    return _SEV_RANK.get((severity or "info").lower(), 3)


def identity(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    """The stable identity of a cause: the same four columns 0094 made unique.

    Not the row id: a cause is UPSERTED across runs, so the id is stable for the wrong
    reason (it is the same row) and would break the moment a re-ingest replaced it. Not the
    URL or the count either - both move when the site's content moves rather than when the
    problem does, which is the property the fingerprint was designed to have.
    """
    return (
        str(finding.get("scope_type") or ""),
        str(finding.get("scope_key") or ""),
        str(finding.get("check_id") or ""),
        str(finding.get("fingerprint") or ""),
    )


@dataclass(frozen=True, slots=True)
class ChangedFinding:
    """One cause that appeared, disappeared, or stayed - in the words a report prints."""

    check_id: str
    title: str
    severity: str
    dimension: str
    pages: int
    #: Only for `persisting`: how the blast radius moved (+3 = three more pages).
    pages_delta: int = 0

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "checkId": self.check_id,
            "title": self.title,
            "severity": self.severity,
            "dimension": self.dimension,
            "pages": self.pages,
        }
        if self.pages_delta:
            out["pagesDelta"] = self.pages_delta
        return out


@dataclass(slots=True)
class DimensionDelta:
    """One pillar/dimension's movement, with the honesty gate on its score."""

    key: str
    label: str
    score_before: float | None = None
    score_after: float | None = None
    score_delta: float | None = None
    #: Why a score delta is NOT given, when it is not. Empty when one is.
    score_withheld: str = ""
    health_before: float | None = None
    health_after: float | None = None
    fixed: int = 0
    new: int = 0
    persisting: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "scoreBefore": self.score_before,
            "scoreAfter": self.score_after,
            "scoreDelta": self.score_delta,
            "scoreWithheld": self.score_withheld,
            "healthBefore": self.health_before,
            "healthAfter": self.health_after,
            "fixed": self.fixed,
            "new": self.new,
            "persisting": self.persisting,
        }


@dataclass(slots=True)
class Comparison:
    """The whole answer to "what changed since last time"."""

    comparable: bool = True
    #: Why the SCORES cannot be compared, when they cannot. Findings still are.
    reason: str = ""
    fixed: list[ChangedFinding] = field(default_factory=list)
    new: list[ChangedFinding] = field(default_factory=list)
    persisting: list[ChangedFinding] = field(default_factory=list)
    #: Present before, and the later run never ran that check. NOT fixed.
    unchecked: list[ChangedFinding] = field(default_factory=list)
    dimensions: list[DimensionDelta] = field(default_factory=list)
    score_before: float | None = None
    score_after: float | None = None
    score_delta: float | None = None
    health_before: float | None = None
    health_after: float | None = None

    @property
    def headline(self) -> str:
        """One sentence for the top of a client report, or "" when there is nothing to say."""
        if not (self.fixed or self.new):
            return ""
        parts: list[str] = []
        if self.fixed:
            parts.append(f"{len(self.fixed)} fixed")
        if self.new:
            parts.append(f"{len(self.new)} new")
        if self.persisting:
            parts.append(f"{len(self.persisting)} still open")
        return ", ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "comparable": self.comparable,
            "reason": self.reason,
            "headline": self.headline,
            "counts": {
                "fixed": len(self.fixed),
                "new": len(self.new),
                "persisting": len(self.persisting),
                "unchecked": len(self.unchecked),
            },
            "fixed": [f.as_dict() for f in self.fixed],
            "new": [f.as_dict() for f in self.new],
            "persisting": [f.as_dict() for f in self.persisting],
            "unchecked": [f.as_dict() for f in self.unchecked],
            "dimensions": [d.as_dict() for d in self.dimensions],
            "scoreBefore": self.score_before,
            "scoreAfter": self.score_after,
            "scoreDelta": self.score_delta,
            "healthBefore": self.health_before,
            "healthAfter": self.health_after,
        }


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _changed(finding: dict[str, Any], *, pages_delta: int = 0) -> ChangedFinding:
    return ChangedFinding(
        check_id=str(finding.get("check_id") or ""),
        title=str(finding.get("title") or finding.get("check_id") or ""),
        severity=str(finding.get("severity") or "info"),
        dimension=str(finding.get("dimension") or ""),
        pages=int(finding.get("instance_count") or 0),
        pages_delta=pages_delta,
    )


def compare(
    *,
    before_findings: list[dict[str, Any]],
    after_findings: list[dict[str, Any]],
    before_rollups: list[dict[str, Any]],
    after_rollups: list[dict[str, Any]],
) -> Comparison:
    """Compare two completed audits of the same site.

    ``before`` is the EARLIER run. Findings are compared by stable identity; scores only
    where the measurement basis matches. Nothing here needs the two runs to be adjacent,
    so any two audits of one site can be compared - which is what an operator asks for
    when a client wants "versus January".
    """
    out = Comparison()

    before_by_id = {identity(f): f for f in before_findings}
    after_by_id = {identity(f): f for f in after_findings}

    # Which DIMENSIONS the later run measured. A cause can only be called fixed if the
    # later run actually looked at its dimension; otherwise "it is gone" means "we stopped
    # looking", and reporting that as fixed work is the one lie this feature could tell.
    measured_after = {
        str(r.get("key") or ""): int(r.get("checks_ran") or 0)
        for r in after_rollups
        if r.get("level") == "dimension"
    }

    for fid, finding in before_by_id.items():
        if fid in after_by_id:
            continue
        dimension = str(finding.get("dimension") or "")
        ran = measured_after.get(dimension)
        if ran is not None and ran == 0:
            out.unchecked.append(_changed(finding))
        else:
            out.fixed.append(_changed(finding))

    for fid, finding in after_by_id.items():
        if fid not in before_by_id:
            out.new.append(_changed(finding))
            continue
        was = int(before_by_id[fid].get("instance_count") or 0)
        now = int(finding.get("instance_count") or 0)
        out.persisting.append(_changed(finding, pages_delta=now - was))

    # Worst first, then widest blast radius, then check id - the same order the findings
    # list uses, so a reader moving between the two screens sees one ordering.
    for bucket in (out.fixed, out.new, out.unchecked, out.persisting):
        bucket.sort(key=lambda f: (_rank(f.severity), -f.pages, f.check_id))

    # --- the site-level numbers, with the basis gate --------------------------
    site_before = next((r for r in before_rollups if r.get("level") == "site"), {})
    site_after = next((r for r in after_rollups if r.get("level") == "site"), {})
    basis_before = str(site_before.get("basis_hash") or "")
    basis_after = str(site_after.get("basis_hash") or "")
    same_basis = bool(basis_before) and basis_before == basis_after

    out.score_before = _num(site_before.get("score"))
    out.score_after = _num(site_after.get("score"))
    # Health is ALWAYS comparable: its denominator is pages, not checks (0094).
    out.health_before = _num(site_before.get("url_health_pct"))
    out.health_after = _num(site_after.get("url_health_pct"))

    if same_basis and out.score_before is not None and out.score_after is not None:
        out.score_delta = round(out.score_after - out.score_before, 1)
    else:
        out.comparable = False
        out.reason = (
            "These two runs measured different check sets, so their scores are not "
            "comparable - subtracting them would describe a change in how we looked, not "
            "a change in the site. The fixed and new findings below are unaffected, and "
            "the share of pages with no critical issue is counted over pages rather than "
            "checks, so it is comparable either way."
        )

    # --- per dimension -------------------------------------------------------
    dims_before = {
        str(r.get("key") or ""): r for r in before_rollups if r.get("level") == "dimension"
    }
    dims_after = {
        str(r.get("key") or ""): r for r in after_rollups if r.get("level") == "dimension"
    }
    for dim_key in sorted(set(dims_before) | set(dims_after)):
        b, a = dims_before.get(dim_key, {}), dims_after.get(dim_key, {})
        delta = DimensionDelta(
            key=dim_key,
            label=str(a.get("label") or b.get("label") or dim_key),
            score_before=_num(b.get("score")),
            score_after=_num(a.get("score")),
            health_before=_num(b.get("url_health_pct")),
            health_after=_num(a.get("url_health_pct")),
        )
        dim_basis_ok = (
            str(b.get("basis_hash") or "") == str(a.get("basis_hash") or "")
            and bool(b.get("basis_hash"))
        )
        if dim_basis_ok and delta.score_before is not None and delta.score_after is not None:
            delta.score_delta = round(delta.score_after - delta.score_before, 1)
        elif delta.score_before is not None or delta.score_after is not None:
            delta.score_withheld = "different check sets"
        delta.fixed = sum(1 for f in out.fixed if f.dimension == dim_key)
        delta.new = sum(1 for f in out.new if f.dimension == dim_key)
        delta.persisting = sum(1 for f in out.persisting if f.dimension == dim_key)
        out.dimensions.append(delta)

    return out
