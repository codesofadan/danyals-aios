"""The altitude contract: enrichment, the page dimension, and honest coverage.

Every behaviour asserted here traces to something measured on real run
837b75d6 (197 pages, 15,617 findings) and recorded in
``docs/audit/fixtures/README.md``.
"""

from __future__ import annotations

import json

import pytest

from audit_engine import checklist as cl
from audit_engine import emit

ALL_CLASSES = frozenset({"zero", "free_quota", "connection", "billable"})
FREE_CLASSES = frozenset({"zero", "free_quota"})


@pytest.fixture(scope="module")
def registry():
    cl.load_registry.cache_clear()
    return cl.load_registry()


def _finding(check_id, **over):
    base = {
        "check_id": check_id, "check_name": "", "category": "on-page",
        "subcategory": None, "owner_agent": None, "status": "fail",
        "severity": "major", "page_id": 1, "evidence_json": "{}",
    }
    base.update(over)
    return base


# --------------------------------------------------------------- enrichment

def test_a_missing_subpoint_is_filled_from_the_registry(registry):
    """9,653 of 15,617 real findings had no subcategory at all."""
    out, stats = emit.enrich_findings([_finding("LOC-001")])
    assert out[0]["subcategory"] == registry["LOC-001"].subcategory == "gbp"
    assert stats["enriched"] == 1 and stats["corrected"] == 0


def test_a_wrong_subpoint_is_corrected_and_counted(registry):
    """203 real findings carried a value the checklist does not contain
    (``geo-ai`` where the vocabulary says ``ai-search``). Silently keeping it
    would put an unknown key into the report's spine."""
    out, stats = emit.enrich_findings([_finding("LOC-001", subcategory="not-a-real-subpoint")])
    assert out[0]["subcategory"] == "gbp"
    assert stats["corrected"] == 1 and stats["enriched"] == 0


def test_enrichment_adds_the_dimension_and_pillar(registry):
    out, _ = emit.enrich_findings([_finding("LOC-001")])
    assert out[0]["dimension"] == "local"
    assert out[0]["pillar"] == "local-seo"
    assert out[0]["automation"] in {"full", "ai-assisted"}


def test_geo_and_strategy_are_carved_out_by_owning_agent(registry):
    a5 = next(c for c, s in registry.items() if s.owner_agent == "A5")
    m2 = next(c for c, s in registry.items() if s.owner_agent == "M2")
    out, _ = emit.enrich_findings([_finding(a5), _finding(m2)])
    assert out[0]["dimension"] == "geo"
    assert out[1]["dimension"] == "strategy"


def test_an_unknown_check_id_is_counted_not_dropped():
    """Dropping it would make findings disappear between the engine and the
    platform; the count is what makes the drift visible."""
    out, stats = emit.enrich_findings([_finding("XX-999")])
    assert len(out) == 1
    assert stats["unknown_check_id"] == 1
    assert out[0]["dimension"] is None


def test_enrichment_never_loses_or_reorders_a_finding(registry):
    ids = ["LOC-001", "ON-001", "TECH-001", "OFF-001"]
    out, stats = emit.enrich_findings([_finding(i) for i in ids])
    assert [f["check_id"] for f in out] == ids
    assert stats["total"] == 4


def test_enrichment_does_not_mutate_its_input():
    src = [_finding("LOC-001")]
    emit.enrich_findings(src)
    assert src[0]["subcategory"] is None


# ------------------------------------------------------------------- pages

def test_pages_carry_the_url_the_finding_lacks():
    """A finding has page_id and no URL. Without this artifact the per-page
    grain is unrecoverable from the bundle."""
    pages = emit.build_pages([{"id": 7, "url": "https://x.test/a", "http_status": 200}])
    assert pages[0]["page_id"] == 7
    assert pages[0]["url"] == "https://x.test/a"
    # every documented column is present even when the crawler left it null
    for k in ("canonical_url", "page_type", "crawl_depth", "word_count", "indexable"):
        assert k in pages[0]


