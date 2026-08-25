"""Checks over the Lighthouse audits[] array.

The distinction these tests exist to protect: an audit ABSENT from the response
and an audit that PASSED look identical if you only keep failures. Reporting
the first as the second is exactly the class of lie this audit system exists to
avoid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import psi_detail as pd


@dataclass
class M:
    name: str
    value: float | None = None
    percentile: float | None = None
    unit: str = "ms"
    rating: str | None = None


@dataclass
class PSI:
    url: str = "https://example.com/"
    strategy: str = "mobile"
    lighthouse_scores: dict = field(default_factory=dict)
    field_metrics: list = field(default_factory=list)
    lab_metrics: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    fetch_time: str | None = None
    error: str | None = None
    audits: dict = field(default_factory=dict)


def audit(score=1.0, mode="numeric", items=0, savings=None, display=None):
    return {"score": score, "scoreDisplayMode": mode, "items": items,
            "overallSavingsMs": savings, "overallSavingsBytes": None,
            "displayValue": display, "id": "x", "title": "t", "description": "d",
            "numericValue": savings}


def psi(**kw):
    a = kw.pop("audits", {})
    base = {pd.VIEWPORT[0]: audit(), pd.FONT_SIZE[0]: audit(),
            pd.TAP_TARGETS[0]: audit(), pd.CONTENT_WIDTH[0]: audit()}
    base.update(a)
    return PSI(audits=base, **kw)


ALL = [
    pd.check_render_blocking, pd.check_render_blocking_css, pd.check_render_blocking_js,
    pd.check_unused_css, pd.check_unused_js, pd.check_core_web_vitals,
    pd.check_cwv_seo_impact, pd.check_lcp_element, pd.check_cls_issues, pd.check_inp,
    pd.check_page_speed_impact, pd.check_page_speed_optimization,
    pd.check_mobile_friendliness_technical, pd.check_mobile_friendliness_on_page,
    pd.check_mobile_usability_issues,
]


# --- the contract that matters ---------------------------------------------

@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_no_psi_result_is_n_a(fn):
    v = fn(None)
    assert v.status == "n_a" and v.confidence == 0.0


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_a_psi_error_is_n_a_not_a_failure(fn):
    v = fn(PSI(error="RateLimited: pagespeed 429 rate-limited"))
    assert v.status == "n_a"
    assert not v.remediation


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_an_empty_audits_array_is_n_a(fn):
    assert fn(PSI()).status == "n_a"


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    for p in (None, PSI(error="x"), psi(), psi(lighthouse_scores={"performance": 40})):
        v = fn(p)
        assert v.status in {"pass", "warn", "fail", "n_a"}
        assert 0.0 <= v.score <= 10.0 and 0.0 <= v.confidence <= 1.0
        if v.status == "n_a":
            assert not v.remediation


# --- absent vs passed -------------------------------------------------------

def test_an_absent_audit_is_n_a_not_a_pass():
    """The whole point: silence is not success."""
    v = pd.check_unused_js(psi())          # audits present, but not unused-js
    assert v.status == "n_a"
    assert "ran none of" in v.evidence["reason"]


def test_a_passing_audit_is_a_pass():
    v = pd.check_unused_js(psi(audits={pd.UNUSED_JS[0]: audit(score=1.0)}))
    assert v.status == "pass"


def test_a_not_applicable_audit_is_n_a():
    v = pd.check_unused_js(psi(audits={pd.UNUSED_JS[0]: audit(score=None, mode="notApplicable")}))
    assert v.status == "n_a"
    assert "not applicable" in v.evidence["reason"]


def test_a_failing_audit_reports_its_savings():
    v = pd.check_render_blocking(psi(audits={pd.RENDER_BLOCKING[0]: audit(score=0.2, savings=1800)}))
    assert v.status == "fail" and v.severity == "major"
    assert v.evidence["estimated_savings_ms"] == 1800
    assert "1800 ms" in v.remediation


def test_a_saving_inside_measurement_noise_is_only_a_warning():
    v = pd.check_render_blocking(psi(audits={pd.RENDER_BLOCKING[0]: audit(score=0.3, savings=40)}))
    assert v.status == "warn"
    assert "measurement noise" in v.remediation


def test_css_and_js_render_blocking_say_they_read_one_audit():
    """Lighthouse reports them together; pretending to two measurements would
    double-count the same defect."""
    p = psi(audits={pd.RENDER_BLOCKING[0]: audit(score=0.3, savings=900)})
    for fn, sibling in ((pd.check_render_blocking_css, "TECH-046"),
                        (pd.check_render_blocking_js, "TECH-045")):
        note = fn(p).evidence["note"]
        assert "one render-blocking audit" in note
        assert sibling in note


# --- Core Web Vitals --------------------------------------------------------

def test_cwv_requires_all_three_in_the_good_band():
    """Google's own rule: one poor metric fails the assessment."""
    good = psi(field_metrics=[M("largest_contentful_paint", percentile=2000),
                              M("cumulative_layout_shift", percentile=0.05),
                              M("interaction_to_next_paint", percentile=150)])
    assert pd.check_core_web_vitals(good).status == "pass"

    one_bad = psi(field_metrics=[M("largest_contentful_paint", percentile=2000),
                                 M("cumulative_layout_shift", percentile=0.05),
                                 M("interaction_to_next_paint", percentile=600)])
    v = pd.check_core_web_vitals(one_bad)
    assert v.status == "fail"
    assert v.evidence["failing"] == ["INP 600 ms"]


