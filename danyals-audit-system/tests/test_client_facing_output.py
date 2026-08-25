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
def test_no_composite_appears_as_an_issue_to_fix(pdf):
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


# --------------------------------------------------------------------------
# EVERY renderer, not just the ones someone listed.
#
# The unit tests proved the renderer correct and the PDF fallback clean, and a
# real run still shipped 1,110 leaks - because three MORE reporters
# (consolidated, html, markdown) each had their own `f"{k}={v}"` flatten. A
# report carried `inputs_declared=15, verdicts_counted=54,
# status_breakdown={"pass": 27, ...}` verbatim.
#
# This sweep finds a renderer nobody remembered to fix.
# --------------------------------------------------------------------------

def _real_evidence_blobs(limit: int = 400) -> list[dict]:
    import json

    out: list[dict] = []
    for findings in RUNS:
        try:
            rows = json.loads(findings.read_text())
        except (ValueError, OSError):  # pragma: no cover
            continue
        rows = rows if isinstance(rows, list) else rows.get("findings", [])
        for row in rows:
            raw = row.get("evidence_json")
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                blob = json.loads(raw)
            except ValueError:
                continue
            if isinstance(blob, dict) and blob:
                out.append(blob)
            if len(out) >= limit:
                return out
    return out


@pytest.mark.skipif(not RUNS, reason="no recorded runs on disk")
def test_every_human_facing_reporter_renders_safely():
    """Each reporter that renders evidence FOR A PERSON, over real evidence."""
    import json

    from audit_engine.reporters import consolidated, html, markdown

    blobs = _real_evidence_blobs()
    assert len(blobs) > 50, f"only {len(blobs)} blobs found; the sweep is too thin"

    renderers = [
        ("consolidated", lambda b: consolidated._evidence_inline(json.dumps(b))),
        ("html", lambda b: html._evidence_summary(json.dumps(b)) or ""),
        # The markdown table is rendered whole, so the assertion covers the row
        # builder rather than a helper it happens to call.
        ("markdown", lambda b: markdown.render_findings_table([{
            "severity": "major", "status": "fail", "check_id": "X-001",
            "check_name": "Example", "score": 3.0, "evidence_json": json.dumps(b),
        }])),
    ]
    for name, render in renderers:
        for blob in blobs:
            out = render(blob) or ""
            assert evidence_is_client_safe(out), f"{name} leaked: {out!r} from {blob!r}"


def test_the_narrative_reporter_is_deliberately_exempt():
    """narrative.py feeds a MODEL, not a client. Raw evidence is correct there,
    and routing it through the client-safe renderer would starve the model of
    the detail it needs to write about the finding."""
    from audit_engine.reporters import narrative

    assert "humanise_evidence" not in narrative.__dict__


# --------------------------------------------------------------------------
# REMEDIATION strings, not just evidence.
#
# `sameAs has 4 entries (Wikidata: False)` shipped in six client artifacts and
# survived every evidence-rendering fix, because it lives in an analyzer's
# remediation text rather than in its evidence dict. A reader sees a field name
# and a Python repr where a sentence should be.
# --------------------------------------------------------------------------

def test_no_analyzer_produces_a_remediation_containing_a_python_repr():
    """Guards the CODE, not the archive.

    An earlier version of this test swept recorded runs, which meant a fixed
    bug could never clear: the artifacts on disk still carry whatever the
    engine emitted the day they were written. Running the analyzers over the
    fixtures asserts what the engine does NOW.
    """
    from audit_engine.analyzers.ai_search import iter_per_page_ai_search
    from audit_engine.analyzers.extras import iter_per_page_extras
    from audit_engine.analyzers.onpage import iter_per_page_checks
    from audit_engine.analyzers.page_tech import check_slug  # noqa: F401 - registers
    from audit_engine.analyzers.semantic_seo import iter_per_page_semantic_seo
    from audit_engine.parsers import html as html_parser

    fixtures = ROOT / "tests" / "fixtures"
    pages = [
        html_parser.parse(f.read_text(), "https://example.com/page")
        for f in sorted(fixtures.glob("*.html"))
    ]
    assert pages, "no HTML fixtures to run the analyzers over"

    offenders: set[str] = set()
    checked = 0
    for page in pages:
        for it in (iter_per_page_checks, iter_per_page_ai_search,
                   iter_per_page_extras, iter_per_page_semantic_seo):
            for cid, *rest in it(page):
                verdict = rest[-1]
                text = (getattr(verdict, "remediation", None) or "").strip()
                if not text:
                    continue
                checked += 1
                if not evidence_is_client_safe(text):
                    offenders.add(f"{cid}: {text[:110]}")
    assert checked > 40, f"only {checked} remediations produced; the sweep is too thin"
    assert not offenders, (
        f"{len(offenders)} analyzers interpolate a repr into client-facing "
        f"remediation: {sorted(offenders)[:5]}"
    )
