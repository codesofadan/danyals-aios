"""P4: engagement shapes - what each runs, in what order, against what budget."""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.content_planning.schemas import Engagement, MapNode
from app.modules.content_planning.service import (
    SHAPE_PLANS,
    BudgetLedger,
    build_work_plan,
    cache_groups,
    check_readiness,
    order_for_cache,
    plan_for,
)


def _eng(shape: str = "page_set", **kw: Any) -> Engagement:
    base: dict[str, Any] = {
        "id": "e1", "shape": shape, "status": "ready",
        "scope": {"services": ["slab leak repair"], "cities": ["San Jose"]},
    }
    return Engagement(**{**base, **kw})  # type: ignore[arg-type]


def _node(kw: str, **over: Any) -> MapNode:
    base: dict[str, Any] = {
        "id": kw, "map_id": "m1", "primary_keyword": kw, "page_type": "service",
        "cluster_key": "slab", "priority": 0, "status": "planned",
    }
    return MapNode(**{**base, **over})  # type: ignore[arg-type]


class TestShapesRunDifferentWork:
    def test_a_single_page_does_not_buy_an_engagements_worth_of_keywords(self) -> None:
        """Discovery is ~10 DataForSEO calls whether the engagement is one page or
        fifty. Running it to write ONE page against a keyword the operator already
        named is buying a plan nobody will use."""
        assert "keyword_discovery" not in plan_for("single_page").engagement_stages

    def test_a_page_set_does_run_discovery_and_a_map(self) -> None:
        stages = plan_for("page_set").engagement_stages
        assert "keyword_discovery" in stages and "topical_map" in stages

    def test_continuing_an_engagement_reads_the_audit_before_planning(self) -> None:
        """Planning first re-commissions pages the client already has - billable
        duplication, which is worse than doing nothing."""
        stages = plan_for("continue_existing").engagement_stages
        assert stages.index("read_audit") < stages.index("topical_map")

    def test_a_retainer_is_recurring_but_nothing_schedules_it(self) -> None:
        """Beat is parked by owner instruction. A shape that claimed to be scheduled
        would be a control that silently does nothing."""
        plan = plan_for("retainer")
        assert plan.recurring is True
        notes = build_work_plan(_eng("retainer"), [_node("a")]).notes
        assert any("beat is parked" in n for n in notes)

    def test_an_unknown_shape_falls_back_to_the_narrowest_one(self) -> None:
        assert plan_for("nonsense").shape == "single_page"  # type: ignore[arg-type]

    def test_every_shape_in_the_enum_has_a_plan(self) -> None:
        """A shape the database accepts but the service cannot route would create an
        engagement that can never start."""
        assert set(SHAPE_PLANS) == {
            "single_page", "page_set", "full_site", "continue_existing", "retainer"}


class TestPrerequisites:
    def test_a_full_site_will_not_start_without_a_brand_kit(self) -> None:
        """Fifty pages that each choose their own look is precisely what the owner
        asked not to happen."""
        r = check_readiness(_eng("full_site"), has_brand_kit=False)
        assert not r.ready and "brand_kit" in r.missing
        assert any("different people" in x for x in r.reasons)

    def test_a_full_site_starts_once_a_kit_exists(self) -> None:
        assert check_readiness(_eng("full_site"), has_brand_kit=True).ready

    def test_continuing_without_the_audit_is_blocked(self) -> None:
        r = check_readiness(_eng("continue_existing", source_audit_id=None))
        assert "source_audit" in r.missing

    def test_continuing_with_an_audit_is_allowed(self) -> None:
        assert check_readiness(_eng("continue_existing", source_audit_id="a1")).ready

    def test_a_shape_with_no_discovery_needs_named_targets(self) -> None:
        r = check_readiness(_eng("single_page", scope={}))
        assert "named_targets" in r.missing

    def test_a_cancelled_engagement_is_never_ready(self) -> None:
        assert not check_readiness(_eng(status="cancelled")).ready

    def test_readiness_is_separate_from_the_sme_halt(self) -> None:
        """The SME halt is per-CLUSTER and blocks drafting; readiness is per-ENGAGEMENT
        and blocks starting. Both failures are real and they are not the same."""
        eng = _eng(status="awaiting_sme")
        assert check_readiness(eng).ready is True
        assert eng.blocks_drafting is True