def test_cwv_confidence_scales_with_how_many_metrics_exist():
    one = psi(field_metrics=[M("largest_contentful_paint", percentile=2000)])
    three = psi(field_metrics=[M("largest_contentful_paint", percentile=2000),
                               M("cumulative_layout_shift", percentile=0.05),
                               M("interaction_to_next_paint", percentile=150)])
    assert pd.check_core_web_vitals(one).confidence < pd.check_core_web_vitals(three).confidence


def test_cwv_with_no_metrics_is_n_a():
    assert pd.check_core_web_vitals(psi()).status == "n_a"


def test_lab_only_data_cannot_assess_the_ranking_signal():
    """Lab numbers do not feed page experience; saying they do would be wrong."""
    v = pd.check_cwv_seo_impact(psi(lab_metrics=[M("largest_contentful_paint", value=2000)]))
    assert v.status == "n_a"
    assert "do not feed the page-experience signal" in v.evidence["reason"]


def test_the_ranking_context_is_stated_rather_than_oversold():
    v = pd.check_cwv_seo_impact(psi(field_metrics=[M("lcp", percentile=1, rating="GOOD")]))
    assert "tie-breaker" in v.evidence["ranking_context"]


def test_poor_field_metrics_fail_the_seo_impact_check():
    v = pd.check_cwv_seo_impact(psi(
        field_metrics=[M("largest_contentful_paint", percentile=5000, rating="POOR")]))
    assert v.status == "fail"
    assert v.evidence["poor"] == ["largest_contentful_paint"]


def test_lcp_element_needs_both_the_element_and_the_measurement():
    assert pd.check_lcp_element(psi()).status == "n_a"
    v = pd.check_lcp_element(psi(audits={pd.LCP_ELEMENT[0]: audit(score=None, items=1)},
                                field_metrics=[M("largest_contentful_paint", percentile=5000)]))
    assert v.status == "fail"
    assert "not lazy-loaded" in v.remediation


def test_cls_bands():
    assert pd.check_cls_issues(psi(field_metrics=[M("cumulative_layout_shift", percentile=0.05)])).status == "pass"
    assert pd.check_cls_issues(psi(field_metrics=[M("cumulative_layout_shift", percentile=0.15)])).status == "warn"
    assert pd.check_cls_issues(psi(field_metrics=[M("cumulative_layout_shift", percentile=0.4)])).status == "fail"