# ---------------------------------------------------------------- coverage

def test_coverage_spans_the_whole_registry_not_just_what_ran(registry):
    cov = emit.build_coverage(
        [_finding("LOC-001")], dimensions=None, permitted_cost_classes=ALL_CLASSES
    )
    assert cov["registry_total"] == 363
    assert cov["counts"]["planned"] == 363
    assert cov["counts"]["ran"] == 1
    assert cov["counts"]["skipped"] == 362


def test_a_check_that_emitted_a_pass_counts_as_having_run():
    """`pass` is a measurement. Conflating it with "did not run" is the defect
    that lets a skipped provider read as a clean bill of health."""
    cov = emit.build_coverage(
        [_finding("LOC-001", status="pass")],
        dimensions=None, permitted_cost_classes=ALL_CLASSES,
    )
    assert "LOC-001" in cov["ran"]


def test_unselected_dimensions_are_reported_as_such_not_as_failures(registry):
    cov = emit.build_coverage(
        [], dimensions=frozenset({"local"}), permitted_cost_classes=ALL_CLASSES
    )
    assert cov["counts"]["planned"] == 36
    reasons = {s["check_id"]: s["reason"] for s in cov["skipped"]}
    onpage = next(c for c, s in registry.items() if s.dimension == "onpage")
    assert reasons[onpage] == emit.SKIP_NOT_SELECTED


def test_a_check_whose_provider_is_barred_says_so(registry):
    """This is what makes 'we could not check this' different from 'this passed'."""
    cov = emit.build_coverage(
        [], dimensions=None, permitted_cost_classes=FREE_CLASSES
    )
    reasons = {s["check_id"]: s["reason"] for s in cov["skipped"]}
    moz = next(c for c, s in registry.items() if "moz_links" in s.data_sources)
    assert reasons[moz] == emit.SKIP_SOURCE_NOT_PERMITTED
    assert cov["counts"]["planned"] == 193  # the frozen free-tier check set


def test_planned_but_silent_is_its_own_reason(registry):
    """Note the id prefix is NOT the dimension: 4 of the 40 ``LOC-*`` checks are
    owned by M2 and therefore belong to ``strategy``, not ``local``. Selecting
    ``local`` correctly excludes them, which is the carve-out doing its job."""
    cov = emit.build_coverage(
        [], dimensions=frozenset({"local"}), permitted_cost_classes=ALL_CLASSES
    )
    local_ids = {c for c, sp in registry.items() if sp.dimension == "local"}
    reasons = {s["reason"] for s in cov["skipped"] if s["check_id"] in local_ids}
    # A planned check that emitted nothing is reported either as "ran and found
    # nothing" or as "its analyzer declaration does not import" - never as a
    # provider or selection problem, which are different remedies.
    assert reasons <= {emit.SKIP_NO_OUTPUT, emit.SKIP_UNRESOLVED_ANALYZER}
    silent = cov["counts"]["no_output"] + cov["counts"]["analyzer_path_unresolved"]
    assert silent == 36
    # and the M2 checks that live in local.yaml are excluded by SELECTION
    m2_in_local = {
        c for c, sp in registry.items()
        if sp.pillar == "local-seo" and sp.dimension == "strategy"
    }
    assert len(m2_in_local) == 4
    by_id = {s["check_id"]: s["reason"] for s in cov["skipped"]}
    assert all(by_id[c] == emit.SKIP_NOT_SELECTED for c in m2_in_local)


def test_every_check_is_accounted_for_exactly_once(registry):
    """planned-and-ran + skipped must partition the registry. A check that falls
    through both is invisible, which is how coverage lies."""
    cov = emit.build_coverage(
        [_finding("LOC-001")], dimensions=None, permitted_cost_classes=ALL_CLASSES
    )
    seen = set(cov["ran"]) | {s["check_id"] for s in cov["skipped"]}
    assert seen == set(registry)
    assert len(cov["ran"]) + len(cov["skipped"]) == 363


