"""The client-facing report.

It is the artefact a client actually reads, so the three honesty rules the API
and the workbook hold are enforced here a THIRD time. Duplication is the point:
a rule that lives in one layer is a rule one refactor away from disappearing from
the document that leaves the building.
"""

from __future__ import annotations

from app.services import audit_report as R


def _rollup(level, key, label, score, ran, applicable, **over):
    row = {
        "level": level, "key": key, "label": label, "score": score,
        "checks_ran": ran, "checks_applicable": applicable, "checks_skipped": applicable - ran,
        "skip_reasons": {}, "findings_open": 0, "instances_open": 0, "pages_affected": 0,
        "pages_crawled": 197, "severity_counts": {}, "url_health_pct": 98.5,
        "basis_hash": "b", "scoring_model_version": "v",
    }
    row.update(over)
    return row


def _finding(**over):
    row = {
        "id": "f1", "check_id": "ON-041", "check_name": "H1 optimization",
        "pillar": "on-page", "subcategory": "Heading structure", "dimension": "onpage",
        "severity": "critical", "locus_kind": "template", "locus_value": "/s/{slug}",
        "instance_count": 42, "pages_affected": 42, "remediation": "Add exactly one H1.",
        "sample_urls": ["https://x.test/a", "https://x.test/b"],
    }
    row.update(over)
    return row


def _doc(**over):
    kw = dict(
        meta={"client_name": "SmileOn", "url": "https://smileon.pk",
              "tier": "Advanced", "generated_at": "25 August 2026"},
        rollups=[
            _rollup("site", "", "Site", 56.4, 160, 363),
            _rollup("dimension", "technical", "Technical", 88.7, 25, 100),
            _rollup("dimension", "strategy", "Strategy", None, 0, 21,
                    skip_reasons={"analyzer_path_unresolved": 21}),
        ],
        findings=[_finding()], pages=[], roadmap=None, roadmap_items=None,
    )
    kw.update(over)
    return R.render(R.ReportInput(**kw))


# ------------------------------------------------------- the three rules

def test_an_unmeasured_dimension_is_never_printed_as_zero():
    doc = _doc()
    assert "not measured" in doc
    # the strategy bar must not be drawn at zero-length-and-coloured as if measured
    assert "ran 0 of 21 checks" in doc


def test_every_score_is_printed_with_the_checks_behind_it():
    doc = _doc()
    assert "ran 25 of 100 checks" in doc
    assert "ran 160 of 363 checks" in doc


def test_no_calendar_date_is_attached_to_a_plan_phase():
    items = [{
        "phase": "p0_30d", "sequence": 1, "title": "Fix H1 - 42 pages",
        "owner_role": "seo_specialist", "exit_criterion": "ON-041 returns pass",
    }]
    doc = _doc(roadmap={"capacity_points_per_month": 40}, roadmap_items=items)
    assert "first 30 days" in doc
    assert "relative windows" in doc
    for month in ("January", "February", "March", "September", "October"):
        assert month not in doc


# ------------------------------------------------------------- the content

def test_a_finding_states_its_blast_radius_and_that_it_is_one_fix():
    doc = _doc()
    assert "42 pages" in doc
    assert "one template: /s/{slug}" in doc
    assert "Add exactly one H1." in doc


def test_a_site_scoped_finding_says_site_wide_not_a_page_count():
    doc = _doc(findings=[_finding(locus_kind="site", instance_count=1,
                                  check_name="Orphan page detection")])
    assert "site-wide" in doc


def test_the_body_is_capped_and_says_where_the_rest_is():
    many = [_finding(id=f"f{i}", check_id=f"ON-{i:03}") for i in range(40)]
    doc = R.render(R.ReportInput(
        meta={}, rollups=[_rollup("site", "", "Site", 50, 10, 10)],
        findings=many, pages=[], top_findings=5))
    assert "35 further issues" in doc
    assert "workbook" in doc


def test_coverage_section_names_why_a_dimension_did_not_run():
    doc = _doc()
    assert "analyzer path unresolved" in doc


# ------------------------------------------------------------- the document

def test_the_document_is_self_contained():
    """No script, no external stylesheet, no font host, no remote image. It has to
    render identically in a browser, in an email, and through a print pass - and
    keep working with no network."""
    doc = _doc()
    assert "<script" not in doc
    assert "<link" not in doc
    assert "@import" not in doc
    # the only external URL permitted is the SVG namespace, which is not fetched
    assert doc.count("http") == doc.count("http://www.w3.org/2000/svg") + doc.count("https://smileon.pk") + doc.count("https://x.test")


def test_rendering_is_deterministic():
    """Regenerating a report a year later must produce the report that was sent."""
    assert _doc() == _doc()


def test_a_decimal_score_from_postgres_does_not_crash_the_charts():
    """Postgres `numeric` arrives as Decimal, which does not mix with the float
    arithmetic every chart does."""
    from decimal import Decimal
    doc = _doc(rollups=[_rollup("site", "", "Site", Decimal("56.4"), 160, 363)])
    assert "56.4" in doc


def test_svg_captions_use_real_characters_not_html_entities():
    """An SVG <text> node does not decode HTML entities, so `&middot;` inside one
    prints literally on the page.

    Scoped to the SVG blocks on purpose: the same entity in an HTML paragraph is
    correct and renders fine, so a document-wide ban would be the wrong rule and
    would fail on prose that is doing nothing wrong.
    """
    import re

    doc = _doc(rollups=[
        _rollup("site", "", "Site", 50, 1, 1),
        _rollup("dimension", "technical", "Technical", 88.7, 25, 100, findings_open=4),
    ])
    for svg in re.findall(r"<svg\b.*?</svg>", doc, flags=re.S):
        found = re.findall(r"&[a-zA-Z]+;", svg)
        assert not found, f"HTML entity inside SVG: {found}"


def test_an_empty_audit_still_produces_a_document():
    doc = R.render(R.ReportInput(meta={}, rollups=[], findings=[], pages=[]))
    assert "<html" in doc and "</html>" in doc