def test_inp_falls_back_to_total_blocking_time_and_says_so():
    v = pd.check_inp(psi(lab_metrics=[M("total_blocking_time", value=900)]))
    assert v.status == "fail"
    assert v.evidence["basis"] == "Total Blocking Time, a lab proxy for INP"
    assert v.confidence < 0.9, "a proxy must be less confident than the real metric"


def test_inp_uses_field_data_when_present():
    v = pd.check_inp(psi(field_metrics=[M("interaction_to_next_paint", percentile=120)]))
    assert v.status == "pass" and v.confidence == 0.9


# --- performance ------------------------------------------------------------

def test_performance_score_names_the_biggest_wins():
    opps = [{"id": "unused-javascript", "title": "Reduce unused JavaScript", "numericValue": 2000},
            {"id": "unused-css-rules", "title": "Reduce unused CSS", "numericValue": 500}]
    v = pd.check_page_speed_impact(psi(lighthouse_scores={"performance": 35}, opportunities=opps))
    assert v.status == "fail"
    assert "Reduce unused JavaScript" in v.remediation


def test_a_good_performance_score_passes():
    assert pd.check_page_speed_impact(psi(lighthouse_scores={"performance": 95})).status == "pass"


def test_opportunities_below_the_reporting_floor_do_not_generate_work():
    opps = [{"id": "x", "title": "t", "numericValue": 30}]
    v = pd.check_page_speed_optimization(psi(opportunities=opps))
    assert v.status == "pass"
    assert "reporting floor" in v.evidence["note"]


def test_large_total_savings_fail():
    opps = [{"id": "a", "title": "A", "numericValue": 4000}]
    v = pd.check_page_speed_optimization(psi(opportunities=opps))
    assert v.status == "fail"
    assert v.evidence["total_estimated_savings_ms"] == 4000


# --- mobile -----------------------------------------------------------------

def test_a_clean_mobile_result_passes():
    assert pd.check_mobile_friendliness_technical(psi()).status == "pass"


def test_a_missing_viewport_is_critical():
    v = pd.check_mobile_friendliness_technical(psi(audits={pd.VIEWPORT[0]: audit(score=0)}))
    assert v.status == "fail" and v.severity == "critical"
    assert "desktop width" in v.remediation


def test_small_tap_targets_are_major_not_critical():
    v = pd.check_mobile_friendliness_technical(psi(audits={pd.TAP_TARGETS[0]: audit(score=0.4)}))
    assert v.status == "warn" and v.severity == "major"


def test_a_desktop_run_cannot_judge_mobile_friendliness():
    v = pd.check_mobile_friendliness_technical(psi(strategy="desktop"))
    assert v.status == "n_a"
    assert "mobile strategy" in v.evidence["reason"]


def test_the_on_page_mobile_check_says_it_shares_the_technical_one():
    v = pd.check_mobile_friendliness_on_page(psi())
    assert "TECH-063" in v.evidence["note"]


def test_mobile_usability_itemises_the_failing_audits():
    p = psi(audits={pd.FONT_SIZE[0]: audit(score=0.2), pd.TAP_TARGETS[0]: audit(score=0.3)})
    v = pd.check_mobile_usability_issues(p)
    assert v.status == "fail"
    assert {r["audit"] for r in v.evidence["failing_audits"]} == {pd.FONT_SIZE[0], pd.TAP_TARGETS[0]}


def test_the_mobile_only_index_is_stated_in_evidence():
    assert "mobile-only" in pd.check_mobile_friendliness_technical(psi()).evidence["context"]


