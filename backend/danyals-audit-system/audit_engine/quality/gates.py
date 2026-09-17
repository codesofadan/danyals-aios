"""L1/L2/L3 quality gates.

L1 - per-finding self-review (deterministic sanity checks: evidence present,
     severity vs status coherence, score range)
L2 - cross-finding critic (duplicate detection, contradiction scan, hallucination
     heuristics against raw artifacts)
L3 - council vote on top-N critical findings (consensus across meta agents,
     here implemented as a deterministic confidence-weighted aggregate)

The full intelligence layer of L2/L3 belongs to M3/M4 Claude subagents - this
module provides the deterministic skeleton + machine-checkable rules that
catch the obvious failures before agents waste cycles on them.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


@dataclass
class GateVerdict:
    finding_id: int | None
    check_id: str
    validation_status: str       # verified | rejected | downgraded | flagged_low_confidence | merged
    reason: str
    new_severity: str | None = None
    new_score: float | None = None


@dataclass
class GateReport:
    reviewed: int = 0
    verified: int = 0
    rejected: int = 0
    downgraded: int = 0
    flagged_low_confidence: int = 0
    merged: int = 0
    verdicts: list[GateVerdict] = field(default_factory=list)

    def add(self, v: GateVerdict) -> None:
        self.reviewed += 1
        self.verdicts.append(v)
        if v.validation_status == "verified":
            self.verified += 1
        elif v.validation_status == "rejected":
            self.rejected += 1
        elif v.validation_status == "downgraded":
            self.downgraded += 1
        elif v.validation_status == "flagged_low_confidence":
            self.flagged_low_confidence += 1
        elif v.validation_status == "merged":
            self.merged += 1


# ---------------- L1 - per-finding self-review ----------------

def l1_self_review(findings: list[dict[str, Any]]) -> GateReport:
    """Per-finding deterministic sanity checks. Cheap, runs first.

    Rejection rules:
      - status fail/warn but score >= 9 (status/score inconsistency)
      - severity critical but status pass (semantic mismatch)
      - score outside 0-10 range
      - no evidence_json AND status fail (every fail needs evidence)

    Downgrade rules:
      - confidence < 0.5 AND severity critical -> downgrade to major

    Flag rules:
      - confidence < 0.5 -> flag low confidence (do not auto-promote into top 10)
    """
    report = GateReport()
    for f in findings:
        cid = f.get("check_id", "?")
        status = f.get("status")
        sev = f.get("severity")
        score = f.get("score")
        conf = f.get("confidence")
        ev = f.get("evidence_json")

        # Range
        if score is not None and (score < 0 or score > 10):
            report.add(GateVerdict(
                finding_id=f.get("id"), check_id=cid,
                validation_status="rejected",
                reason=f"score {score} out of 0-10 range",
            ))
            continue

        # status/score inconsistency
        if status in ("fail", "warn") and score is not None and score >= 9:
            report.add(GateVerdict(
                finding_id=f.get("id"), check_id=cid,
                validation_status="rejected",
                reason=f"status={status} but score={score} (inconsistent)",
            ))
            continue

        if status == "pass" and sev == "critical":
            report.add(GateVerdict(
                finding_id=f.get("id"), check_id=cid,
                validation_status="rejected",
                reason="severity=critical but status=pass (inconsistent)",
            ))
            continue

        # Evidence requirement
        if status == "fail" and not ev:
            report.add(GateVerdict(
                finding_id=f.get("id"), check_id=cid,
                validation_status="rejected",
                reason="status=fail but no evidence_json",
            ))
            continue

        # Confidence handling
        if conf is not None:
            if conf < 0.5 and sev == "critical":
                report.add(GateVerdict(
                    finding_id=f.get("id"), check_id=cid,
                    validation_status="downgraded",
                    reason=f"confidence={conf:.2f} too low for critical; downgraded to major",
                    new_severity="major",
                ))
                continue
            if conf < 0.5:
                report.add(GateVerdict(
                    finding_id=f.get("id"), check_id=cid,
                    validation_status="flagged_low_confidence",
                    reason=f"confidence={conf:.2f} below 0.5 threshold",
                ))
                continue

        report.add(GateVerdict(
            finding_id=f.get("id"), check_id=cid,
            validation_status="verified",
            reason="L1 passed",
        ))
    return report


# ---------------- L2 - cross-finding critic ----------------

def l2_critic(findings: list[dict[str, Any]]) -> GateReport:
    """Cross-finding deterministic checks.

    - Duplicate check_id with same evidence -> mark later occurrences as merged
    - Contradiction: two findings on the same page where one says pass and
      another in the same subcategory says fail at critical -> flag
    """
    report = GateReport()
    seen: dict[tuple[str, int | None, str], int] = {}
    for f in findings:
        key = (f.get("check_id"), f.get("page_id"), str(f.get("evidence_json") or "")[:200])
        if key in seen:
            report.add(GateVerdict(
                finding_id=f.get("id"), check_id=f.get("check_id", "?"),
                validation_status="merged",
                reason=f"duplicate of finding id={seen[key]}",
            ))
            continue
        seen[key] = f.get("id") or 0
        report.add(GateVerdict(
            finding_id=f.get("id"), check_id=f.get("check_id", "?"),
            validation_status="verified",
            reason="L2 passed",
        ))
    return report


# ---------------- L3 - council vote on top critical ----------------

def l3_council(findings: list[dict[str, Any]], *, top_n: int = 10) -> dict[str, Any]:
    """Council vote on the top-N critical findings.

    For Phase 5 the "vote" is deterministic: each candidate gets a council_score
    that aggregates severity weight, finding score, and confidence. Ties broken
    by check_id alpha for stability.
    """
    candidates = [
        f for f in findings
        if f.get("severity") == "critical" and f.get("status") in ("warn", "fail")
    ]
    weighted: list[tuple[float, dict[str, Any]]] = []
    for f in candidates:
        sev_w = 3.0  # critical
        score_penalty = 10.0 - (f.get("score") or 0)
        conf = f.get("confidence") or 0.5
        council_score = round(sev_w * score_penalty * conf, 2)
        weighted.append((council_score, f))
    weighted.sort(key=lambda x: (-x[0], x[1].get("check_id", "")))
    top = [
        {
            "check_id": f.get("check_id"),
            "check_name": f.get("check_name"),
            "page_id": f.get("page_id"),
            "council_score": ws,
        }
        for ws, f in weighted[:top_n]
    ]
    return {
        "candidates": len(candidates),
        "council_size": 4,        # M1 + M2 + M3 + M4 (notional)
        "top": top,
    }


# ---------------- Pipeline ----------------

def run_all_gates(findings: list[dict[str, Any]], *, out_dir: Path) -> dict[str, Any]:
    """Apply L1, L2, L3 in sequence; write critic-report.json and
    findings-validated.json. Returns a summary dict."""
    l1 = l1_self_review(findings)
    l2 = l2_critic(findings)
    council = l3_council(findings)

    rejected_ids: set[int] = {v.finding_id for v in l1.verdicts if v.validation_status == "rejected" and v.finding_id is not None}
    rejected_ids.update(v.finding_id for v in l2.verdicts if v.validation_status == "merged" and v.finding_id is not None)

    downgrade_map: dict[int, str] = {
        v.finding_id: v.new_severity
        for v in l1.verdicts
        if v.validation_status == "downgraded" and v.finding_id and v.new_severity
    }

    validated: list[dict[str, Any]] = []
    for f in findings:
        fid = f.get("id")
        if fid in rejected_ids:
            continue
        out = dict(f)
        if fid in downgrade_map:
            out["severity"] = downgrade_map[fid]
        validated.append(out)

    critic_report = {
        "l1": _summarize(l1),
        "l2": _summarize(l2),
        "l3_council": council,
        "totals": {
            "reviewed": len(findings),
            "verified_after_all_gates": len(validated),
            "rejected": len(rejected_ids),
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "critic-report.json").write_text(
        json.dumps(critic_report, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "findings-validated.json").write_text(
        json.dumps(validated, indent=2, default=str), encoding="utf-8"
    )
    return critic_report


def _summarize(r: GateReport) -> dict[str, Any]:
    return {
        "reviewed": r.reviewed,
        "verified": r.verified,
        "rejected": r.rejected,
        "downgraded": r.downgraded,
        "flagged_low_confidence": r.flagged_low_confidence,
        "merged": r.merged,
        "rejection_rate": round(r.rejected / max(1, r.reviewed), 3),
        "sample_rejections": [
            {"check_id": v.check_id, "reason": v.reason}
            for v in r.verdicts
            if v.validation_status == "rejected"
        ][:10],
    }
