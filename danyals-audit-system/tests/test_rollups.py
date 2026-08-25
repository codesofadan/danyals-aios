"""Composite scores, and the gate that stops them lying.

OFF-074 "Authority score" declares data_sources [computed], which classes as
zero-cost, so it ran on a FREE tier while all 33 backlink checks it aggregates
were skipped - publishing an authority score computed over no link data.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from audit_engine.analyzers import rollups as ro
from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.dispatch import run_rollups
from audit_engine.analyzers.ledger import LEDGER, Reason
from audit_engine.analyzers.registry import registered
from audit_engine.checklist import load_registry
from audit_engine.scorers.aggregator import SEVERITY_WEIGHT

ROLLUPS = {c: r for c, r in registered().items() if r.scope == "rollup"}


@dataclass
class F:
    """Stands in for a persisted Finding: same three attributes."""
    check_id: str
    status: str = "pass"
    score: float = 10.0
    severity: str = "info"


def ctx_with(*findings):
    return ro.RollupContext.from_findings(findings)


# --- the input sets come from the taxonomy, not from a hand-written list ----

def test_eighteen_rollups_are_registered():
    assert len(ROLLUPS) == 18


@pytest.mark.parametrize("cid", sorted(ROLLUPS))
def test_every_rollup_declares_a_real_non_empty_input_set(cid):
    reg = ROLLUPS[cid]
    specs = load_registry()
    assert reg.inputs, f"{cid} declares no inputs"
    assert all(i in specs for i in reg.inputs)
    assert cid not in reg.inputs, f"{cid} aggregates itself"


@pytest.mark.parametrize("cid", sorted(ROLLUPS))
def test_no_rollup_aggregates_another_rollup(cid):
    """A pillar rollup that included the scoring subpoint would fold its own
    output back into itself."""
    assert not (set(ROLLUPS[cid].inputs) & set(ROLLUPS)), cid


@pytest.mark.parametrize("cid", sorted(ROLLUPS))
def test_min_inputs_ran_is_sane(cid):
    reg = ROLLUPS[cid]
    assert 1 <= reg.min_inputs_ran <= len(reg.inputs)


def test_a_pillar_rollup_covers_most_of_its_pillar():
    specs = load_registry()
    on_page = {c for c, s in specs.items() if s.pillar == "on-page"}
    assert len(set(ROLLUPS["ON-118"].inputs)) >= len(on_page) * 0.8


# --- the gate ---------------------------------------------------------------

def test_a_rollup_over_no_inputs_is_n_a_not_zero():
    """The OFF-074 defect, asserted directly."""
    res = run_rollups(set(), ctx_with(), registrations=[ROLLUPS["OFF-074"]])
    (_, v), = res.verdicts
    assert v.status == "n_a"
    assert v.score == 0.0 and v.confidence == 0.0
    assert res.gated == ["OFF-074"]


def test_an_n_a_input_does_not_count_as_having_run():
    """A page full of "not applicable" is not evidence."""
    ins = ROLLUPS["ON-116"].inputs
    ctx = ctx_with(*[F(i, status="n_a", score=0.0) for i in ins])
    assert ctx.ran == set()
    res = run_rollups(ctx.ran, ctx, registrations=[ROLLUPS["ON-116"]])
    assert res.gated == ["ON-116"]


def test_enough_inputs_lets_the_rollup_compute():
    ins = ROLLUPS["ON-116"].inputs
    ctx = ctx_with(*[F(i, status="pass", score=9.0, severity="info") for i in ins])
    res = run_rollups(ctx.ran, ctx, registrations=[ROLLUPS["ON-116"]])
    (_, v), = res.verdicts
    assert v.status == "pass"
    assert v.score == pytest.approx(9.0)
    assert res.gated == []


def test_a_partial_rollup_scales_confidence_and_says_which_inputs_ran():
    ins = ROLLUPS["ON-118"].inputs
    ran = ins[:20]
    ctx = ctx_with(*[F(i, score=8.0) for i in ran])
    (_, v), = run_rollups(ctx.ran, ctx, registrations=[ROLLUPS["ON-118"]]).verdicts
    assert v.evidence["partial_rollup"] is True
    assert len(v.evidence["inputs_ran"]) == 20
    assert len(v.evidence["inputs_missing"]) == len(ins) - 20
    assert v.confidence < 0.9, "a rollup over a fifth of its inputs must not be confident"


# --- the weighting is the engine's own -------------------------------------

def test_the_weighting_matches_the_engine_aggregator_exactly():
    """A rollup must never disagree with the pillar score above it."""
    ins = ROLLUPS["ON-116"].inputs
    findings = [
        F(ins[0], status="fail", score=0.0, severity="critical"),
        F(ins[1], status="pass", score=10.0, severity="info"),
    ]
    ctx = ctx_with(*findings)
    score, _prov = ctx.score_over(ins)
    expected = (
        (0.0 * SEVERITY_WEIGHT["critical"] + 10.0 * SEVERITY_WEIGHT["info"])
        / (SEVERITY_WEIGHT["critical"] + SEVERITY_WEIGHT["info"])
    )
    assert score == pytest.approx(round(expected, 2))


def test_a_critical_failure_outweighs_an_info_pass():
    ins = ROLLUPS["ON-116"].inputs
    bad = ctx_with(F(ins[0], "fail", 0.0, "critical"), F(ins[1], "pass", 10.0, "info"))
    good = ctx_with(F(ins[0], "pass", 10.0, "critical"), F(ins[1], "fail", 0.0, "info"))
    assert bad.score_over(ins)[0] < good.score_over(ins)[0]


def test_provenance_is_always_carried():
    ins = ROLLUPS["ON-116"].inputs
    _score, prov = ctx_with(F(ins[0], score=7.0)).score_over(ins)
    assert prov["verdicts_counted"] == 1
    assert "severity-weighted mean" in prov["weighting"]


def test_a_rollup_is_informational_never_critical():
    """It restates checks that already reported their own severity. Raising an
    alarm here would double-count them."""
    ins = ROLLUPS["ON-116"].inputs
    ctx = ctx_with(*[F(i, "fail", 0.0, "critical") for i in ins])
    (_, v), = run_rollups(ctx.ran, ctx, registrations=[ROLLUPS["ON-116"]]).verdicts
    assert v.severity in {"info", "minor", "major"}
    assert v.severity != "critical"


def test_many_verdicts_for_one_check_all_count():
    """Per-page checks emit once per page; a rollup must see every one."""
    ins = ROLLUPS["ON-116"].inputs
    ctx = ctx_with(*[F(ins[0], score=s) for s in (10.0, 0.0)])
    score, prov = ctx.score_over(ins)
    assert prov["verdicts_counted"] == 2
    assert score == pytest.approx(5.0)


# --- what was deliberately NOT built ---------------------------------------

@pytest.mark.parametrize("cid", ["ON-112", "OFF-072", "OFF-073", "OFF-075"])
def test_the_undefinable_rollups_are_ledgered_as_an_owner_decision(cid):
    """Building these by picking a plausible-looking subpoint would produce a
    number a client could not trace back to anything."""
    assert cid not in ROLLUPS
    assert LEDGER[cid].reason is Reason.OWNER_DECISION


def test_rollup_pending_is_retired():
    """Wave 5 closed the reason out entirely."""
    assert not hasattr(Reason, "ROLLUP_PENDING")


# --- the context ------------------------------------------------------------

def test_the_context_accepts_findings_from_the_legacy_generators():
    """Most on-page checks still come from iter_* generators. A rollup seeing
    only registry-dispatched findings would score a tenth of the pillar."""
    ctx = ro.RollupContext.from_findings([F("ON-034", "pass", 9.0, "info")])
    assert ctx.ran == {"ON-034"}


def test_the_context_accepts_verdicts_too():
    ctx = ro.RollupContext()
    ctx.add("ON-034", Verdict("pass", 9.0, "info", 1.0, {}))
    assert ctx.ran == {"ON-034"}


def test_an_empty_context_has_run_nothing():
    assert ro.RollupContext().ran == set()
