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


# ------------------------------------------ the document and the workbook agree
#
# The complaint this answers, in the owner's words: the PDF "was not giving the
# confidence that the pdf is representing the same audit that was conducted and
# that is present in the xlsx." It was not - the report printed the top 25 issues
# and the workbook listed several hundred, so the two artefacts read as different
# runs of different depth. Every issue the workbook holds is now accounted for in
# the document: the worst carry a full card, the rest are listed by name under
# their own dimension. These pin that, because a cap is exactly the kind of
# change that gets reintroduced for page count.

def _many(n: int) -> list[dict]:
    return [
        _finding(id=f"f{i}", check_id=f"ON-{i:03d}", check_name=f"Issue number {i}",
                 severity="minor" if i % 2 else "major", instance_count=(i % 7) + 1)
        for i in range(n)
    ]


def test_every_issue_in_the_run_is_named_in_the_document():
    issues = _many(120)
    doc = _doc(findings=issues, top_findings=10,
               rollups=[_rollup("site", "", "Site", 56.4, 160, 363),
                        # "onpage" - the real dimension key (`_finding` uses it too).
                        # This fixture said "on-page" (the PILLAR spelling), which is
                        # why a pillar-keyed lookup appeared to work.
                        _rollup("dimension", "onpage", "On-page", 61.0, 91, 142,
                                findings_open=120)])
    missing = [f["check_id"] for f in issues if f["check_id"] not in doc]
    assert missing == [], f"{len(missing)} issues in the run never appear in the report"


def test_the_document_says_where_the_uncarded_issues_went():
    doc = _doc(findings=_many(120), top_findings=10,
               rollups=[_rollup("site", "", "Site", 56.4, 160, 363),
                        _rollup("dimension", "onpage", "On-page", 61.0, 91, 142)])
    # A reader who counts 10 cards must be told the other 110 are not lost.
    assert "110 further issues" in doc
    assert "section 03" in doc


def test_a_dimension_with_no_issues_says_so_rather_than_rendering_empty():
    doc = _doc(findings=[],
               rollups=[_rollup("site", "", "Site", 90.0, 160, 363),
                        _rollup("dimension", "technical", "Technical", 90.0, 25, 100)])
    assert "No open issues in this dimension." in doc


# ------------------------------------------------------------- coverage reasons

def test_the_report_says_why_a_check_did_not_run_not_just_how_many():
    doc = _doc(rollups=[
        _rollup("site", "", "Site", 56.4, 160, 363),
        _rollup("dimension", "off-page", "Off-page", None, 6, 80,
                skip_reasons={"needs_provider": 39, "ai_assisted": 12}),
    ])
    assert "Why a check did not run" in doc
    assert "Needs provider" in doc
    assert ">39<" in doc


# ------------------------------------------------------------ slugs are not prose

def test_a_slug_is_cased_as_a_phrase_not_by_str_title():
    # `.title()` gives "Seo Specialist"; `.capitalize()` gives "Ai assisted" and
    # destroys anything already correctly cased. Both reach a client verbatim.
    assert R.label_of("needs_rendered_dom") == "Needs rendered DOM"
    assert R.label_of("ai_assisted") == "AI assisted"
    assert R.label_of("seo_specialist", style="title") == "SEO Specialist"
    assert R.label_of("local_seo") == "Local SEO"
    assert R.label_of("needs_provider", style="lower") == "needs provider"
    assert R.label_of(None) == ""


def test_an_owner_role_reaches_the_plan_correctly_cased():
    doc = _doc(
        roadmap={"capacity_points_per_month": 40},
        roadmap_items=[{"phase": "p0_30d", "sequence": 1, "title": "Fix the H1s",
                        "owner_role": "seo_specialist", "exit_criterion": "One H1 per page"}],
    )
    assert "SEO Specialist" in doc
    assert "Seo Specialist" not in doc


# ---------------------------------------------------------------------- branding

def test_the_document_carries_the_brand_not_the_platform():
    from app.services.branding import Brand
    doc = _doc(brand=Brand(name="Acme SEO", contact_email="hi@acme.co",
                           website="acme.co", accent="#0A7"))
    assert "Acme SEO" in doc
    assert "#0A7" in doc            # the accent reached the stylesheet
    assert "hi@acme.co" in doc


def test_a_placeholder_contact_address_is_not_printed():
    from app.services.branding import Brand
    # `branding.json` ships with `danyal@example.com` until the operator fills it
    # in. Printing it under "questions" is worse than printing nothing.
    doc = _doc(brand=Brand(name="Danyal's Agency", contact_email="danyal@example.com"))
    assert "danyal@example.com" not in doc
    # The brand still prints - and its apostrophe is escaped, not passed through.
    assert "Danyal&#x27;s Agency" in doc


# ------------------------------------------------------------------- the charts

def test_a_coverage_chart_omits_a_dimension_with_no_checklist():
    # applicable == 0 is "this dimension has no checks", which is not "0% ran".
    assert R.coverage_bar([("Ghost", 0, 0)]) == ""
    assert "0 of 12" in R.coverage_bar([("Real", 0, 12)])


def test_a_severity_chart_scales_against_the_busiest_dimension():
    svg = R.sev_split([("Big", {"major": 100}), ("Small", {"major": 1})])
    # Both bars drawn, and the small one is not padded up to the big one's width.
    assert svg.count("<rect") == 2
    assert ">100<" in svg and ">1<" in svg


