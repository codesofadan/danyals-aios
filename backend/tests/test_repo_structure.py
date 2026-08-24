"""Structural guards: refuse the decay that a folder audit had to clean up by hand.

Structure rots silently. Nobody deliberately commits a stale build artefact or lets a
migration ordinal collide - it happens one convenient exception at a time, and is only
visible once someone audits the whole tree. These guards make the tree refuse.

They follow the pattern this repository already uses for the same reason:
``test_dial_registration.py`` (a module cannot ship an unregistered dial key),
``test_backlinks_own_profile.py`` (a query cannot forget to pin ``competitor_id``),
``test_no_synthetic_providers_in_production.py`` (a fake cannot reach a production
path). Auto-discovering, so a future module inherits them with nothing to remember.

Each guard below records the ACTUAL incident that motivates it. A guard whose reason has
been forgotten is the first one somebody deletes to make a build go green.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# 1 · Migration ordinals are unique
# --------------------------------------------------------------------------- #
# Prevented defect: `0070` and `0072` EACH APPEAR TWICE (0070_site_templates +
# 0070_web2_platforms_batch3; 0072_content_schedule + 0072_web2_platforms_batch4),
# and 0052 is missing entirely - the result of migrations authored in parallel
# branches and merged without reconciliation.
#
# It currently works only because they are applied in filename order and that order
# happens to be safe. It is NOT fixable retroactively: `deploy.schema_migrations` keys
# on filename, so renaming an applied migration makes it re-apply. Prevention is the
# only remedy available, which is precisely why it needs a guard rather than a note.
_KNOWN_COLLISIONS: frozenset[str] = frozenset({"0070", "0072"})


def _migration_ordinals() -> dict[str, list[str]]:
    by_ordinal: dict[str, list[str]] = defaultdict(list)
    for path in sorted((_REPO_ROOT / "db" / "migrations").glob("*.sql")):
        by_ordinal[path.name.split("_", 1)[0]].append(path.name)
    return by_ordinal


def test_no_new_migration_ordinal_collides() -> None:
    """A NEW duplicate ordinal fails the build. The two historical ones are grandfathered
    because they are already applied and renaming them would re-run them."""
    collisions = {
        ordinal: names
        for ordinal, names in _migration_ordinals().items()
        if len(names) > 1 and ordinal not in _KNOWN_COLLISIONS
    }
    assert not collisions, (
        "Two migrations share an ordinal:\n"
        + "\n".join(f"  {o}: {', '.join(n)}" for o, n in sorted(collisions.items()))
        + "\n\nPick the next free number. Do NOT renumber an applied migration - the "
        "ledger keys on filename and it would re-apply."
    )


def test_the_grandfathered_collisions_have_not_grown() -> None:
    """The historical collisions stay exactly two files each. If a third joins one, the
    exemption is being used as a loophole."""
    ordinals = _migration_ordinals()
    for ordinal in sorted(_KNOWN_COLLISIONS):
        names = ordinals.get(ordinal, [])
        assert len(names) <= 2, f"ordinal {ordinal} has grown to {len(names)}: {names}"


# --------------------------------------------------------------------------- #
# 2 · No built distributables committed as source
# --------------------------------------------------------------------------- #
# Prevented defect: three zips sat at the repo root. `spotino-theme.zip` merely
# duplicated its folder, but `aios-publisher.zip` had gone STALE - plugin v1.4.0 with 4
# files against a v1.7.0 source with 8, missing the entire `includes/` directory
# (~1,475 lines, most of the plugin) - and `push-to-wordpress.ps1` instructed operators
# to install FROM IT. The documented procedure put a broken plugin on a client's site.
#
# That is the failure mode of a committed build artefact: it is invisible to review,
# undiffable, and silently drifts from the source it was built from.
_BINARY_SUFFIXES: frozenset[str] = frozenset({".zip", ".tar", ".gz", ".tgz", ".rar", ".7z"})

# Directories where a binary is legitimately content rather than a build output.
_BINARY_OK_PREFIXES: tuple[str, ...] = (
    "docs/",                       # the client PDF pack, reference PDFs
    "frontend/public/",            # served assets
    "tools/wordpress-demo/",       # a demo article and its featured image
    "danyals-audit-system/",       # the vendored engine's own fixtures
)

# Grandfathered, with the reason. SEO-CONTENT-OS.zip is the ONLY copy of the canonical
# content doctrine that `content_qa.py` and `content_generator.py` cite to justify their
# numeric constants (`backend/seo-content-os/knowledge/`, a path that has never existed
# in git history). It must be EXTRACTED, not deleted - owned by research item R6-1.
# Until then it stays, and this exemption is the record of why.
_BINARY_GRANDFATHERED: frozenset[str] = frozenset({"SEO-CONTENT-OS.zip"})


def _tracked_files() -> list[str]:
    import subprocess

    out = subprocess.run(
        ["git", "ls-files"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_no_build_artefact_is_committed_as_source() -> None:
    offenders = [
        f
        for f in _tracked_files()
        if Path(f).suffix.lower() in _BINARY_SUFFIXES
        and not f.startswith(_BINARY_OK_PREFIXES)
        and f not in _BINARY_GRANDFATHERED
    ]
    assert not offenders, (
        "Built distributable(s) committed as source:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\nA committed archive is a diff nobody can read and it drifts from its "
        "source silently. Build it instead, and add the path to .gitignore. If it is "
        "genuinely content rather than a build output, add its directory to "
        "_BINARY_OK_PREFIXES with a reason."
    )


# --------------------------------------------------------------------------- #
# 3 · Portal import isolation  (a SECURITY guard, not a tidiness one)
# --------------------------------------------------------------------------- #
# The client portal is the one surface where a wrong import is a CLIENT-VISIBLE DATA
# BREACH: other clients' existence, internal cost and MRR, credentials, artefact paths,
# team performance. The recovery specification lists those explicitly as things that
# must never reach a client.
#
# And the tree invites the mistake. `components/client/` (the client portal) sits
# directly beside `components/clients/` (the ADMIN's client-management screens) - ten
# characters apart, opposite audiences, adjacent in every file listing and every
# autocomplete. TypeScript cannot catch it: both are valid components.
#
# Server-side authorization is the real boundary and it holds. This guard exists because
# the cheapest moment to catch such an import is before it ships, and because a reviewer
# scanning a diff will not reliably notice a single character.
_ADMIN_ONLY_COMPONENT_DIRS: frozenset[str] = frozenset({
    "clients", "vault", "cost", "team", "tasks", "policy", "leads",
    "reports", "settings", "wordpress", "offpage", "overview", "audit",
})

_PORTAL_ROOTS: dict[str, frozenset[str]] = {
    # portal app dir -> component dirs it may import
    "client": frozenset({"client", "auth", "ui", "report", "loader", "charts"}),
    "team": frozenset({"portal", "auth", "ui", "loader", "charts"}),
}

_IMPORT_RE = re.compile(r"@/components/([a-zA-Z0-9_-]+)")


def _portal_violations() -> list[str]:
    out: list[str] = []
    for portal, allowed in _PORTAL_ROOTS.items():
        root = _REPO_ROOT / "frontend" / "app" / portal
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.tsx")):
            for used in _IMPORT_RE.findall(path.read_text(encoding="utf-8")):
                if used in _ADMIN_ONLY_COMPONENT_DIRS and used not in allowed:
                    rel = path.relative_to(_REPO_ROOT)
                    out.append(f"{rel}: imports @/components/{used}/ (admin-only)")
    return out


def test_a_portal_page_never_imports_an_admin_component() -> None:
    violations = _portal_violations()
    assert not violations, (
        "A client/team portal page imports an admin-only component:\n  "
        + "\n  ".join(violations)
        + "\n\nThis is a data-exposure risk, not a style issue. `components/client/` is "
        "the CLIENT portal; `components/clients/` is the ADMIN's client management. If "
        "the import is genuinely intended, move the shared piece into "
        "`components/ui/` or `components/shared/` rather than widening the allow-list."
    )


def test_the_portal_guard_actually_scans_something() -> None:
    """A guard that silently matches nothing passes forever. Assert it has real input."""
    scanned = sum(
        1
        for portal in _PORTAL_ROOTS
        for _ in (_REPO_ROOT / "frontend" / "app" / portal).rglob("*.tsx")
        if (_REPO_ROOT / "frontend" / "app" / portal).exists()
    )
    assert scanned >= 5, f"expected to scan the portal pages, found {scanned} files"


# --------------------------------------------------------------------------- #
# 4 · A test may not claim a cross-artifact guarantee it does not check
# --------------------------------------------------------------------------- #
# Prevented defect, found 2026-08-24 while fixing the RBAC hand-mirror:
#
#   tests/test_rbac_matrix.py::test_default_role_perms_match_frontend
#   docstring: "These assertions pin the reference data to frontend/lib/data.ts"
#
# It never opens that file. It re-types the expected values as Python literals and
# compares Python to Python. `frontend/lib/data.ts` could drift arbitrarily and the test
# stays green - and it HAD drifted: 14 fields differed between `matrix.py` and `data.ts`
# (nine colours, an icon, four descriptions). Authority data still agreed, so nothing was
# broken, but the guarantee the test's name advertises had not held for some time.
#
# THIS IS A SPECIES, NOT AN INCIDENT. It is the third occurrence in this repository:
#   1. `backend/CLAUDE.md` invariant #12 described a hard publish gate raising
#      `PublishBlocked`. It is raised nowhere.
#   2. The recovery specification cited that invariant as `[CONFIRMED — [CODE]]`
#      evidence, so the audit cited documentation as if it were code.
#   3. This: a test whose NAME asserts a guarantee its BODY does not implement.
#
# All three are the same failure: a confident artefact that nobody re-derived from
# source. A missing test is visible - `pytest` reports nothing and the gap is obvious in
# coverage. A test like this is INVISIBLE, because it is green, and its name is exactly
# what a reviewer greps for when asking "is this covered?".
#
# The rule: if a test's name or docstring claims parity with a NAMED EXTERNAL ARTEFACT
# (a `.ts` file, a migration, another module's source), its module must actually READ
# something. Comparing hand-copied literals is not pinning; it is a second copy of the
# thing that drifts, wearing the name of a guard.
# TWO LIMITS OF THIS DETECTOR, STATED RATHER THAN GLOSSED. Both came from a sibling
# session's mutation run, where nine agents were told to refute its equivalent guard.
#
# LIMIT A - IT IS KEYED ON A NAME, AND NAMES ARE THE CHEAPEST THING TO EDIT. A test that
# stops *claiming* parity stops being detected, whether or not it stops *needing* to
# claim it. Renaming `test_mask_secret_matches_frontend` to
# `test_mask_secret_is_documented_behaviour`, body untouched, removes it from this sweep
# entirely. The staleness test below now refuses to read that as a discharge, which is
# the containment; the detection gap itself is real and remains. The sibling's answer to
# the same problem in its own guard was to key on CONTENT rather than name - flagging any
# constant holding >= 3 known feature keys under any identifier. There is no equally
# clean content signature for "compares hand-copied literals", so this stays name-keyed
# and honest about it.
#
# LIMIT B - A CONSISTENCY GATE IS NOT A CORRECTNESS GATE. Every entry discharged by
# writing a real cross-artifact reader answers "do the two copies agree?" and NOT "are
# they right?". The sibling proved this is not academic: an adversary granted the Content
# Creator template `key_vault` - the feature whose own description reads "Super Admin
# only" - in BOTH files at once, keeping the count at five. Forty-seven tests passed,
# including its single-source gate, which is *supposed* to pass, because the copies
# agreed. So when one of these entries is discharged, ask the second question too: what
# anchors this value to something independent of both copies?

_SYNC_CLAIM_RE = re.compile(r"match|mirror|in_sync|sync|pins?\b|parity|agree", re.I)
_NAMED_ARTIFACT_RE = re.compile(
    r"frontend|_ts\b|\.ts\b|migration|portal\.ts|tools\.ts|data\.ts|db_enums?", re.I
)
# Reachability is computed PER TEST, not per module, and this is the second version.
#
# The first cleared a whole module the moment that module read any file. A sibling
# session named the blind spot immediately: a module holding one real reader AND one
# hand-copied claim passes on the reader's account. That is not hypothetical - it hid
# `test_policy.py::test_python_literal_unions_match_policy_ts`, whose name claims parity
# with `policy.ts` while it compares against `_EXPECTED_ENUMS`, a hand-typed Python
# constant, in a module that reads a file exactly once somewhere else.
#
# The question that matters is not "does this FILE read the artefact" but "does THIS
# ASSERTION read it" - and those come apart at exactly the granularity this list works
# at. So: walk the call graph from each test, through the module's own helpers, and ask
# whether any node performs a read.
_READ_CALLS: frozenset[str] = frozenset({
    "read_text", "read_bytes", "open", "iterdir", "rglob", "glob", "run", "check_output",
})

# The seven that existed when this guard was written. Each is REAL - every one compares
# hand-copied literals while its name advertises parity with a file it never opens. They
# are listed rather than fixed because fixing them means writing seven real cross-artifact
# readers, which is its own piece of work with its own review.
#
# THIS LIST MAY ONLY SHRINK. A new entry fails the build; removing one means the test now
# genuinely reads what it claims to. A guard introduced already-failing teaches people to
# ignore it, so it is introduced passing, with the debt named.
_UNCHECKED_SYNC_CLAIMS: frozenset[str] = frozenset({
    "tests/modules/client_onboarding/test_schemas.py::test_status_tuples_match_the_migration_enums",
    # The two below became visible only when reachability moved from per-module to
    # per-test; both sit in modules that read a file somewhere else.
    "tests/modules/client_onboarding/test_vault.py::test_the_masked_list_response_shape_is_unchanged_by_kind",
    "tests/test_policy.py::test_python_literal_unions_match_policy_ts",
    "tests/modules/rank_tracker/test_service.py::test_workspace_primary_and_bullets_match_tools_ts",
    "tests/test_rbac_matrix.py::test_default_role_perms_match_frontend",
    "tests/test_rbac_matrix.py::test_templates_match_frontend_and_super_is_all_features",
    "tests/test_reports.py::test_report_types_mirror_the_frontend_catalogue",
    "tests/test_tasks_schema.py::test_next_status_mirrors_portal_ts",
    "tests/test_vault.py::test_mask_secret_matches_frontend",
})

_TESTS_DIR = Path(__file__).resolve().parent


def _called_names(fn: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


def _reads_directly(fn: ast.FunctionDef) -> bool:
    return bool(_called_names(fn) & _READ_CALLS)


def _reaches_a_read(
    fns: dict[str, ast.FunctionDef], name: str, seen: frozenset[str] = frozenset()
) -> bool:
    """Does ``name``, or anything it calls within its own module, perform a read?

    Takes ``fns`` as a parameter rather than closing over it: a nested function that
    captured the enclosing loop's variable would resolve it at CALL time, not at
    definition time, so every module would be analysed against the last one scanned.
    """
    if name in seen or name not in fns:
        return False
    if _reads_directly(fns[name]):
        return True
    seen = seen | {name}
    return any(_reaches_a_read(fns, c, seen) for c in _called_names(fns[name]))


def _unchecked_sync_claims() -> list[str]:
    out: list[str] = []
    for path in sorted(_TESTS_DIR.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

        # A read at import time (a module constant built from a file) covers every test
        # in the module, because the artefact genuinely was consulted.
        module_level_read = any(
            isinstance(c, ast.Call)
            and (getattr(c.func, "attr", None) in _READ_CALLS
                 or getattr(c.func, "id", None) in _READ_CALLS)
            for stmt in tree.body
            if not isinstance(stmt, ast.FunctionDef | ast.ClassDef)
            for c in ast.walk(stmt)
        )

        rel = path.relative_to(_TESTS_DIR.parent).as_posix()
        for name, fn in fns.items():
            if not name.startswith("test_"):
                continue
            blob = f"{name} {ast.get_docstring(fn) or ''}"
            if not (_SYNC_CLAIM_RE.search(blob) and _NAMED_ARTIFACT_RE.search(blob)):
                continue
            if module_level_read or _reaches_a_read(fns, name):
                continue
            out.append(f"{rel}::{name}")
    return out


def test_no_new_test_claims_a_sync_it_does_not_check() -> None:
    new = sorted(set(_unchecked_sync_claims()) - _UNCHECKED_SYNC_CLAIMS)
    assert not new, (
        "Test(s) whose name or docstring claims parity with a named external artefact, "
        "but which never reach a file read - not directly, and not through any helper "
        "they call:\n  "
        + "\n  ".join(new)
        + "\n\nHand-copied literals are not a pin - they are a second copy of the thing "
        "that drifts, wearing the name of a guard. Either READ the artefact and compare, "
        "or rename the test so it does not promise what it does not do."
    )


def _test_still_exists(entry: str) -> bool:
    """Does the exact test named by a debt entry still exist under that name?"""
    rel, _, name = entry.partition("::")
    path = _TESTS_DIR.parent / rel
    if not path.exists():
        return False
    return any(
        isinstance(n, ast.FunctionDef) and n.name == name
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )


def test_the_unchecked_sync_debt_only_shrinks() -> None:
    """An entry may leave this list for exactly ONE reason: the test now reads what it
    claims. Any other reason is the list being edited to make a build green.

    THIS TEST WAS WRONG UNTIL 2026-08-24, and its wrongness was the species it exists to
    catch. It computed `listed - still_detected` and reported the difference as *"these
    now genuinely check what they claim"*. But a test drops out of detection for TWO
    reasons, and it could not tell them apart:

      * it now reaches a read                  -> genuinely discharged
      * it was RENAMED out of the name regex   -> claim hidden, body untouched

    Renaming `test_mask_secret_matches_frontend` to
    `test_mask_secret_is_documented_behaviour`, changing nothing else, made this test
    announce the debt was discharged AND instruct the engineer to delete the entry. A
    guard asserting a guarantee it had not verified - exactly what guard 4 was written
    to find, living inside guard 4.

    Prompted by a sibling session's mutation run, which found the same shape in its own
    non-vacuity proof: *a guard anchored to the artefact it guards decays as that
    artefact changes, and the pressure is always to edit the anchor.* The anchor here is
    a list of test NAMES, and names are the cheapest thing in the file to edit.
    """
    still_detected = set(_unchecked_sync_claims())
    left_the_list = _UNCHECKED_SYNC_CLAIMS - still_detected

    discharged = sorted(e for e in left_the_list if _test_still_exists(e))
    vanished = sorted(e for e in left_the_list if not _test_still_exists(e))

    assert not vanished, (
        "Debt entr(ies) no longer detected because the test was RENAMED OR DELETED, not "
        "because it was fixed:\n  "
        + "\n  ".join(vanished)
        + "\n\nA rename discharges nothing - the hand-copied comparison is still there, "
        "just no longer advertising itself. If the claim was genuinely dropped (the test "
        "no longer promises parity) say so in the entry and remove it deliberately. If "
        "the test was rewritten to read the artefact, confirm that and remove it. Do NOT "
        "delete the entry merely to make this green: THAT is the failure mode this guard "
        "exists to prevent, and it would be the third time this repository has shipped a "
        "guarantee nobody checked."
    )
    assert not discharged, (
        "These now reach a real read and are genuinely discharged - delete them from "
        f"_UNCHECKED_SYNC_CLAIMS in the same commit that fixed them: {discharged}"
    )


# --------------------------------------------------------------------------- #
# 5 · A coverage list may not shrink behind a floor
# --------------------------------------------------------------------------- #
# Prevented defect, and the honest limit of guard 4.
#
# `tests/test_contract_lock.py` is the shape guard 4 CANNOT see. It genuinely reads
# `frontend/lib/*.ts` - `_ts_field_names()` opens the file and parses it - so every test
# in it reaches a real read and guard 4 clears them all, correctly by its own rule. The
# problem is elsewhere, in two places:
#
#   1. `_model_emitted_keys()` returns a set of FIELD NAMES. So the lock compares names,
#      never values. A `RoleView` whose `desc` differs completely from the TypeScript
#      passes. This is exactly how nine colour drifts and an icon drift survived in
#      `matrix.py` vs `data.ts`: even had `RoleView` been listed, it would not have been
#      caught. (`_ENUM_CONTRACT` is the honest half - it exists because "names matching
#      isn't enough" and does compare `Literal` values against TS unions.)
#   2. `test_contract_lock_covers_the_core_response_models` guards the list with
#      `assert len(_CONTRACT) >= 10`, and `_CONTRACT` holds 33. **Twenty-three models
#      could be deleted from the list and the floor would still pass.**
#
# (1) is a semantic gap no structural guard closes - a name-lock is a legitimate check,
# and "compares the wrong thing" is not detectable from shape. (2) IS mechanical, and it
# is the half that makes (1) dangerous: a low floor means coverage can quietly retreat,
# so a reader who greps the file concludes far more protection than exists.
#
# This pins the sizes. Growing a list is fine and expected; SHRINKING one must be
# deliberate and visible in a diff, not absorbed by slack.
_CONTRACT_SIZES: dict[str, int] = {
    "_CONTRACT": 33,       # model <-> TS type pairs, field NAMES only
    "_ENUM_CONTRACT": 28,  # Literal <-> TS union pairs, compared BY VALUE
}


def test_the_contract_lock_coverage_lists_do_not_shrink() -> None:
    import tests.test_contract_lock as lock

    shrunk = {
        name: (expected, len(getattr(lock, name)))
        for name, expected in _CONTRACT_SIZES.items()
        if len(getattr(lock, name)) < expected
    }
    assert not shrunk, (
        "A contract-lock coverage list has shrunk:\n  "
        + "\n  ".join(f"{n}: was {was}, now {now}" for n, (was, now) in sorted(shrunk.items()))
        + "\n\nThe list's own floor is `>= 10`, which 33 entries clear with 23 to spare - "
        "so dropping a model is invisible there. If the removal is intended, lower the "
        "number here in the same commit so it appears in the diff."
    )


def test_the_pinned_contract_sizes_are_not_stale() -> None:
    """If a list has GROWN, raise the pin - otherwise the guard silently protects an
    old, smaller floor and the newest models are unguarded."""
    import tests.test_contract_lock as lock

    grown = {
        name: (expected, len(getattr(lock, name)))
        for name, expected in _CONTRACT_SIZES.items()
        if len(getattr(lock, name)) > expected
    }
    assert not grown, (
        "Coverage grew - raise the pin so the new entries are protected too:\n  "
        + "\n  ".join(f"{n}: pinned {was}, actual {now}" for n, (was, now) in sorted(grown.items()))
    )
