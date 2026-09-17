"""Quality gate tests - L1/L2/L3 deterministic behavior."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from audit_engine.quality.gates import (
    l1_self_review,
    l2_critic,
    l3_council,
    run_all_gates,
)


def _f(**kw):
    base = {
        "id": 1,
        "check_id": "ON-001",
        "check_name": "test",
        "page_id": None,
        "owner_agent": "A1",
        "status": "pass",
        "severity": "info",
        "score": 10.0,
        "confidence": 1.0,
        "evidence_json": '{"x":1}',
        "category": "on-page",
        "subcategory": None,
        "remediation": None,
    }
    base.update(kw)
    return base


def test_l1_rejects_score_out_of_range():
    r = l1_self_review([_f(score=12.0)])
    assert r.rejected == 1


def test_l1_rejects_status_score_inconsistency():
    r = l1_self_review([_f(status="fail", score=9.5, severity="critical")])
    assert r.rejected == 1


def test_l1_rejects_critical_pass():
    r = l1_self_review([_f(status="pass", severity="critical")])
    assert r.rejected == 1


def test_l1_rejects_fail_without_evidence():
    r = l1_self_review([_f(id=2, status="fail", severity="major", evidence_json=None, score=2.0)])
    assert r.rejected == 1


def test_l1_downgrades_low_confidence_critical():
    r = l1_self_review([_f(id=3, status="fail", severity="critical", score=0.0, confidence=0.3)])
    assert r.downgraded == 1
    v = r.verdicts[0]
    assert v.new_severity == "major"


def test_l1_flags_low_confidence_non_critical():
    r = l1_self_review([_f(id=4, status="warn", severity="major", score=5.0, confidence=0.3)])
    assert r.flagged_low_confidence == 1


def test_l1_passes_clean_finding():
    r = l1_self_review([_f()])
    assert r.verified == 1


def test_l2_merges_duplicates():
    f1 = _f(id=1)
    f2 = _f(id=2)
    r = l2_critic([f1, f2])
    assert r.merged == 1
    assert r.verified == 1


def test_l3_council_orders_critical_by_score():
    f1 = _f(id=10, status="fail", severity="critical", score=2.0, confidence=1.0, check_id="ON-100")
    f2 = _f(id=11, status="fail", severity="critical", score=0.0, confidence=1.0, check_id="ON-200")
    result = l3_council([f1, f2])
    assert result["candidates"] == 2
    assert result["top"][0]["check_id"] == "ON-200"  # lower score -> higher council_score


def test_run_all_gates_writes_artifacts(tmp_path: Path):
    findings = [
        _f(id=1, status="fail", severity="critical", score=2.0, confidence=1.0),
        _f(id=2, status="fail", severity="critical", score=2.0, confidence=1.0),  # dup
        _f(id=3, status="fail", severity="major", score=4.0, confidence=0.3),     # flagged
    ]
    summary = run_all_gates(findings, out_dir=tmp_path)
    assert (tmp_path / "critic-report.json").exists()
    assert (tmp_path / "findings-validated.json").exists()
    assert summary["totals"]["reviewed"] == 3
