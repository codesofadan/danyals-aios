"""One bad check must cost one check, never a run.

The defect this replaced, now history: `iter_per_page_checks` was a bare
generator, so an exception inside it abandoned every remaining check for that
page AND every page after it - and the audit still reported success with a
quietly smaller denominator, which RAISES the score. Nothing on the call path in
`_run_quick` wrapped the loop.

That generator and its three siblings are gone; every page-scope check now runs
through the dispatcher, which converts a failure into one `n_a` carrying
`analyzer_error` and continues. These tests are what makes that claim checkable.
"""
from __future__ import annotations

import asyncio

import pytest

from audit_engine.analyzers import registry as reg_mod
from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.dispatch import (
    ANALYZER_ERROR,
    INPUTS_MISSING,
    INPUTS_RAN,
    PARTIAL_ROLLUP,
    run_rollups,
    run_scope,
    run_scope_async,
)
from audit_engine.checklist import load_registry


@pytest.fixture(autouse=True)
def _clean():
    _snapshot = reg_mod.registered()
    reg_mod.clear_registry_for_tests()
    yield
    reg_mod.restore_registry_for_tests(_snapshot)


def full_ids(n):
    return [c for c, s in load_registry().items() if s.automation == "full"][:n]


def ok(score=8.0):
    return Verdict("pass", score, "info", 0.9, {"seen": True})


# --- error isolation --------------------------------------------------------

def test_one_failing_check_does_not_stop_the_others():
    a, b, c = full_ids(3)

    @reg_mod.check(a, scope="page")
    def first(p):
        return ok()

    @reg_mod.check(b, scope="page")
    def boom(p):
        raise ValueError("analyzer bug")

    @reg_mod.check(c, scope="page")
    def third(p):
        return ok()

    res = run_scope("page", object())
    assert res.ids() == {a, b, c}, "checks after the failure were abandoned"
    assert res.errored == [b]


def test_a_failed_check_is_n_a_with_zero_confidence_not_a_pass():
    """confidence 0 keeps it out of the weighted mean; n_a keeps it out of the
    failed count. Either mistake moves the client's score."""
    a = full_ids(1)[0]

    @reg_mod.check(a, scope="page")
    def boom(p):
        raise RuntimeError("kaboom")

    (_, v), = run_scope("page", object()).verdicts
    assert v.status == "n_a"
    assert v.confidence == 0.0
    assert v.score == 0.0
    assert "RuntimeError" in v.evidence[ANALYZER_ERROR]
    assert "kaboom" in v.evidence[ANALYZER_ERROR]


def test_a_check_returning_the_wrong_type_is_an_error_not_a_crash():
    a = full_ids(1)[0]

    @reg_mod.check(a, scope="page")
    def wrong(p):
        return {"status": "pass"}

    res = run_scope("page", object())
    assert res.errored == [a]
    assert "TypeError" in res.verdicts[0][1].evidence[ANALYZER_ERROR]


def test_an_analyzer_error_message_is_truncated():
    a = full_ids(1)[0]

    @reg_mod.check(a, scope="page")
    def boom(p):
        raise ValueError("x" * 5000)

    (_, v), = run_scope("page", object()).verdicts
    assert len(v.evidence[ANALYZER_ERROR]) <= 300


# --- scope routing ----------------------------------------------------------

def test_only_the_requested_scope_runs():
    a, b = full_ids(2)

    @reg_mod.check(a, scope="page")
    def pg(p):
        return ok()

    @reg_mod.check(b, scope="psi")
    def psi(x):
        return ok()

    assert run_scope("page", object()).ids() == {a}
    assert run_scope("psi", object()).ids() == {b}


def test_only_restricts_to_a_permitted_set():
    """The tier system uses this so a free run never calls a billable check."""
    a, b = full_ids(2)

    @reg_mod.check(a, scope="page")
    def one(p):
        return ok()

    @reg_mod.check(b, scope="page")
    def two(p):
        return ok()

    assert run_scope("page", object(), only={a}).ids() == {a}


