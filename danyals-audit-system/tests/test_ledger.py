"""Every declared check is registered or ledgered. Nothing is silent.

The ledger's whole value is that it cannot rot quietly, so these tests are
deliberately unforgiving about counts.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from audit_engine.analyzers import ledger as ledger_mod
from audit_engine.checklist import cost_class, load_registry

REGISTRY = load_registry()
ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "audit_engine"


def _python_emitted() -> set[str]:
    out: set[str] = set()
    for path in sorted(ENGINE_ROOT.rglob("*.py")):
        if path.name in {"checklist.py", "ledger.py"}:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        out |= {
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value in REGISTRY
        }
    return out


# --- the core invariant -----------------------------------------------------

def test_every_full_check_is_implemented_or_ledgered():
    """The one that makes coverage honest."""
    implemented = _python_emitted()
    silent = sorted(
        c for c, s in REGISTRY.items()
        if s.automation == "full" and c not in implemented and c not in ledger_mod.LEDGER
    )
    assert not silent, (
        f"{len(silent)} checks are declared, not implemented, and not ledgered, "
        f"so coverage cannot say why they did not run: {silent[:15]}"
    )


def test_no_ledger_entry_describes_an_implemented_check():
    """Implement a check and you must delete its excuse in the same PR."""
    implemented = _python_emitted()
    stale = sorted(c for c in ledger_mod.LEDGER if c in implemented)
    assert not stale, f"these are implemented but still ledgered as missing: {stale}"


def test_no_ledger_entry_describes_an_ai_assisted_check():
    wrong = sorted(c for c in ledger_mod.LEDGER if REGISTRY[c].automation != "full")
    assert not wrong, f"an agent already runs these; they are not gaps: {wrong}"


def test_every_ledgered_id_exists():
    assert not sorted(c for c in ledger_mod.LEDGER if c not in REGISTRY)


# --- the two-sided ratchet --------------------------------------------------

def test_ledger_has_not_grown():
    assert len(ledger_mod.LEDGER) <= ledger_mod.LEDGER_CEILING, (
        f"{len(ledger_mod.LEDGER)} entries against a ceiling of {ledger_mod.LEDGER_CEILING}. A new "
        f"unimplemented check was added. Implement it, or raise the ceiling in "
        f"the same commit and say why."
    )


def test_ledger_has_not_silently_shrunk():
    assert len(ledger_mod.LEDGER) >= ledger_mod.LEDGER_FLOOR, (
        f"{len(ledger_mod.LEDGER)} entries against a floor of {ledger_mod.LEDGER_FLOOR}. Checks were "
        f"implemented - good - but the floor must drop in the same commit so the "
        f"coverage gain appears in the diff."
    )


def test_the_ratchet_is_closed():
    """A floor below the ceiling would let the count drift between them."""
    assert ledger_mod.LEDGER_FLOOR == ledger_mod.LEDGER_CEILING == len(ledger_mod.LEDGER)


# --- an excuse must fit the check ------------------------------------------

@pytest.mark.parametrize("check_id", sorted(ledger_mod.LEDGER))
def test_the_reason_matches_what_the_check_actually_declares(check_id):
    entry = ledger_mod.LEDGER[check_id]
    required = ledger_mod.REASON_REQUIRES[entry.reason]
    if not required:
        return
    declared = set(REGISTRY[check_id].data_sources)
    assert declared & required, (
        f"{check_id} is parked as {entry.reason.value} but declares {sorted(declared)}, "
        f"none of which is one of {sorted(required)}. The excuse does not fit the check."
    )


def test_not_yet_built_really_means_every_input_is_already_free():
    """This reason claims there is no blocker but the work. Prove it."""
    for cid, e in ledger_mod.LEDGER.items():
        if e.reason is not ledger_mod.Reason.NOT_YET_BUILT:
            continue
        classes = {cost_class(s) for s in REGISTRY[cid].data_sources}
        assert classes <= {"zero"}, (
            f"{cid} is ledgered NOT_YET_BUILT but needs {sorted(classes)} data. "
            f"It has a real blocker and must say which."
        )


def test_every_entry_names_a_blocker_and_a_note():
    for cid, e in ledger_mod.LEDGER.items():
        assert e.blocked_on.strip(), f"{cid} names no blocker"
        assert len(e.note.strip()) > 40, f"{cid} has no reviewable note"


def test_every_reason_is_used_or_removed():
    """A reason nobody uses is dead vocabulary that will be misapplied later."""
    used = {e.reason for e in ledger_mod.LEDGER.values()}
    unused = sorted(r.value for r in ledger_mod.Reason if r not in used)
    assert not unused, f"unused reasons: {unused}"
