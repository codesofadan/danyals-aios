"""The workbook's rules, tested without a database.

The row builders are pure functions over rows, so the shape of the deliverable
can be asserted without Postgres. The end-to-end build is covered in
tests/integration/test_audit_altitudes.py.
"""

from __future__ import annotations

from app.services import audit_workbook as W


def _rollup(level, key, label, score, ran, applicable, **over):
    row = {
        "level": level, "key": key, "label": label, "score": score,
        "checks_ran": ran, "checks_applicable": applicable, "checks_planned": ran,
        "checks_skipped": applicable - ran, "skip_reasons": {},
        "findings_open": 0, "instances_open": 0, "pages_affected": 0,
        "pages_crawled": 10, "severity_counts": {}, "status_counts": {},
        "url_health_pct": None, "basis_hash": "b", "scoring_model_version": "v",
    }
    row.update(over)
    return row


# ------------------------------------------------------- not measured != zero

def test_an_unmeasured_dimension_says_so_instead_of_scoring_zero():
    """Measured on a real run: strategy ran 0 of 21 checks. Printing 0 would tell
    a client their strategy is worthless; printing nothing would hide that we did
    not look."""
    rows = W._pillar_rows([_rollup("dimension", "strategy", "Strategy", None, 0, 21,
                                   skip_reasons={"no_finding_emitted": 21})])
    assert rows[0][1] == W.NOT_MEASURED
    assert rows[0][2] == "0 of 21"
    assert "no_finding_emitted: 21" in rows[0][-1]


def test_a_measured_zero_is_still_a_zero():
    rows = W._pillar_rows([_rollup("dimension", "onpage", "On-Page", 0.0, 5, 5)])
    assert rows[0][1] == 0.0


def test_a_score_never_appears_without_its_coverage():
    """The defect: technical scored 97.2 over 25 of 100 checks. The number and
    its denominator must travel together in every row of every sheet."""
    rows = W._pillar_rows([_rollup("dimension", "technical", "Technical", 97.2, 25, 100)])
    assert rows[0][1] == 97.2
    assert rows[0][2] == "25 of 100"
    assert rows[0][3] == 25 and rows[0][4] == 100


def test_dimensions_render_in_a_fixed_business_order():
    """Not alphabetical: the operator reads on-page and technical first."""
    rollups = [_rollup("dimension", k, k, 50.0, 1, 1)
               for k in ("strategy", "geo", "local", "offpage", "technical", "onpage")]
    assert [r[0] for r in W._pillar_rows(rollups)] == \
        ["onpage", "technical", "offpage", "local", "geo", "strategy"]


def test_subpoints_open_on_the_worst_measured_first_with_unmeasured_last():
    rollups = [
        _rollup("subpoint", "on-page/a", "a", 90.0, 2, 2),
        _rollup("subpoint", "on-page/b", "b", 10.0, 2, 2),
        _rollup("subpoint", "on-page/c", "c", None, 0, 2),
    ]
    scores = [r[2] for r in W._subpoint_rows(rollups)]
    assert scores[0] == 10.0 and scores[1] == 90.0
    assert scores[-1] == W.NOT_MEASURED


def test_only_the_requested_level_is_emitted():
    mixed = [_rollup("site", "", "Site", 50.0, 1, 1),
             _rollup("dimension", "onpage", "On-Page", 50.0, 1, 1),
             _rollup("subpoint", "on-page/x", "x", 50.0, 1, 1)]
    assert len(W._pillar_rows(mixed)) == 1
    assert len(W._subpoint_rows(mixed)) == 1


# --------------------------------------------------------------- the fix list

def _finding(**over):
    row = {
        "id": "abcdef12-0000-0000-0000-000000000000", "check_id": "ON-041",
        "check_name": "H1 optimization", "pillar": "on-page", "subcategory": "headings",
        "dimension": "onpage", "owner_agent": "A3", "automation": "full",
        "severity": "critical", "instance_count": 42, "instances_stored": 42,
        "pages_affected": 42, "locus_kind": "template", "locus_value": "/s/{slug}",
        "remediation": "add an H1", "evidence": {"n": 1},
        "first_seen_at": None, "last_seen_at": None, "fingerprint": "fp123",
    }
    row.update(over)
    return row


def test_a_finding_row_is_one_problem_with_its_page_count():
    """The whole point: one row saying '42 pages', not 42 rows."""
    r = W._finding_rows([_finding()])[0]
    assert r[2] == "H1 optimization"
    assert r[11] == 42            # Instances
    assert r[14] == "template"    # fixing this is ONE edit
    assert r[-1] == "fp123"       # the join key into the nano sheet


def test_a_finding_carries_the_role_that_will_fix_it():
    r = W._finding_rows([_finding()])[0]
    assert r[7] == W.role_for_section("on-page")


def test_instances_stored_is_reported_separately_from_instances_observed():
    """A cap must never masquerade as a smaller problem."""
    r = W._finding_rows([_finding(instance_count=50_000, instances_stored=20_000)])[0]
    assert r[11] == 50_000 and r[12] == 20_000


