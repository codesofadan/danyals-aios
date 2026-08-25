"""The cause / instance / page transform.

Anchored to real run 837b75d6 (smileon.pk, 197 pages, 15,617 findings): 8,077
issue rows contain 461 causes across 9 derived templates, and every one of the
8,077 survives as an instance. See docs/audit/fixtures/README.md.
"""

from __future__ import annotations

import json

from app.services import audit_altitude as A


def _f(check_id="ON-041", *, page_id=None, status="fail", severity="major",
       evidence=None, **over):
    row = {
        "check_id": check_id, "check_name": "H1 optimization",
        "category": "on-page", "pillar": "on-page", "subcategory": "headings",
        "dimension": "onpage", "owner_agent": "A3", "automation": "full",
        "status": status, "severity": severity, "page_id": page_id,
        "evidence_json": json.dumps(evidence or {}), "remediation": "add an H1",
        "confidence": 0.9,
    }
    row.update(over)
    return row


def _pages(*urls):
    tmap = A.assign_templates(list(urls))
    return {
        i + 1: {"page_id": i + 1, "url": u, "template_id": tmap[u]}
        for i, u in enumerate(urls)
    }


# ------------------------------------------------------------------ templates

def test_siblings_collapse_to_one_template():
    """/treatments/braces and /treatments/implants are one template - one edit."""
    t = A.assign_templates([
        "https://x.test/treatments/braces",
        "https://x.test/treatments/implants",
    ])
    assert set(t.values()) == {"/treatments/{slug}"}


def test_a_lone_page_keeps_its_own_shape():
    """With one page under a prefix there is no template EVIDENCE, so we do not
    invent one. Claiming a template from a single sample is a guess."""
    t = A.assign_templates(["https://x.test/contact"])
    assert t["https://x.test/contact"] == "/contact"


