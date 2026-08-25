"""The roadmap: sequenced work, with every number measured or operator-supplied.

Verified against the real 461-finding smileon.pk audit: at 40 pts/month 162 items
plan and 299 fall to backlog; at 80 pts/month 322 plan and 139 fall to backlog -
the capacity input is the ONLY thing that moves.
"""

from __future__ import annotations

from app.services import audit_roadmap as RM


def _f(fid="f1", **over):
    row = {
        "id": fid, "check_id": "ON-041", "check_name": "H1 optimization",
        "pillar": "on-page", "subcategory": "headings", "dimension": "onpage",
        "severity": "major", "locus_kind": "template", "locus_value": "/s/{slug}",
        "instance_count": 10, "pages_affected": 10, "confidence": 1.0,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------- impact

def test_impact_is_severity_times_reach_times_confidence():
    assert RM.compute_impact(severity="critical", pages_affected=50,
                             pages_crawled=100, confidence=1.0) == 1.5
    assert RM.compute_impact(severity="major", pages_affected=100,
                             pages_crawled=100, confidence=1.0) == 2.0


def test_a_site_wide_finding_reaches_the_whole_site():
    """A broken robots.txt affects no single page and every page. Scoring reach
    as 0 would rank it below a typo."""
    assert RM.compute_impact(severity="critical", pages_affected=0,
                             pages_crawled=100, confidence=1.0) == 3.0


def test_low_confidence_lowers_impact():
    """An inferred finding must not outrank a measured one of equal severity."""
    high = RM.compute_impact(severity="major", pages_affected=10, pages_crawled=10, confidence=1.0)
    low = RM.compute_impact(severity="major", pages_affected=10, pages_crawled=10, confidence=0.5)
    assert low < high


def test_reach_cannot_exceed_one():
    assert RM.compute_impact(severity="major", pages_affected=500,
                             pages_crawled=100, confidence=1.0) == 2.0


# --------------------------------------------------------------------- effort

def test_a_template_fix_costs_the_same_whether_it_covers_four_pages_or_four_hundred():
    """This is the entire reason causes and instances are separate. One template
    edit is one edit; pricing it per page would recreate the flat list."""
    small = RM.compute_effort(locus_kind="template", pillar="on-page", instance_count=4)
    large = RM.compute_effort(locus_kind="template", pillar="on-page", instance_count=400)
    assert small == large


def test_per_page_work_does_scale_but_is_bucketed_not_linear():
    """200 pages of genuinely per-page work is harder than 4 - but not 50x."""
    a = RM.compute_effort(locus_kind="url", pillar="on-page", instance_count=1)
    b = RM.compute_effort(locus_kind="url", pillar="on-page", instance_count=30)
    c = RM.compute_effort(locus_kind="url", pillar="on-page", instance_count=200)
    assert a < b < c
    assert c < a * 5


def test_a_site_level_fix_is_the_cheapest_locus():
    site = RM.compute_effort(locus_kind="site", pillar="on-page", instance_count=1)
    tmpl = RM.compute_effort(locus_kind="template", pillar="on-page", instance_count=1)
    assert site < tmpl


def test_off_page_is_the_most_expensive_surface():
    """It depends on third parties, which we do not control."""
    off = RM.compute_effort(locus_kind="site", pillar="off-page", instance_count=1)
    on = RM.compute_effort(locus_kind="site", pillar="on-page", instance_count=1)
    assert off > on


# ------------------------------------------------------------------- ordering

def test_highest_value_per_unit_of_work_goes_first():
    cheap_big = _f("cheap", severity="critical", locus_kind="site", pages_affected=0)
    dear_small = _f("dear", severity="minor", locus_kind="url", instance_count=200,
                    pages_affected=200)
    rm = RM.build([dear_small, cheap_big], pages_crawled=200)
    assert rm.items[0].finding_id == "cheap"


def test_ordering_is_deterministic_for_identical_priorities():
    a = _f("a", check_id="ON-001")
    b = _f("b", check_id="ON-002")
    first = [i.finding_id for i in RM.build([a, b], pages_crawled=10).items]
    second = [i.finding_id for i in RM.build([b, a], pages_crawled=10).items]
    assert first == second


# ------------------------------------------------------------------- phasing

def test_capacity_is_the_only_thing_that_moves_the_plan():
    """Real numbers: 40 pts/month planned 162 of 461; 80 planned 322."""
    findings = [_f(f"f{i}", check_id=f"ON-{i:03}") for i in range(60)]
    lean = RM.build(findings, pages_crawled=100, capacity_points_per_month=10)
    rich = RM.build(findings, pages_crawled=100, capacity_points_per_month=100)
    assert len(rich.planned) > len(lean.planned)
    assert len(rich.backlog) < len(lean.backlog)


def test_nothing_is_dropped_only_moved_to_backlog():
    findings = [_f(f"f{i}", check_id=f"ON-{i:03}") for i in range(200)]
    rm = RM.build(findings, pages_crawled=100, capacity_points_per_month=5)
    assert len(rm.items) == 200
    assert len(rm.planned) + len(rm.backlog) == 200
    assert rm.backlog, "a tiny capacity must produce a visible backlog"


def test_phases_are_relative_windows_and_carry_no_dates():
    """The anti-fabrication rule. No item may claim a calendar date, because
    nothing we measure supports one."""
    rm = RM.build([_f()], pages_crawled=10)
    item = rm.items[0]
    assert item.phase in {p for p, _ in RM.PHASE_MONTHS} | {RM.PHASE_BACKLOG}
    assert not hasattr(item, "due_date")
    assert not hasattr(item, "start_date")


def test_the_phase_windows_sum_to_twelve_months():
    assert sum(m for _, m in RM.PHASE_MONTHS) == 12


def test_sequence_restarts_within_each_phase():
    findings = [_f(f"f{i}", check_id=f"ON-{i:03}") for i in range(40)]
    rm = RM.build(findings, pages_crawled=100, capacity_points_per_month=10)
    for phase, items in rm.by_phase().items():
        if items:
            assert [i.sequence for i in items] == list(range(1, len(items) + 1)), phase


def test_a_single_item_larger_than_a_phase_is_still_scheduled():
    """Refusing to schedule the biggest problem would be worse than overfilling."""
    huge = _f("huge", locus_kind="url", pillar="off-page", instance_count=500,
              pages_affected=500)
    rm = RM.build([huge], pages_crawled=500, capacity_points_per_month=1)
    assert rm.items[0].phase == RM.PHASE_P0


# --------------------------------------------------------------------- fields

def test_every_item_states_how_to_prove_it_is_done():
    """'We fixed 14 issues' needs a check to re-run, not an absence of findings."""
    rm = RM.build([_f()], pages_crawled=10)
    item = rm.items[0]
    assert item.verification_check == "ON-041"
    assert "ON-041" in item.exit_criterion and "pass" in item.exit_criterion


def test_work_is_assigned_using_the_established_role_vocabulary():
    """Keyed on DIMENSION - geo work is blog_writer, technical is developer."""
    geo = RM.build([_f(dimension="geo")], pages_crawled=10).items[0]
    tech = RM.build([_f(dimension="technical", pillar="technical")], pages_crawled=10).items[0]
    local = RM.build([_f(dimension="local", pillar="local-seo")], pages_crawled=10).items[0]
    assert geo.owner_role == "blog_writer"
    assert tech.owner_role == "developer"
    assert local.owner_role == "local_specialist"


def test_the_title_states_the_blast_radius():
    assert "10 pages" in RM.build([_f(instance_count=10)], pages_crawled=10).items[0].title
    site = RM.build([_f(locus_kind="site", instance_count=1)], pages_crawled=10).items[0]
    assert "site-wide" in site.title


def test_the_effort_model_is_publishable():
    """A client who disagrees with an ordering must be able to read the table
    that produced it."""
    table = RM.effort_table()
    assert table["scoring_model_version"] == RM.SCORING_MODEL_VERSION
    assert set(table["locus"]) == {"site", "template", "url", "entity"}
    assert "priority" in table and "impact" in table


def test_an_empty_audit_produces_an_empty_plan_not_a_crash():
    rm = RM.build([], pages_crawled=0)
    assert rm.items == [] and rm.planned == [] and rm.backlog == []