def test_rollups_report_the_denominator_not_only_the_numerator(registry):
    """'ran 25' is not a fact a client can use. 'ran 25 of 100' is."""
    cov = emit.build_coverage(
        [_finding("TECH-001")], dimensions=None, permitted_cost_classes=ALL_CLASSES
    )
    tech = cov["by_dimension"]["technical"]
    assert tech["applicable"] == 100
    assert tech["ran"] == 1
    assert cov["by_pillar"]["technical"]["applicable"] == 101


def test_subpoint_rollup_is_keyed_pillar_slash_subpoint(registry):
    cov = emit.build_coverage([], dimensions=None, permitted_cost_classes=ALL_CLASSES)
    assert "local-seo/gbp" in cov["by_subpoint"]
    assert cov["by_subpoint"]["local-seo/gbp"]["applicable"] == 10
    assert len(cov["by_subpoint"]) == 39 + 30 + 17 + 8


# --------------------------------------------------------------- artifacts

def test_write_altitude_artifacts_produces_all_three(tmp_path):
    paths = emit.write_altitude_artifacts(
        tmp_path,
        findings=[_finding("LOC-001")],
        page_rows=[{"id": 1, "url": "https://x.test/"}],
        dimensions=None,
        permitted_cost_classes=ALL_CLASSES,
    )
    assert set(paths) == {"findings_json", "pages_json", "coverage_json"}
    findings = json.loads(paths["findings_json"].read_text())
    assert findings[0]["subcategory"] == "gbp"
    assert json.loads(paths["pages_json"].read_text())[0]["url"] == "https://x.test/"
    cov = json.loads(paths["coverage_json"].read_text())
    assert cov["enrichment"]["total"] == 1
    assert cov["registry_total"] == 363


def test_artifacts_are_byte_stable_for_the_same_input(tmp_path):
    """Golden-fixture regression needs a stable transform. The engine's own
    evidence is not byte-stable run to run; this layer must not add to that."""
    args = dict(
        findings=[_finding("LOC-001"), _finding("ON-001")],
        page_rows=[{"id": 1, "url": "https://x.test/"}],
        dimensions=None,
        permitted_cost_classes=ALL_CLASSES,
    )
    a = tmp_path / "a"
    b = tmp_path / "b"
    pa = emit.write_altitude_artifacts(a, **args)
    pb = emit.write_altitude_artifacts(b, **args)
    for k in pa:
        assert pa[k].read_bytes() == pb[k].read_bytes(), k


# ------------------------------------------------- analyzer path diagnostics

def test_an_unimportable_analyzer_path_is_reported_separately(registry):
    """"Ran and found nothing" and "there is no code behind this declaration" are
    different facts. Collapsing them tells a client their site was checked when
    it may not have been."""
    cov = emit.build_coverage([], dimensions=None, permitted_cost_classes=ALL_CLASSES)
    reasons = {s["check_id"]: s["reason"] for s in cov["skipped"]}
    unresolved = [c for c, r in reasons.items() if r == emit.SKIP_UNRESOLVED_ANALYZER]
    assert unresolved, "the engine has checks whose analyzer path does not import"
    for cid in unresolved[:5]:
        assert not emit.analyzer_path_resolves(registry[cid].analyzer)


def test_the_path_check_is_not_treated_as_proof_of_implementation():
    """Guard against re-introducing the over-claim: on a real run 160 checks ran
    while only 31 declared paths resolved, so a resolving path is neither
    necessary nor sufficient for a check to work. The reason string must say
    'path unresolved', not 'not implemented'."""
    assert emit.SKIP_UNRESOLVED_ANALYZER == "analyzer_path_unresolved"
    assert "not_implemented" not in emit.SKIP_UNRESOLVED_ANALYZER


def test_an_empty_analyzer_declaration_does_not_resolve():
    assert emit.analyzer_path_resolves("") is False
    assert emit.analyzer_path_resolves("nomodule") is False
    assert emit.analyzer_path_resolves("audit_engine.emit.build_coverage") is True
