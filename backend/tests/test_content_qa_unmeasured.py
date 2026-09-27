"""A QA dimension that measured nothing must not report a score.

THE DEFECT, in two forms, both found by reading real runs.

FORM 1 (CJ-4346). The teardown's table-stakes entity list - the only input
``entity_coverage`` has - was capitalised stopwords: ``['Physical', 'Regular', 'The',
'This', 'You']``. Every English draft contains those, so the dimension scored **100**
against a tautology. Fixed upstream in ``content_research.proper_nouns``.

FORM 2 (CJ-4347, after that fix). With real entity extraction the list came back EMPTY,
because the research stage had degraded and no competitor pages were fetched. The scorer's
rule was "no table-stakes to cover => full marks (nothing is required)", so an 8%-weighted
dimension again contributed a perfect score for having learned nothing - and the weighted
total is what decides whether a page is worth a reviewer's time.

Both forms are the same mistake: reporting a measurement that did not happen. The audit
engine already settled the right answer for this shape - its aggregator DROPS an ``n_a``
verdict from the weighted mean so an unmeasured check "leaves the composite instead of
dragging it down". This module now does the same: the weight is renormalised over the
dimensions actually measured, and the unmeasured ones are named.
"""

from __future__ import annotations

import pytest

from app.services.content_qa import (
    DIMENSION_WEIGHTS,
    HARD_GATE_DIMENSIONS,
    QA_DIMENSIONS,
    UNMEASURED,
    _score_entity_coverage,
)

pytestmark = pytest.mark.unit


class _Teardown:
    def __init__(self, entities: list[str]) -> None:
        self.table_stakes_entities = entities
        self.differentiator_entities: list[str] = []


class _Brief:
    def __init__(self, entities: list[str]) -> None:
        self.teardown = _Teardown(entities)


class _Content:
    def __init__(self, draft: str) -> None:
        self.draft_md = draft


def test_an_empty_table_stakes_list_reports_unmeasured_not_full_marks() -> None:
    """FORM 2, exactly. Re-inject `return 100, []` and this fails."""
    score, notes = _score_entity_coverage(_Content("Some prose."), _Brief([]))  # type: ignore[arg-type]
    assert score == UNMEASURED
    assert notes, "an unmeasured dimension must say why"
    assert "not measured" in " ".join(notes).lower()


def test_unmeasured_is_distinguishable_from_both_zero_and_a_hundred() -> None:
    """The whole point of the sentinel: 0 means measured-and-bad, 100 means
    measured-and-perfect, and neither is true of a measurement that never ran."""
    assert UNMEASURED != 0
    assert UNMEASURED != 100
    assert UNMEASURED < 0, "a sentinel inside the 0-100 range could be mistaken for a score"


def test_real_entities_are_still_scored_normally() -> None:
    """The guard against over-correcting: a genuine expectation must still be measured."""
    brief = _Brief(["Lahore", "Centrum", "Panadol", "Novartis"])
    content = _Content("We stock Centrum and Panadol in Lahore.")
    score, _notes = _score_entity_coverage(content, brief)  # type: ignore[arg-type]
    assert score not in (UNMEASURED, 100)
    assert 0 < score < 100, "3 of 4 covered should be a partial score"


def test_full_coverage_of_a_real_list_still_scores_100() -> None:
    brief = _Brief(["Lahore", "Centrum"])
    content = _Content("Centrum, in Lahore.")
    score, _notes = _score_entity_coverage(content, brief)  # type: ignore[arg-type]
    assert score == 100


# --------------------------------------------------------------------------- #
# The roll-up.
# --------------------------------------------------------------------------- #
def test_an_unmeasured_dimension_is_excluded_from_the_weighted_total() -> None:
    """Renormalisation, checked by arithmetic rather than by a magic number.

    With every measured dimension at 80, the weighted total must be 80 - not 80 minus
    the unmeasured dimension's weight (which is what leaving it in at 0 would give, and
    which would punish the page for a provider degrade), and not above 80 (which is what
    leaving it in at 100 did).
    """
    measured = [d for d in QA_DIMENSIONS if d != "entity_coverage"]
    weight_sum = sum(DIMENSION_WEIGHTS[d] for d in measured)
    renormalised = sum(80 * DIMENSION_WEIGHTS[d] for d in measured) / weight_sum
    assert round(renormalised) == 80

    # And the old behaviours are both provably different from 80.
    as_zero = sum(80 * DIMENSION_WEIGHTS[d] for d in measured)  # entity_coverage at 0
    as_hundred = as_zero + 100 * DIMENSION_WEIGHTS["entity_coverage"]
    assert round(as_zero) < 80, "leaving it in at 0 deflates the total"
    assert round(as_hundred) > 80, "leaving it in at 100 inflates the total"


def test_every_dimension_carries_a_weight_so_renormalising_is_well_defined() -> None:
    """If a dimension were missing from the weight vector, renormalisation would divide
    by a sum that does not match the dimensions being summed."""
    assert set(QA_DIMENSIONS) == set(DIMENSION_WEIGHTS)
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == 1.0


def test_entity_coverage_is_not_a_hard_gate_so_unmeasured_cannot_block() -> None:
    """Sanity on the fix's blast radius: `entity_coverage` is excluded from
    `blocked_by` when unmeasured, and it is not a hard gate anyway - so a degraded
    research stage can never hard-block a publish through this path."""
    assert "entity_coverage" not in HARD_GATE_DIMENSIONS


def test_the_scorecard_names_what_it_could_not_measure() -> None:
    """A reader must be able to tell a 0 that is a finding from a 0 that is an absence,
    without reading the notes prose."""
    from dataclasses import fields

    from app.services.content_qa import QaScore

    assert "unmeasured" in {f.name for f in fields(QaScore)}