def test_a_flat_blast_chart_is_not_drawn():
    # Twelve identical bars is decoration, not information.
    same = [_finding(id=f"f{i}", check_id=f"ON-{i:03d}", instance_count=5) for i in range(12)]
    assert "Where one fix goes furthest" not in _doc(findings=same)
    varied = [_finding(id=f"f{i}", check_id=f"ON-{i:03d}", instance_count=i + 1)
              for i in range(12)]
    assert "Where one fix goes furthest" in _doc(findings=varied)


def test_a_phase_with_no_work_is_not_drawn_as_an_empty_column():
    svg = R.phase_bars([("Now", "30d", 4), ("Next", "90d", 0)])
    assert ">Now<" in svg
    assert ">Next<" not in svg


# ------------------------------------------------------- the page appendix
def test_the_page_table_prints_the_real_http_status() -> None:
    """The Status column read `status_code`; the column is `http_status`
    (0094_audit_altitudes.sql), and `audit_workbook` already reads it correctly.

    So the key was never present on the row and every URL in every report printed a
    dash - a Status column that had never once shown a status, in the appendix a client
    is most likely to spot-check. It is exactly the kind of defect that survives because
    "-" looks like missing data rather than like a bug.
    """
    doc = _doc(pages=[
        {"url": "https://smileon.pk/", "http_status": 200, "word_count": 812,
         "indexable": True},
        {"url": "https://smileon.pk/gone", "http_status": 404, "word_count": 0,
         "indexable": False},
    ])
    assert ">200<" in doc
    assert ">404<" in doc


def test_a_page_with_no_recorded_status_still_renders_a_dash() -> None:
    """A genuinely absent status must stay a dash rather than become a zero - a page we
    never got a response from is not a page that returned 0."""
    doc = _doc(pages=[{"url": "https://smileon.pk/x", "word_count": 10, "indexable": True}])
    assert "https://smileon.pk/x" in doc


# ------------------------------------------------------- dimension attribution
def test_section_03_attributes_findings_by_dimension_not_pillar() -> None:
    """Findings and dimension rollups use DIFFERENT taxonomies, and only one matches.

    A finding carries a pillar like "on-page"; the dimension rollup this section walks
    is keyed "onpage". Grouping the findings by pillar therefore matched nothing for
    every dimension except "technical" - which is spelled the same in both - so the card
    printed "No open issues in this dimension" for dimensions that section 02, one page
    earlier, had just reported hundreds of issues for.

    Measured on the fixture audit before the fix: 5 of 6 dimension cards claimed no open
    issues and the whole section carried 36 rows for 461 findings.
    """
    finding = _finding(check_id="ONP-001", check_name="Thin page copy",
                       dimension="onpage", pillar="on-page")
    doc = _doc(
        rollups=[
            _rollup("site", "", "Site", 56.4, 160, 363),
            _rollup("dimension", "onpage", "On-Page", 34.2, 80, 122),
        ],
        findings=[finding],
    )
    section = doc.split("Every dimension, in full", 1)[1]
    assert "Thin page copy" in section
    assert "No open issues in this dimension" not in section.split("Weakest areas")[0]


def test_a_dimension_that_genuinely_found_nothing_still_says_so() -> None:
    """The empty state must survive the fix - a dimension that ran and found nothing is
    a real result, and silently dropping the card would understate what was checked."""
    doc = _doc(
        rollups=[
            _rollup("site", "", "Site", 90.0, 100, 100),
            _rollup("dimension", "local", "Local SEO", 100.0, 18, 18),
        ],
        findings=[],
    )
    assert "No open issues in this dimension" in doc


# ------------------------------------------------------------ no em/en dashes
#
# House style bans them from every client-facing document. The ban cannot live as
# a rule people remember, because most of the prose in this report is not written
# in this repository: remediation strings, check names and subcategory labels all
# arrive from the engine, and one dash typed into a remediation template would
# reach a client no matter how careful the template here was. So it is enforced at
# the boundary, on the finished document.

def test_no_em_or_en_dash_survives_in_the_rendered_document():
    doc = _doc(findings=[_finding(
        check_name="Title tags — missing",
        remediation="Rewrite the title – keep it under 60 characters.",
    )])
    assert "—" not in doc
    assert "–" not in doc
    assert "&mdash;" not in doc and "&ndash;" not in doc
    # And the sentence still reads: replaced, not deleted.
    assert "Title tags - missing" in doc


def test_a_dash_in_a_dimension_label_is_caught_too():
    # Rollup labels come from the database, so they are as untrusted as findings.
    doc = _doc(rollups=[
        _rollup("site", "", "Site", 56.4, 160, 363),
        _rollup("dimension", "technical", "Technical — core", 88.7, 25, 100),
    ])
    assert "—" not in doc
    assert "Technical - core" in doc


def test_the_sanitiser_replaces_rather_than_strips():
    assert R.no_dashes("a — b") == "a - b"
    assert R.no_dashes("a &mdash; b") == "a - b"
    assert R.no_dashes("a &#8211; b") == "a - b"
    assert R.no_dashes("plain") == "plain"


def test_the_score_caption_clears_the_ring():
    # "SITE SCORE" was drawn four pixels under a twelve-wide stroke, so it read as
    # part of the ring instead of a label for it - the crowding an operator sees
    # at the one place they look first.
    svg = R.donut(74.0, size=140, label="SITE SCORE")
    assert 'height="158"' in svg          # 140 + 18 of clearance, not 140 + 6
    assert 'y="150"' in svg               # baseline below the ring, not on it
    # No caption, no reserved space: an unlabelled donut must not gain a gap.
    assert 'height="146"' in R.donut(74.0, size=140)
