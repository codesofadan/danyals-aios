"""MACRO rollups: the flat score, and the coverage that qualifies it.

Two real defects anchor these tests:
  * run 3055416d scored 58.0 as the mean of two dimensions while two others were
    dropped from the denominator entirely (R4-F6);
  * run 837b75d6 scored technical 97.2 having run 25 of 100 technical checks.
"""

from __future__ import annotations

from app.services import audit_rollups as R
from app.services.audit_altitude import Cause, Instance


def _facts(cid, pillar="technical", sub="crawl", dim="technical", sev="major"):
    return R.CheckFacts(
        id=cid, name=cid, pillar=pillar, subcategory=sub, dimension=dim,
        owner_agent="B1", severity_default=sev, automation="full",
    )


def _registry(*specs):
    return {s.id: s for s in specs}


def _coverage(ran=(), no_output=(), not_permitted=()):
    skipped = [{"check_id": c, "reason": "no_finding_emitted"} for c in no_output]
    skipped += [{"check_id": c, "reason": "source_not_permitted"} for c in not_permitted]
    return {"ran": list(ran), "skipped": skipped, "checks": {}}


def _cause(cid, severity="major", pillar="technical", sub="crawl", dim="technical", urls=()):
    return Cause(
        check_id=cid, check_name=cid, pillar=pillar, subcategory=sub, dimension=dim,
        owner_agent="B1", automation="full", severity=severity, status="open",
        confidence=0.9, locus_kind="template", locus_value="/x/{slug}",
        discriminator="", fingerprint=f"fp-{cid}", remediation="", evidence={},
        instances=[
            Instance(instance_key=u, instance_kind="url", url=u, engine_page_id=None,
                     template_id="/x/{slug}", observed="", expected="", detail="",
                     evidence={}, severity=severity)
            for u in urls
        ],
    )


def _pages(n):
    return [{"page_id": i, "url": f"https://x.test/p{i}"} for i in range(1, n + 1)]


# ------------------------------------------------------- not measured != zero

def test_a_dimension_that_ran_nothing_scores_none_not_zero():
    """The whole defect in one assertion. 0 means 'measured, and terrible'.
    None means 'we did not look'. Conflating them is what let a free audit
    silently drop off-page from the denominator and inflate the composite."""
    reg = _registry(_facts("T1"), _facts("S1", pillar="off-page", sub="authority", dim="offpage"))
    rollups = R.build_rollups(
        causes=[], coverage=_coverage(ran=["T1"], no_output=["S1"]),
        registry=reg, pages=_pages(1),
    )
    by = {(r.level, r.key): r for r in rollups}
    assert by[("dimension", "offpage")].score is None
    assert by[("dimension", "offpage")].checks_ran == 0
    assert by[("dimension", "technical")].score == 100.0  # ran and passed


def test_a_measured_total_failure_scores_zero_not_none():
    reg = _registry(_facts("T1"))
    rollups = R.build_rollups(
        causes=[_cause("T1", urls=["https://x.test/p1"])],
        coverage=_coverage(ran=["T1"]), registry=reg, pages=_pages(1),
    )
    site = next(r for r in rollups if r.level == "site")
    assert site.score == 0.0


# ------------------------------------------------------------ no renormalising

def test_a_pillar_score_is_not_an_average_of_its_subpoints():
    """The pillar is scored over its OWN ran-set with the same formula. If it
    were an average of subpoint scores, a subpoint with one check would weigh as
    much as one with thirty - which is the renormalisation defect wearing a hat."""
    reg = _registry(
        _facts("A1", sub="alpha", sev="critical"),
        _facts("B1", sub="beta"), _facts("B2", sub="beta"), _facts("B3", sub="beta"),
    )
    causes = [_cause("A1", severity="critical", sub="alpha", urls=["https://x.test/p1"])]
    rollups = R.build_rollups(
        causes=causes, coverage=_coverage(ran=["A1", "B1", "B2", "B3"]),
        registry=reg, pages=_pages(1),
    )
    by = {(r.level, r.key): r for r in rollups}
    alpha = by[("subpoint", "technical/alpha")].score   # 1 critical check, failed -> 0
    beta = by[("subpoint", "technical/beta")].score     # 3 major checks, all passed -> 100
    pillar = by[("pillar", "technical")].score
    assert alpha == 0.0 and beta == 100.0
    # mass: ran 3+2+2+2 = 9, failed 3 -> 100*(1-3/9) = 66.7
    assert pillar == 66.7
    assert pillar != round((alpha + beta) / 2, 1)


def test_severity_mass_not_check_count_drives_the_score():
    reg = _registry(_facts("C1", sev="critical"), _facts("I1", sev="info"))
    # fail the info check only: 0.5 of 3.5 mass
    rollups = R.build_rollups(
        causes=[_cause("I1", severity="info", urls=["https://x.test/p1"])],
        coverage=_coverage(ran=["C1", "I1"]), registry=reg, pages=_pages(1),
    )
    site = next(r for r in rollups if r.level == "site")
    assert site.score == 85.7  # 100*(1-0.5/3.5)


# ------------------------------------------------------------------- coverage

def test_every_level_reports_its_denominator():
    """'ran 25' is not usable. 'ran 25 of 100' is. This is the column that stops
    a 97.2 over a quarter of the checklist reading as a clean bill of health."""
    reg = _registry(*[_facts(f"T{i}") for i in range(1, 11)])
    rollups = R.build_rollups(
        causes=[], coverage=_coverage(ran=["T1", "T2"], no_output=[f"T{i}" for i in range(3, 11)]),
        registry=reg, pages=_pages(1),
    )
    tech = next(r for r in rollups if r.level == "dimension" and r.key == "technical")
    assert (tech.checks_applicable, tech.checks_ran, tech.checks_skipped) == (10, 2, 8)