def test_a_sync_dispatch_refuses_an_async_analyzer_loudly():
    a = full_ids(1)[0]

    @reg_mod.check(a, scope="page")
    async def slow(p):
        return ok()

    with pytest.raises(RuntimeError, match="run_scope_async"):
        run_scope("page", object())


def test_async_dispatch_awaits_and_still_isolates_errors():
    a, b = full_ids(2)

    @reg_mod.check(a, scope="site_crawled")
    async def slow(ctx):
        await asyncio.sleep(0)
        return ok()

    @reg_mod.check(b, scope="site_crawled")
    async def slow_boom(ctx):
        raise OSError("network died")

    res = asyncio.run(run_scope_async("site_crawled", object()))
    assert res.ids() == {a, b}
    assert res.errored == [b]


# --- the inputs_ran gate ----------------------------------------------------

def test_a_rollup_with_no_inputs_that_ran_is_n_a_not_zero():
    """OFF-074 published an authority score while all 33 Moz inputs were skipped."""
    target, *ins = full_ids(4)

    @reg_mod.rollup(target, inputs=tuple(ins), min_inputs_ran=2)
    def score(ctx):
        return Verdict("fail", 0.0, "critical", 1.0, {})

    res = run_rollups(set(), object())
    (_, v), = res.verdicts
    assert res.gated == [target]
    assert v.status == "n_a", "a rollup over nothing must not score zero"
    assert v.confidence == 0.0
    assert v.evidence[INPUTS_RAN] == []
    assert sorted(v.evidence[INPUTS_MISSING]) == sorted(ins)


def test_a_rollup_below_its_minimum_is_gated_before_the_call():
    target, *ins = full_ids(4)
    called = []

    @reg_mod.rollup(target, inputs=tuple(ins), min_inputs_ran=3)
    def score(ctx):
        called.append(1)
        return ok()

    run_rollups({ins[0]}, object())
    assert not called, "the gate must run BEFORE the function, not after"


def test_a_partial_rollup_computes_but_scales_confidence_and_says_so():
    target, *ins = full_ids(4)  # 3 inputs

    @reg_mod.rollup(target, inputs=tuple(ins), min_inputs_ran=1)
    def score(ctx):
        return Verdict("pass", 9.0, "info", 1.0, {"mine": 1})

    (_, v), = run_rollups({ins[0], ins[1]}, object()).verdicts
    assert v.status == "pass"
    assert v.evidence[PARTIAL_ROLLUP] is True
    assert sorted(v.evidence[INPUTS_RAN]) == sorted(ins[:2])
    assert v.evidence[INPUTS_MISSING] == [ins[2]]
    assert v.confidence == pytest.approx(1.0 * 2 / 3, rel=1e-3)
    assert v.evidence["mine"] == 1, "the rollup's own evidence survives"


def test_a_complete_rollup_still_carries_its_provenance():
    """Provenance always, not only when something is missing."""
    target, *ins = full_ids(4)

    @reg_mod.rollup(target, inputs=tuple(ins), min_inputs_ran=1)
    def score(ctx):
        return ok(9.0)

    (_, v), = run_rollups(set(ins), object()).verdicts
    assert v.evidence[PARTIAL_ROLLUP] is False
    assert sorted(v.evidence[INPUTS_RAN]) == sorted(ins)
    assert v.evidence[INPUTS_MISSING] == []
    assert v.confidence == pytest.approx(0.9)


def test_a_rollup_that_raises_is_isolated_like_any_other_check():
    target, *ins = full_ids(4)

    @reg_mod.rollup(target, inputs=tuple(ins), min_inputs_ran=1)
    def boom(ctx):
        raise ZeroDivisionError("bad weighting")

    res = run_rollups(set(ins), object())
    assert res.errored == [target]
    assert res.verdicts[0][1].status == "n_a"
