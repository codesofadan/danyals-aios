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
