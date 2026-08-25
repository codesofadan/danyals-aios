"""The registry refuses bad registrations at import, not at run time.

Each refusal below corresponds to a defect that actually shipped. A test that
only proves the happy path would be worthless here, so every guard is shown to
fire.
"""
from __future__ import annotations

import pytest

# Importing the CLI registers every analyzer. Done at MODULE level so the
# registry is already populated when the clearing fixture takes its snapshot -
# otherwise the snapshot is empty, the fixture restores nothing, and any test
# that iterates `registered()` passes vacuously. That is exactly what the
# analyzer-path equality test did on its first run.
import audit_engine.cli.main  # noqa: F401
from audit_engine.analyzers import registry as reg_mod
from audit_engine.checklist import load_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Empty registry per test, real one restored afterwards."""
    snapshot = reg_mod.registered()
    reg_mod.clear_registry_for_tests()
    yield snapshot
    reg_mod.restore_registry_for_tests(snapshot)


@pytest.fixture
def real_registry(_clean_registry):
    """The registry as the ENGINE builds it, inside a test that would otherwise
    see an empty one.

    Without this a test that iterates `registered()` passes vacuously - which is
    exactly what the analyzer-path equality test did on its first run.
    """
    reg_mod.restore_registry_for_tests(_clean_registry)
    registered = reg_mod.registered()
    assert registered, "the engine registered nothing; this fixture is not working"
    return registered


def _a_full_check() -> str:
    return next(c for c, s in load_registry().items() if s.automation == "full")


def _an_ai_assisted_check() -> str:
    return next(c for c, s in load_registry().items() if s.automation == "ai-assisted")


# --- the happy path ---------------------------------------------------------

def test_a_valid_registration_binds_and_reads_its_taxonomy_from_the_checklist():
    cid = _a_full_check()

    @reg_mod.check(cid, scope="page")
    def analyzer(p):  # pragma: no cover - never called here
        return None

    reg = reg_mod.registered()[cid]
    assert reg.scope == "page"
    assert reg.dotted_path.endswith("analyzer")
    assert reg.is_async is False
    # taxonomy is NOT supplied by the decorator - it comes from the checklist
    assert reg.spec.name == load_registry()[cid].name
    assert reg.spec.pillar == load_registry()[cid].pillar


def test_an_async_analyzer_is_detected():
    cid = _a_full_check()

    @reg_mod.check(cid, scope="site_crawled")
    async def analyzer(ctx):  # pragma: no cover
        return None

    assert reg_mod.registered()[cid].is_async is True


# --- the four refusals ------------------------------------------------------

def test_an_unknown_check_id_is_refused():
    with pytest.raises(reg_mod.RegistrationError, match="no checklist row defines"):
        @reg_mod.check("ON-999", scope="page")
        def analyzer(p):  # pragma: no cover
            return None


def test_registering_the_same_id_twice_is_refused():
    """Six ids used to emit twice per run. This makes that unmergeable."""
    cid = _a_full_check()

    @reg_mod.check(cid, scope="page")
    def first(p):  # pragma: no cover
        return None

    with pytest.raises(reg_mod.RegistrationError, match="already registered"):
        @reg_mod.check(cid, scope="page")
        def second(p):  # pragma: no cover
            return None


def test_python_may_not_register_an_ai_assisted_check():
    """The Wave A defect: an agent and a heuristic both scoring one check."""
    cid = _an_ai_assisted_check()
    with pytest.raises(reg_mod.RegistrationError, match="Wave A defect"):
        @reg_mod.check(cid, scope="page")
        def analyzer(p):  # pragma: no cover
            return None


def test_an_invalid_scope_is_refused():
    cid = _a_full_check()
    with pytest.raises(reg_mod.RegistrationError, match="valid scopes"):
        @reg_mod.check(cid, scope="whatever")  # type: ignore[arg-type]
        def analyzer(p):  # pragma: no cover
            return None


# --- rollup provenance ------------------------------------------------------

def test_a_rollup_with_no_declared_inputs_is_refused():
    """OFF-074 published an authority score while all 33 inputs were skipped."""
    cid = _a_full_check()
    with pytest.raises(reg_mod.RegistrationError, match="no declared inputs"):
        @reg_mod.check(cid, scope="rollup")
        def analyzer(ctx):  # pragma: no cover
            return None


def test_a_rollup_declaring_an_unknown_input_is_refused():
    cid = _a_full_check()
    with pytest.raises(reg_mod.RegistrationError, match="unknown inputs"):
        @reg_mod.rollup(cid, inputs=("OFF-999",))
        def analyzer(ctx):  # pragma: no cover
            return None


def test_a_rollup_cannot_require_more_inputs_than_it_declares():
    cid = _a_full_check()
    other = [c for c, s in load_registry().items() if s.automation == "full" and c != cid][:2]
    with pytest.raises(reg_mod.RegistrationError, match="needs 5 inputs"):
        @reg_mod.rollup(cid, inputs=tuple(other), min_inputs_ran=5)
        def analyzer(ctx):  # pragma: no cover
            return None


def test_declaring_inputs_outside_a_rollup_is_refused():
    cid = _a_full_check()
    other = next(c for c, s in load_registry().items() if s.automation == "full" and c != cid)
    with pytest.raises(reg_mod.RegistrationError, match="not 'rollup'"):
        @reg_mod.check(cid, scope="page", inputs=(other,))
        def analyzer(p):  # pragma: no cover
            return None


def test_a_valid_rollup_records_its_provenance():
    cid = _a_full_check()
    ins = tuple(c for c, s in load_registry().items() if s.automation == "full" and c != cid)[:3]

    @reg_mod.rollup(cid, inputs=ins, min_inputs_ran=2)
    def analyzer(ctx):  # pragma: no cover
        return None

    reg = reg_mod.registered()[cid]
    assert reg.scope == "rollup"
    assert reg.inputs == ins
    assert reg.min_inputs_ran == 2


# --- lookup -----------------------------------------------------------------

def test_for_scope_filters():
    ids = [c for c, s in load_registry().items() if s.automation == "full"][:3]

    @reg_mod.check(ids[0], scope="page")
    def a(p):  # pragma: no cover
        return None

    @reg_mod.check(ids[1], scope="psi")
    def b(psi):  # pragma: no cover
        return None

    assert [r.check_id for r in reg_mod.for_scope("page")] == [ids[0]]
    assert [r.check_id for r in reg_mod.for_scope("psi")] == [ids[1]]
    assert reg_mod.for_scope("rollup") == []


# --------------------------------------------------------------------------
# The claim registry.py makes about itself.
#
# Its docstring says `Registration` records the real dotted path "which a test
# then asserts equals the YAML's `analyzer:` field". That test did not exist,
# and would have failed: 0 of 87 registered checks had a correct declaration,
# so coverage reported `analyzer_path_unresolved` for checks that had just run.
# --------------------------------------------------------------------------

def test_every_registered_check_declares_its_real_analyzer_path(real_registry):
    """Wave 1's plan said the `analyzer:` field "becomes true and testable"."""
    specs = load_registry()
    assert len(real_registry) > 80, "too few registrations to be a real check"
    wrong = {
        cid: (specs[cid].analyzer, r.dotted_path)
        for cid, r in real_registry.items()
        if specs[cid].analyzer != r.dotted_path
    }
    assert not wrong, (
        f"{len(wrong)} checklist declarations disagree with the code that "
        f"implements them: {dict(list(wrong.items())[:3])}"
    )


def test_a_registered_analyzer_path_actually_imports(real_registry):
    """A path that is merely CONSISTENT is not enough - it has to resolve, or
    the coverage sheet's 'is there code behind this' column is still a guess."""
    from audit_engine import emit

    for cid, r in list(real_registry.items())[:20]:
        assert emit.analyzer_path_resolves(r.dotted_path, cid), cid


def test_a_factory_built_rollup_reports_a_usable_path(real_registry):
    """Eighteen rollups are made by a factory. Without naming the closure they
    all reported `rollups._make.<locals>._fn`, which is useless in a coverage
    sheet and cannot be matched against anything."""
    rollups = {c: r for c, r in real_registry.items() if r.scope == "rollup"}
    assert len(rollups) == 18
    for cid, r in rollups.items():
        assert "<locals>" not in r.dotted_path, cid
        assert r.dotted_path.endswith(cid.lower().replace("-", "_")), cid
