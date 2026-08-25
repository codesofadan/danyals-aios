"""Two migrations must never share a number - apply order would become a tiebreak.

``infra/deploy/install.sh`` applies ``db/migrations/[0-9]*.sql`` in **shell glob order**
and records each one in ``deploy.schema_migrations``, whose PRIMARY KEY is the
``filename``. Two files sharing a number therefore apply in filename order, not in the
order the numbers claim - and nothing anywhere states which of the two was intended to
run first.

WHY THE KNOWN PAIRS ARE NOT RENUMBERED (measured 2026-08-25):

The ledger keys on the filename. Renaming an already-applied migration makes it look
UNAPPLIED on every deployed environment, so the next ``install.sh`` re-runs it. For a
migration that is not idempotent that is a broken deploy, and for one that is, it is
still a silent re-execution nobody asked for. The two historical collisions below are
therefore RECORDED, not fixed: both pairs are independent (a template/schedule change
and a Web-2.0 platform seed touch no common object), so their relative order does not
matter, and freezing them costs nothing.

The gap at 0052 is deliberate and harmless: numbers are allocated, not compacted, and
a gap cannot make two files race.

This guard exists so the NEXT collision fails in CI instead of being discovered on a
VPS at deploy time.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"

# Historical collisions, frozen because the ledger keys on filename (see module
# docstring). Each pair is order-independent. NOTHING may be added here without the
# same justification - the fix for a new collision is to renumber it before it ships.
_GRANDFATHERED: dict[str, set[str]] = {
    "0070": {"0070_site_templates.sql", "0070_web2_platforms_batch3.sql"},
    "0072": {"0072_content_schedule.sql", "0072_web2_platforms_batch4.sql"},
}


def _by_number() -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for sql in _MIGRATIONS.glob("[0-9]*.sql"):
        m = re.match(r"^(\d{4})_", sql.name)
        if m:
            out[m.group(1)].add(sql.name)
    return dict(out)


def test_the_sweep_actually_finds_migrations() -> None:
    """Guard-for-the-guard: a discovery bug must FAIL, never vacuously pass."""
    found = _by_number()
    assert len(found) >= 90, f"expected the full migration set, found {len(found)} numbers"


def test_no_new_duplicate_migration_numbers() -> None:
    """A number used twice makes apply order depend on the shell's glob sort."""
    dupes = {n: files for n, files in _by_number().items() if len(files) > 1}
    unexpected = {
        n: sorted(files) for n, files in dupes.items() if files != _GRANDFATHERED.get(n)
    }
    assert not unexpected, (
        f"migration number(s) used more than once: {unexpected}. install.sh applies "
        f"db/migrations/[0-9]*.sql in glob order and keys deploy.schema_migrations on "
        f"the FILENAME, so these two would apply in an order nobody chose. Renumber the "
        f"new one before it is applied anywhere - renaming it later makes every "
        f"deployed environment re-run it."
    )


def test_grandfathered_collisions_still_exist_as_recorded() -> None:
    """If a frozen pair is renumbered or removed, this list must stop claiming it.

    Prevents the allowlist rotting into a licence for a collision it no longer
    describes.
    """
    actual = _by_number()
    for number, expected in _GRANDFATHERED.items():
        assert actual.get(number) == expected, (
            f"the recorded collision at {number} no longer matches the tree "
            f"(recorded {sorted(expected)}, found {sorted(actual.get(number, set()))}). "
            f"If it was genuinely resolved, delete its entry from _GRANDFATHERED."
        )
