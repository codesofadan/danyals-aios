"""Every ``require_feature("...")`` key MUST exist in ``FEATURE_KEYS``.

This is an AUTO-DISCOVERING net in the same family as ``test_dial_registration`` and
``test_route_auth_guard``: it walks every router in ``app/routers/`` and
``app/modules/*/router.py`` and extracts the key literal from each
``require_feature(...)`` call, so a NEW module is covered the day it lands.

WHY THIS EXISTS (a real defect, measured 2026-08-25):

The feature catalogue was reduced from 17 keys to 11 in ``app/rbac/matrix.py`` and its
mirror ``frontend/lib/data.ts``. Six module routers were never updated and kept
guarding on keys the catalogue no longer contained: ``keyword_research``,
``rank_tracker``, ``competitor_intel``, ``on_page``, ``local_seo`` and
``backlink_manager``.

The failure mode is SILENT and, like the dial defect, two-sided:

1. ``effective_feature_level`` (``rbac/matrix.py``) ends with
   ``overrides.get(feature_key, "off")`` - a key nobody holds a grant for resolves to
   ``off``, so ``require_feature`` raises 403 for every non-owner.
2. The only write path for a grant (``UpdateGrantsRequest`` / ``InviteMemberRequest``
   in ``app/schemas/identity.py``) VALIDATES against ``FEATURE_KEYS``, so a grant for
   an unregistered key **cannot be created**.

Together: roughly 54 endpoints across six modules were owner-only, returning
``403 "Missing feature access: <key>"`` to an admin or a manager, with no way for
anyone to switch them on. No module-local suite could see it - each one fakes the
guard - and ``test_route_auth_guard`` only asserts 401-when-unauthenticated, which
those routes did correctly.

The same drift also silently emptied the team portal's tool catalogue, because
``frontend/lib/tools.ts`` builds its slugs from the mirrored feature list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.rbac.matrix import FEATURE_KEYS

pytestmark = pytest.mark.unit

_APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _router_files() -> list[Path]:
    """Every module that can declare a route guard."""
    files = sorted((_APP_DIR / "routers").glob("*.py"))
    files += sorted((_APP_DIR / "modules").glob("*/router.py"))
    return [f for f in files if f.name != "__init__.py"]


def _required_feature_keys(py: Path) -> list[str]:
    """Key literals passed to ``require_feature(...)``, read via AST.

    AST rather than a regex: a regex matches the call inside a docstring or a comment
    (several routers document the guard in prose), and importing the module would drag
    settings, Celery and a DB pool into a unit test.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"))
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name != "require_feature" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            keys.append(first.value)
    return keys


_GUARDED: list[tuple[str, str]] = [
    (str(py.relative_to(_APP_DIR)), key) for py in _router_files() for key in _required_feature_keys(py)
]


def test_the_sweep_actually_finds_guards() -> None:
    """Guard-for-the-guard: a discovery bug must FAIL, never vacuously pass."""
    assert len(_GUARDED) >= 10, (
        f"expected many require_feature() guards across the routers, found {_GUARDED}. "
        "If the guards genuinely moved, fix the discovery here - do not let this "
        "suite pass by finding nothing."
    )


@pytest.mark.parametrize(
    ("source", "key"), _GUARDED, ids=[f"{s}:{k}" for s, k in _GUARDED]
)
def test_guarded_feature_key_is_registered(source: str, key: str) -> None:
    """A guard on an unregistered key is owner-only and cannot be granted."""
    assert key in FEATURE_KEYS, (
        f"app/{source} guards a route with require_feature({key!r}), which is NOT in "
        f"FEATURE_KEYS. effective_feature_level() resolves an unknown key to 'off' for "
        f"every non-owner, and the grant schemas in app/schemas/identity.py reject the "
        f"key, so nobody can switch it on: the route is owner-only and unfixable from "
        f"the UI. Either register the feature in app/rbac/matrix.py (and its mirror in "
        f"frontend/lib/data.ts) or drop the guard. Registered: {sorted(FEATURE_KEYS)}"
    )


def test_no_duplicate_feature_keys() -> None:
    """FEATURE_KEYS is derived from FEATURES; a duplicate would mask a definition."""
    assert len(FEATURE_KEYS) == len(set(FEATURE_KEYS)), (
        f"duplicate feature key(s): {sorted(FEATURE_KEYS)}"
    )