class TestOrderingForTheDoctrineCache:
    def test_pages_are_grouped_by_type(self) -> None:
        """The page pack is the largest variable block of the system prompt and the
        cache is prefix-matched. Two consecutive pages of one type reuse it; two that
        alternate each pay the write."""
        nodes = [_node("a", page_type="service"), _node("b", page_type="local"),
                 _node("c", page_type="service"), _node("d", page_type="local")]
        types = [n.page_type for n in order_for_cache(nodes)]
        assert types == ["local", "local", "service", "service"]

    def test_priority_still_leads_within_a_group(self) -> None:
        nodes = [_node("low", priority=1), _node("high", priority=9)]
        assert [n.primary_keyword for n in order_for_cache(nodes)] == ["high", "low"]

    def test_ordering_changes_order_only_never_membership(self) -> None:
        nodes = [_node(k, page_type=t) for k, t in
                 [("a", "service"), ("b", "local"), ("c", "faq")]]
        assert {n.id for n in order_for_cache(nodes)} == {"a", "b", "c"}

    def test_the_run_lengths_report_what_the_sort_actually_bought(self) -> None:
        ordered = order_for_cache([_node("a"), _node("b"), _node("c", page_type="faq")])
        assert cache_groups(ordered) == [("faq", 1), ("service", 2)]

    def test_an_all_different_plan_is_told_it_gains_nothing(self) -> None:
        """Implying a saving that is not there is worse than reporting none."""
        nodes = [_node("a", page_type="service"), _node("b", page_type="faq")]
        notes = build_work_plan(_eng(), nodes).notes
        assert any("buys no cache reuse" in n for n in notes)


class TestTheEngagementBudget:
    def test_no_cap_means_no_block(self) -> None:
        ok, why = BudgetLedger().can_start_page(estimate=99.0)
        assert ok and why == ""

    def test_a_page_that_would_overrun_does_not_start(self) -> None:
        """Stopping with thirty finished pages beats stopping halfway through page
        thirty-one with no budget left to finish it."""
        ledger = BudgetLedger(cap=10.0, spent=9.0)
        ok, why = ledger.can_start_page(estimate=2.0)
        assert not ok
        assert "$1.00 of the $10.00" in why

    def test_a_page_that_fits_starts(self) -> None:
        ok, _ = BudgetLedger(cap=10.0, spent=9.0).can_start_page(estimate=0.5)
        assert ok

    def test_the_ledger_counts_what_was_actually_spent(self) -> None:
        """`_estimate_full_cost` bounds one job against an ESTIMATE. A retry loop walks
        past that while every individual job still looks reasonable."""
        ledger = BudgetLedger(cap=5.0)
        for _ in range(3):
            ledger.record(1.9)
        assert ledger.exhausted is True
        assert ledger.pages_done == 3
        assert not ledger.can_start_page(estimate=0.01)[0]

    def test_remaining_never_goes_negative(self) -> None:
        ledger = BudgetLedger(cap=1.0)
        ledger.record(5.0)
        assert ledger.remaining == 0.0

    @pytest.mark.parametrize("cost", [-1.0, 0.0])
    def test_a_nonsense_cost_cannot_credit_the_ledger(self, cost: float) -> None:
        ledger = BudgetLedger(cap=10.0, spent=4.0)
        ledger.record(cost)
        assert ledger.spent == 4.0


class TestTheWorkPlan:
    def test_produced_pages_are_not_replanned(self) -> None:
        nodes = [_node("a", status="planned"), _node("b", status="published")]
        assert build_work_plan(_eng(), nodes).page_count == 1

    def test_a_fully_produced_engagement_says_so(self) -> None:
        plan = build_work_plan(_eng(), [_node("a", status="published")])
        assert plan.can_start is False
        assert any("already produced" in n for n in plan.notes)

    def test_a_blocked_prerequisite_reaches_the_plans_notes(self) -> None:
        plan = build_work_plan(_eng("full_site"), [_node("a")], has_brand_kit=False)
        assert plan.can_start is False
        assert any("brand kit" in n for n in plan.notes)

    def test_a_ready_engagement_can_start(self) -> None:
        plan = build_work_plan(_eng(), [_node("a"), _node("b")])
        assert plan.can_start and plan.page_count == 2
        assert plan.page_stages[0] == "sme", "the halt must come first"
