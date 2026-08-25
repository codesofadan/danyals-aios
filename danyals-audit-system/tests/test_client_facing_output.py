"""Nothing engineering-shaped reaches a client.

The unit tests in test_evidence_text.py prove the RULES. This proves the rules
are actually applied on the path a client's report is built from, against every
run recorded on disk - which is the difference between "the renderer is correct"
and "the report is clean".

Three shapes are refused, each because it shipped:

  * a Python dict repr        "status_breakdown: {'fail': 34, 'warn': 36}"
  * an internal module path   "scorers.aggregator", in a column headed Evidence
  * a leaked repr value       "cache_control: not captured" / "covers_host: False"
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from audit_engine.evidence_text import evidence_is_client_safe

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = sorted((ROOT / "data" / "audits").glob("*/*/findings.json"))


def _pdf_module():
    """Import scripts/generate_audit_pdf.py without installing it as a package."""
    path = ROOT / "scripts" / "generate_audit_pdf.py"
    spec = importlib.util.spec_from_file_location("_gen_audit_pdf", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gen_audit_pdf"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pdf():
    return _pdf_module()


@pytest.mark.skipif(not RUNS, reason="no recorded runs on disk")
def test_no_issue_description_leaks_engineering_shapes(pdf):
    checked = 0
    for findings in RUNS:
        issues = pdf.compute_full_issue_list(findings.parent)
        for issue in issues:
            text = pdf._describe_issue(issue) if hasattr(pdf, "_describe_issue") else ""
            if not text:
                continue
            checked += 1
            assert evidence_is_client_safe(text), (
                f"{issue.get('check_id')} in {findings.parent.name}: {text!r}"
            )
    assert checked > 50, f"only {checked} descriptions rendered; the sweep is too thin"


@pytest.mark.skipif(not RUNS, reason="no recorded runs on disk")
def test_no_issue_description_says_not_captured(pdf):
    """The TECH-053 contradiction: a card whose description said
    "cache_control: not captured" while its own fix said "No Cache-Control,
    Expires, ETag or Last-Modified"."""
    for findings in RUNS:
        for issue in pdf.compute_full_issue_list(findings.parent):
            text = pdf._describe_issue(issue) if hasattr(pdf, "_describe_issue") else ""
            assert "not captured" not in text, f"{issue.get('check_id')}: {text!r}"


@pytest.mark.skipif(not RUNS, reason="no recorded runs on disk")
def test_no_composite_appears_as_an_issue_to_fix(pdf):  # noqa: D401
    """A composite restates checks that already reported their own severity.
    Listing it again double-counts the defect and pads the issue count with
    rows nobody can action - "Overall on-page SEO score" is not a task."""
    for findings in RUNS:
        for issue in pdf.compute_full_issue_list(findings.parent):
            cid = issue.get("check_id", "")
            assert not pdf._is_composite(cid, issue.get("subcategory")), (
                f"{cid} is a composite and must not be an issue card"
            )


@pytest.mark.skipif(not RUNS, reason="no recorded runs on disk")
def test_a_pass_over_a_partial_crawl_is_not_sold_as_working(pdf):
    """"No orphan pages" over a fraction of the site is not the same statement
    as "no orphan pages". It is the one error class a client cannot detect and
    will act on, and "What's working" is the worst place to make it."""
    import json

    for findings in RUNS:
        rows = json.loads(findings.read_text())
        rows = rows if isinstance(rows, list) else rows.get("findings", [])
        partial_names = set()
        for r in rows:
            raw = r.get("evidence_json") or "{}"
            try:
                ev = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("crawl_was_partial") and r.get("status") == "pass":
                partial_names.add((r.get("check_name") or "").strip())
        if not partial_names:
            continue
        passes = pdf._passes_by_dimension(findings.parent)
        shown = {n for names in passes.values() for n in names}
        leaked = partial_names & shown
        assert not leaked, f"{findings.parent.name}: partial-crawl passes shown as working: {leaked}"
