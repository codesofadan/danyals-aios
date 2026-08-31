"""Figures on the page that no supplied fact can support.

Measured on the first three paid runs: the writer used every fact it was given
AND invented eight more figures alongside them. The QA gate blocked on it every
time - correctly - but nothing tried to fix it, so every page arrived needing a
human to hunt for invented numbers.

The risk in a checker like this is the opposite failure: objecting to every
numeral, so the model cuts prose that was fine. Most of these tests are about
what it must NOT flag.
"""

from __future__ import annotations

import pytest

from app.services.content_pipeline.grounding import supplied_figures, unsourced_figures

pytestmark = pytest.mark.unit

FACTS = (
    "count_source: 412 emergency callouts in 2025, median on-site 47 minutes",
    "license_permit: Texas Master Plumber licence M-41982",
    "proof: Flat $149 emergency diagnostic",
    "review_source: 268 reviews at 4.8 on Google",
)


def codes(text: str) -> list[str]:
    return [f.message.split("'")[1] for f in unsourced_figures(text, FACTS)]


class TestWhatItCatches:
    def test_an_invented_money_amount(self) -> None:
        assert "$2,400" in codes("The average repair runs $2,400 in this area.")

    def test_an_invented_quantity_with_a_thousands_separator(self) -> None:
        assert "10,000" in codes("By then 10,000 gallons have soaked into the soil.")

    def test_an_invented_percentage(self) -> None:
        assert "44%" in codes("We resolve 44% of calls on the first visit.")

    def test_an_invented_three_digit_figure(self) -> None:
        assert "400" in codes("We serve 400 homes a month across the area.")

    def test_it_reports_where(self) -> None:
        found = unsourced_figures("line one\nWe serve 400 homes.", FACTS)
        assert found[0].line == 2


class TestWhatItMustNotFlag:
    """A checker that objects to every numeral makes the model cut good prose."""

    def test_a_figure_the_client_supplied(self) -> None:
        assert codes("We logged 412 callouts and answer in 47 minutes.") == []

    def test_a_supplied_money_amount(self) -> None:
        assert codes("The diagnostic is a flat $149, credited to the repair.") == []

    def test_a_supplied_decimal(self) -> None:
        assert codes("Our Google rating is 4.8 across 268 reviews.") == []

    def test_a_figure_that_is_part_of_a_supplied_one(self) -> None:
        """'41982' inside licence 'M-41982' is sourced, not invented."""
        assert codes("Licence M-41982 is on the TSBPE register.") == []

    def test_small_bare_integers_in_ordinary_prose(self) -> None:
        # "two vans", "5 minutes" are structural. Flagging them would have the
        # model rewriting sentences that were never a claim.
        assert codes("We run 2 night vans and answer within 5 rings.") == []

    def test_a_figure_does_not_swallow_the_punctuation_after_it(self) -> None:
        """'$1,600,' was reported once, comma and all - which reads as a
        different number from the one in the sentence."""
        found = unsourced_figures("Repairs run $1,600, sometimes more.", FACTS)
        assert [f.message.split("'")[1] for f in found] == ["$1,600"]

    def test_a_phone_number_in_the_supplied_facts_grounds_its_area_code(self) -> None:
        """The NAP travels as a fact, so '214' in the prose is sourced."""
        facts = (*FACTS, "phone: 214-555-0142")
        assert unsourced_figures("Call 214-555-0142 any time.", facts) == ()

    def test_it_does_not_report_the_same_figure_twice(self) -> None:
        found = unsourced_figures("We serve 400 homes. Another 400 homes wait.", FACTS)
        assert len(found) == 1


class TestSuppliedFigureExtraction:
    def test_it_reads_every_number_out_of_the_facts(self) -> None:
        assert {"412", "2025", "47", "41982", "149", "268", "4.8"} <= supplied_figures(FACTS)

    def test_no_facts_means_nothing_is_supplied(self) -> None:
        assert supplied_figures(()) == set()


class TestTheStageRefusesToRunUngrounded:
    def test_with_no_supplied_facts_it_skips_rather_than_gutting_the_page(self) -> None:
        """Every figure would be 'unsourced', and a repair would strip the page
        bare. That is a grounding failure upstream, not something to fix here."""
        from app.services.content_pipeline.context import PipelineContext
        from app.services.content_pipeline.grounding import run_grounding

        ctx = PipelineContext(draft_md="We serve 400 homes and saved $2,400.")
        result = run_grounding(ctx, writer=None)  # type: ignore[arg-type]
        assert result.outcome == "skipped"
        assert "no supplied facts" in result.notes[0]


class TestItMeasuresExactlyWhatTheGateMeasures:
    """A repair that measures LESS than the gate can never satisfy it. Measured:
    the first version skipped bare integers under 100 to avoid mangling prose,
    passed its own check, and left the gate still blocking on '24', '50', '90'."""

    def test_a_two_digit_claim_the_gate_audits_is_flagged(self) -> None:
        assert codes("A tank holds 50 gallons on average.") == ["50"]

    def test_a_bare_year_is_not_a_quantity_claim(self) -> None:
        """The gate exempts it, so this must too, or the repair would keep
        rewriting 'in 2026' forever."""
        assert codes("Rules changed in 2026 for this permit.") == []

    def test_every_figure_it_flags_is_one_the_gate_would_audit(self) -> None:
        from app.services.content_qa import concrete_claim_digits

        draft = (
            "We ran 412 calls, hold licence M-41982, charge $149, and a tank "
            "holds 50 gallons. In 2026 the rule changed. We use 2 vans."
        )
        audited = set(concrete_claim_digits(draft))
        for finding in unsourced_figures(draft, FACTS):
            token = finding.message.split("'")[1]
            core = "".join(c for c in token if c.isdigit() or c == ".").strip(".")
            assert core in audited, f"{token} is not in the gate's audit set"