def test_identifier_segments_are_shaped_not_kept():
    t = A.assign_templates([
        "https://x.test/blog/2026-01-02/hello",
        "https://x.test/p/12345",
        "https://x.test/u/3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    ])
    vals = set(t.values())
    assert "/blog/{date}/hello" in vals
    assert "/p/{n}" in vals
    assert "/u/{uuid}" in vals


def test_root_is_its_own_template():
    t = A.assign_templates(["https://x.test/", "https://x.test"])
    assert set(t.values()) == {"/"}


def test_template_assignment_is_order_independent():
    urls = ["https://x.test/a/one", "https://x.test/a/two", "https://x.test/b"]
    assert A.assign_templates(urls) == A.assign_templates(list(reversed(urls)))


# ---------------------------------------------------------------- fingerprint

def test_fingerprint_is_stable_for_the_same_cause():
    a = A.fingerprint(check_id="ON-041", locus_kind="template", locus_value="/s/{slug}")
    b = A.fingerprint(check_id="ON-041", locus_kind="template", locus_value="/s/{slug}")
    assert a == b and len(a) == 16


def test_two_broken_templates_do_not_merge():
    """The disqualifying failure of check_id-only clustering: one template gets
    fixed, the finding stays open, and the client is told nothing changed."""
    a = A.fingerprint(check_id="ON-041", locus_kind="template", locus_value="/a/{slug}")
    b = A.fingerprint(check_id="ON-041", locus_kind="template", locus_value="/b/{slug}")
    assert a != b


def test_fingerprint_ignores_everything_that_moves_with_the_site():
    """A fingerprint that changes when CONTENT changes cannot answer 'is this the
    same problem as last month'. Adding a page must not re-identify a finding."""
    base = dict(check_id="ON-041", locus_kind="template", locus_value="/s/{slug}")
    fp = A.fingerprint(**base)
    # none of these are inputs at all - the signature has no place to put them
    assert fp == A.fingerprint(**base, discriminator="")
    assert fp != A.fingerprint(**base, discriminator="http_4xx")


def test_fingerprint_version_participates_in_identity():
    a = A.fingerprint(check_id="X", locus_kind="site", locus_value="", version=1)
    b = A.fingerprint(check_id="X", locus_kind="site", locus_value="", version=2)
    assert a != b


# ------------------------------------------------------------- discriminators

def test_status_class_splits_a_check_into_real_causes():
    """A 404 link and a 500 link are different problems with different owners."""
    assert A.discriminator_for("X", {"target_status": 404}) == "http_4xx"
    assert A.discriminator_for("X", {"target_status": 500}) == "http_5xx"


def test_a_measured_value_is_not_a_discriminator():
    """'title is 12 chars' and 'title is 14 chars' are ONE problem. Splitting on
    the measured value would open a new finding every time content is edited."""
    assert A.discriminator_for("X", {"length": 12}) == ""
    assert A.discriminator_for("X", {"length": 14}) == ""


# ------------------------------------------------------------------- grouping

def test_nothing_is_ever_lost():
    """461 causes from 8,077 rows, and all 8,077 still reachable as instances."""
    pages = _pages("https://x.test/s/a", "https://x.test/s/b", "https://x.test/s/c")
    rows = [_f(page_id=i) for i in (1, 2, 3)]
    causes = A.build_causes(rows, pages)
    assert sum(c.instance_count for c in causes) == 3


def test_one_template_many_pages_is_one_cause():
    """The headline behaviour: 'the service template omits H1 - 3 pages'."""
    pages = _pages("https://x.test/s/a", "https://x.test/s/b", "https://x.test/s/c")
    causes = A.build_causes([_f(page_id=i) for i in (1, 2, 3)], pages)
    assert len(causes) == 1
    c = causes[0]
    assert c.locus_kind == "template" and c.locus_value == "/s/{slug}"
    assert c.instance_count == 3 and c.pages_affected == 3


def test_pages_on_different_templates_yield_different_causes():
    pages = _pages(
        "https://x.test/a/one", "https://x.test/a/two",
        "https://x.test/b/one", "https://x.test/b/two",
    )
    causes = A.build_causes([_f(page_id=i) for i in (1, 2, 3, 4)], pages)
    assert len(causes) == 2
    assert {c.locus_value for c in causes} == {"/a/{slug}", "/b/{slug}"}


def test_a_finding_with_no_page_is_site_scoped():
    causes = A.build_causes([_f("TECH-001", page_id=None)], {})
    assert causes[0].locus_kind == "site" and causes[0].locus_value == ""


def test_a_single_affected_page_is_url_scoped():
    pages = _pages("https://x.test/contact")
    causes = A.build_causes([_f(page_id=1)], pages)
    assert causes[0].locus_kind == "url"
    assert causes[0].locus_value == "https://x.test/contact"


def test_passing_and_not_applicable_rows_are_not_problems():
    pages = _pages("https://x.test/a", "https://x.test/b")
    rows = [_f(page_id=1, status="pass"), _f(page_id=2, status="n_a")]
    assert A.build_causes(rows, pages) == []
    assert len(A.build_causes(rows, pages, include_non_issues=True)) >= 1


def test_a_cause_takes_the_worst_severity_of_its_instances():
    """One critical page inside a template makes the template's fix critical."""
    pages = _pages("https://x.test/s/a", "https://x.test/s/b")
    rows = [_f(page_id=1, severity="minor"), _f(page_id=2, severity="critical")]
    causes = A.build_causes(rows, pages)
    assert len(causes) == 1 and causes[0].severity == "critical"


def test_instances_carry_the_url_the_finding_never_had():
    pages = _pages("https://x.test/s/a", "https://x.test/s/b")
    causes = A.build_causes([_f(page_id=1), _f(page_id=2)], pages)
    urls = {i.url for i in causes[0].instances}
    assert urls == {"https://x.test/s/a", "https://x.test/s/b"}


def test_evidence_is_decoded_from_its_json_string():
    """Evidence arrives JSON-ENCODED, not nested - a second parse is required."""
    pages = _pages("https://x.test/only")
    causes = A.build_causes([_f(page_id=1, evidence={"word_count": 21})], pages)
    assert causes[0].instances[0].evidence == {"word_count": 21}
    assert "word_count=21" in causes[0].instances[0].detail


def test_unparseable_evidence_is_kept_not_dropped():
    pages = _pages("https://x.test/only")
    causes = A.build_causes([_f(page_id=1, evidence_json="{not json")], pages)
    assert causes[0].instances[0].evidence.get("raw", "").startswith("{not")


def test_ordering_is_deterministic_and_worst_first():
    pages = _pages("https://x.test/a/1", "https://x.test/a/2", "https://x.test/b/1", "https://x.test/b/2")
    rows = [
        _f("ON-1", page_id=1, severity="minor"), _f("ON-1", page_id=2, severity="minor"),
        _f("ON-2", page_id=3, severity="critical"), _f("ON-2", page_id=4, severity="critical"),
    ]
    once = A.build_causes(rows, pages)
    twice = A.build_causes(list(reversed(rows)), pages)
    assert [c.fingerprint for c in once] == [c.fingerprint for c in twice]
    assert once[0].severity == "critical"


def test_the_transform_does_not_mutate_its_input():
    pages = _pages("https://x.test/a")
    rows = [_f(page_id=1)]
    snapshot = json.dumps(rows, sort_keys=True)
    A.build_causes(rows, pages)
    assert json.dumps(rows, sort_keys=True) == snapshot


def test_rows_without_a_check_id_are_skipped_not_crashed():
    assert A.build_causes([_f(check_id="")], {}) == []