def test_skip_reasons_are_preserved_per_level():
    """'we could not check this' must stay distinguishable from 'this passed'."""
    reg = _registry(_facts("T1"), _facts("T2"), _facts("T3"))
    rollups = R.build_rollups(
        causes=[], coverage=_coverage(ran=["T1"], no_output=["T2"], not_permitted=["T3"]),
        registry=reg, pages=_pages(1),
    )
    tech = next(r for r in rollups if r.level == "dimension")
    assert tech.skip_reasons == {"no_finding_emitted": 1, "source_not_permitted": 1}


def test_checks_are_partitioned_ran_plus_skipped_equals_applicable():
    reg = _registry(*[_facts(f"T{i}") for i in range(1, 6)])
    rollups = R.build_rollups(
        causes=[], coverage=_coverage(ran=["T1"], no_output=["T2", "T3"], not_permitted=["T4", "T5"]),
        registry=reg, pages=_pages(1),
    )
    for r in rollups:
        assert r.checks_ran + r.checks_skipped == r.checks_applicable


# ----------------------------------------------------------------- basis hash

def test_basis_changes_when_the_check_set_changes():
    """A lapsed provider key changes what ran. That must change the basis, not
    silently move the score along an existing trend line."""
    a = R.compute_basis_hash(tier="paid", types=[], checks_ran=["A", "B"], fingerprint_version=1)
    b = R.compute_basis_hash(tier="paid", types=[], checks_ran=["A"], fingerprint_version=1)
    assert a != b


def test_basis_is_order_independent_but_tier_sensitive():
    a = R.compute_basis_hash(tier="paid", types=["a", "b"], checks_ran=["X", "Y"], fingerprint_version=1)
    b = R.compute_basis_hash(tier="paid", types=["b", "a"], checks_ran=["Y", "X"], fingerprint_version=1)
    c = R.compute_basis_hash(tier="free", types=["a", "b"], checks_ran=["X", "Y"], fingerprint_version=1)
    assert a == b and a != c


def test_every_rollup_row_carries_the_same_basis():
    reg = _registry(_facts("T1"), _facts("O1", pillar="off-page", sub="authority", dim="offpage"))
    rollups = R.build_rollups(causes=[], coverage=_coverage(ran=["T1"]), registry=reg, pages=_pages(1))
    assert len({r.basis_hash for r in rollups}) == 1


# ------------------------------------------------------------- url health pct

def test_health_counts_critical_only_and_is_denominated_in_pages():
    """Measured on real data: including `major` returned 0.0% on a 197-page site
    because every page carried a major finding, so the metric said nothing."""
    reg = _registry(_facts("C1", sev="critical"), _facts("M1"))
    causes = [
        _cause("C1", severity="critical", urls=["https://x.test/p1"]),
        _cause("M1", severity="major", urls=[f"https://x.test/p{i}" for i in range(1, 11)]),
    ]
    rollups = R.build_rollups(
        causes=causes, coverage=_coverage(ran=["C1", "M1"]), registry=reg, pages=_pages(10),
    )
    site = next(r for r in rollups if r.level == "site")
    assert site.url_health_pct == 90.0   # 1 of 10 pages has a critical


def test_health_is_only_reported_at_site_level():
    reg = _registry(_facts("T1"))
    rollups = R.build_rollups(causes=[], coverage=_coverage(ran=["T1"]), registry=reg, pages=_pages(4))
    for r in rollups:
        if r.level != "site":
            assert r.url_health_pct is None


def test_health_is_none_when_nothing_was_crawled():
    reg = _registry(_facts("T1"))
    rollups = R.build_rollups(causes=[], coverage=_coverage(ran=["T1"]), registry=reg, pages=[])
    assert next(r for r in rollups if r.level == "site").url_health_pct is None


# ----------------------------------------------------------------- structure

def test_all_four_levels_are_emitted():
    reg = _registry(_facts("T1"))
    levels = {r.level for r in R.build_rollups(
        causes=[], coverage=_coverage(ran=["T1"]), registry=reg, pages=_pages(1))}
    assert levels == {"site", "dimension", "pillar", "subpoint"}


def test_rollups_are_deterministic():
    reg = _registry(_facts("T1"), _facts("O1", pillar="off-page", sub="authority", dim="offpage"))
    args = dict(causes=[_cause("T1", urls=["https://x.test/p1"])],
                coverage=_coverage(ran=["T1", "O1"]), registry=reg, pages=_pages(2))
    a = R.build_rollups(**args)
    b = R.build_rollups(**args)
    assert [(r.level, r.key, r.score) for r in a] == [(r.level, r.key, r.score) for r in b]


def test_instances_are_summed_not_findings_only():
    """The macro row must know it is describing 8,077 occurrences of 461 problems."""
    reg = _registry(_facts("T1"))
    c = _cause("T1", urls=[f"https://x.test/p{i}" for i in range(1, 6)])
    rollups = R.build_rollups(causes=[c], coverage=_coverage(ran=["T1"]), registry=reg, pages=_pages(5))
    site = next(r for r in rollups if r.level == "site")
    assert site.findings_open == 1 and site.instances_open == 5 and site.pages_affected == 5