# --------------------------------------------------------------------------
# The canonical metric key.
#
# PageSpeed names one metric three ways. CrUX returns
# LARGEST_CONTENTFUL_PAINT_MS, Lighthouse returns largest-contentful-paint, and
# code matching either one silently misses the other. That is how Largest
# Contentful Paint and Cumulative Layout Shift came to be reported as "not
# measured" on EVERY audit while the response contained both - on the real
# smileon.pk response, an LCP of 7238 ms against a 2500 ms target.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("LARGEST_CONTENTFUL_PAINT_MS", "largest_contentful_paint"),
    ("largest-contentful-paint", "largest_contentful_paint"),
    ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "cumulative_layout_shift"),
    ("cumulative-layout-shift", "cumulative_layout_shift"),
    ("INTERACTION_TO_NEXT_PAINT", "interaction_to_next_paint"),
    ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "experimental_time_to_first_byte"),
    ("total-blocking-time", "total_blocking_time"),
    ("FIRST_CONTENTFUL_PAINT_MS", "first_contentful_paint"),
])
def test_every_shape_of_a_metric_name_collapses_to_one_key(raw, expected):
    from audit_engine.integrations.pagespeed import canonical_metric

    assert canonical_metric(raw) == expected


def test_the_crux_field_shape_is_found_not_silently_missed():
    """The exact regression: a CrUX-shaped name must resolve."""
    p = psi(audits={pd.LCP_ELEMENT[0]: audit(score=None, items=1)},
            field_metrics=[M("LARGEST_CONTENTFUL_PAINT_MS", percentile=7238)])
    v = pd.check_lcp_element(p)
    assert v.status == "fail", "an LCP of 7238 ms was reported as not measured"
    assert v.evidence["lcp_ms"] == 7238


def test_the_lighthouse_lab_shape_is_found_too():
    p = psi(lab_metrics=[M("cumulative-layout-shift", value=0.4)])
    v = pd.check_cls_issues(p)
    assert v.status == "fail"
    assert v.evidence["cls"] == 0.4


def test_cwv_sees_all_three_from_crux_shaped_names():
    p = psi(field_metrics=[
        M("LARGEST_CONTENTFUL_PAINT_MS", percentile=7238),
        M("CUMULATIVE_LAYOUT_SHIFT_SCORE", percentile=0.0),
        M("INTERACTION_TO_NEXT_PAINT", percentile=127),
    ])
    v = pd.check_core_web_vitals(p)
    assert v.evidence["metrics_available"] == 3
    assert v.evidence["failing"] == ["LCP 7238 ms"]
    assert v.status == "fail"


def test_the_legacy_cwv_findings_use_the_same_lookup():
    """extras.iter_cwv_findings had the same bug and must be fixed with it."""
    from audit_engine.analyzers.extras import iter_cwv_findings

    p = psi(field_metrics=[M("LARGEST_CONTENTFUL_PAINT_MS", percentile=7238)])
    by_id = {cid: v for cid, _o, v in iter_cwv_findings(p)}
    assert by_id["TECH-040"].evidence["value"] == 7238.0
    assert by_id["TECH-040"].status == "fail"


# --------------------------------------------------------------------------
# Lighthouse renames and removals.
# --------------------------------------------------------------------------

def test_a_renamed_lighthouse_audit_is_still_found():
    """Lighthouse 12 renamed render-blocking-resources to -insight. A check
    pinned to one id silently stops measuring after an upgrade."""
    p = psi(audits={"render-blocking-insight": audit(score=0.2, savings=900)})
    v = pd.check_render_blocking(p)
    assert v.status == "fail"
    assert v.evidence["audit"] == "render-blocking-insight"


def test_the_older_audit_id_still_works():
    p = psi(audits={"render-blocking-resources": audit(score=0.2, savings=900)})
    assert pd.check_render_blocking(p).evidence["audit"] == "render-blocking-resources"


def test_audits_this_lighthouse_version_removed_are_named():
    """Lighthouse 12 dropped font-size, tap-targets and content-width."""
    p = PSI(audits={"meta-viewport": audit(score=1.0)})
    v = pd.check_mobile_friendliness_technical(p)
    assert set(v.evidence["audits_not_in_this_lighthouse"]) == {
        "font-size", "tap-targets", "content-width"}


def test_no_gradable_mobile_audit_is_n_a_not_a_pass():
    """"No failures found" and "nothing was measured" are different things."""
    p = PSI(audits={"unrelated-audit": audit(score=1.0)})
    v = pd.check_mobile_usability_issues(p)
    assert v.status == "n_a"
    assert v.evidence["audits_graded"] == 0