def test_timestamps_are_strings_because_excel_rejects_tz_aware_datetimes():
    import datetime as dt
    r = W._finding_rows([_finding(last_seen_at=dt.datetime(2026, 8, 24, 12, 0,
                                                           tzinfo=dt.UTC))])[0]
    assert isinstance(r[19], str) and r[19].startswith("2026-08-24")


# --------------------------------------------------------------- the evidence

def test_an_instance_row_joins_back_to_its_cause():
    inst = {
        "fingerprint": "fp123", "check_id": "ON-041", "check_name": "H1",
        "pillar": "on-page", "subcategory": "headings", "dimension": "onpage",
        "severity": "major", "severity_override": "", "url": "https://x.test/a",
        "template_id": "/s/{slug}", "observed": "missing", "detail": "no h1",
        "evidence": {"h1": 0},
    }
    r = W._instance_row(inst)
    assert r[0] == "fp123"
    assert r[7] == "https://x.test/a"


def test_an_instance_severity_override_wins_over_the_causes():
    """A 500 inside a finding whose default is 404 is worse than its parent."""
    inst = {
        "fingerprint": "f", "check_id": "c", "check_name": "n", "pillar": "p",
        "subcategory": "s", "dimension": "d", "severity": "minor",
        "severity_override": "critical", "url": "", "template_id": "",
        "observed": "", "detail": "", "evidence": {},
    }
    assert W._instance_row(inst)[6] == "critical"


# ------------------------------------------------------------------ coverage

def test_the_coverage_sheet_lists_checks_that_did_NOT_run():
    """This is the sheet that stops a skipped check reading like a passing one."""
    coverage = {
        "ran": ["A"],
        "skipped": [{
            "check_id": "B", "reason": "needs_backlink_provider",
            "blocked_on": "O-6",
            "note": "No backlink data is purchased, so this check has nothing to read.",
        }],
        "checks": {
            "A": {"name": "a", "pillar": "on-page", "subcategory": "x",
                  "dimension": "onpage", "owner_agent": "A1", "automation": "full",
                  "severity_default": "major", "cost_classes": ["zero"],
                  "data_sources": ["crawled_html"]},
            "B": {"name": "b", "pillar": "off-page", "subcategory": "y",
                  "dimension": "offpage", "owner_agent": "C1", "automation": "full",
                  "severity_default": "major", "cost_classes": ["billable"],
                  "data_sources": ["moz_links"]},
        },
    }
    rows = W._coverage_rows(coverage)
    assert len(rows) == 2
    by_id = {r[0]: r for r in rows}
    assert by_id["A"][10] == "yes" and by_id["A"][11] == ""
    assert by_id["B"][10] == "no"
    # A SENTENCE, not a slug. "source_not_permitted" is not an explanation a
    # client can act on; "no backlink data is purchased" is.
    assert by_id["B"][11] == "No backlink data is purchased, so this check has nothing to read."
    assert by_id["B"][12] == "O-6"
    # the cost of each check is legible, which is what makes tiering explicable
    assert by_id["B"][8] == "billable"


def test_the_coverage_sheet_falls_back_to_the_slug_for_an_older_artifact():
    """Runs recorded before the ledger was wired carry only a reason string.
    An empty cell would read as "no reason given"."""
    coverage = {
        "ran": [],
        "skipped": [{"check_id": "B", "reason": "source_not_permitted"}],
        "checks": {"B": {"name": "b", "pillar": "off-page", "subcategory": "y",
                         "dimension": "offpage", "owner_agent": "C1",
                         "automation": "full", "severity_default": "major",
                         "cost_classes": ["billable"], "data_sources": ["moz_links"]}},
    }
    row = W._coverage_rows(coverage)[0]
    assert row[11] == "source_not_permitted"
    assert row[12] == ""


def test_the_misleading_analyzer_path_column_is_gone():
    """It reported whether a STALE metadata field imports, which was "no" for
    143 of 363 rows including every check that had just run. A client saw
    "Ran? yes / Analyzer Path Resolves? no" on one row."""
    assert "Analyzer Path Resolves" not in W.COVERAGE_HEADERS
    assert "Why Not" in W.COVERAGE_HEADERS and "Blocked On" in W.COVERAGE_HEADERS


def test_evidence_renders_deterministically():
    """The same evidence always renders the same string.

    This used to assert order-INDEPENDENCE, because the old renderer
    `json.dumps(..., sort_keys=True)`. It no longer sorts: an analyzer writes
    its evidence with the headline measurement first, and sorting scrambles
    that - TECH-039 would lead with "layout shift score" and bury a 7.2s
    largest contentful paint at the end.

    Determinism is what the workbook actually needs (a regenerated file must not
    diff spuriously), and key order is stable per check because each analyzer
    builds its dict from a literal.
    """
    evidence = {"word_count": 21, "response_ms": 315}
    assert W._evidence_text(evidence) == W._evidence_text(dict(evidence))
    assert W._evidence_text(evidence) == "words: 21; server response: 315ms"


def test_evidence_keeps_the_analyzers_ordering():
    """The first key an analyzer wrote is the first thing a client reads."""
    assert W._evidence_text({"lcp_ms": 7238, "cls": 0.0}).startswith(
        "largest contentful paint"
    )


def test_empty_evidence_is_blank_not_the_string_none():
    assert W._evidence_text(None) == ""
    assert W._evidence_text({}) == ""
