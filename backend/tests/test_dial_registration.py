"""Every dial key a module spends through MUST be registered in ``DIAL_FEATURES``.

This is an AUTO-DISCOVERING net: it walks ``app/modules/*/tasks.py`` and extracts each
module's ``_FEATURE`` constant, so a NEW module is covered the day it lands with no
manual registration here (the same discipline as ``test_route_auth_guard``).

WHY THIS EXISTS (a real defect this suite now prevents):

Four Part-8 modules shipped passing unregistered keys to the cost gate
(``keyword_research`` / ``local_rank`` / ``rank_tracker`` / ``on_page``). Nothing failed
loudly, because the failure mode is SILENT and two-sided:

1. ``PostgresCostStore.dial_mode`` ends with ``_DEFAULT_MODE.get(feature_key, "off")`` -
   an unknown key resolves to ``off``, so the gate skips the provider call and the
   module degrades **forever** while looking healthy.
2. ``PATCH /cost/dials`` rejects any key not in ``DIAL_KEYS`` (``routers/cost.py``), so
   ops **cannot switch it on**.

Together that is worse than "defaulted off": the paid path is UNSWITCHABLE-ON, i.e.
dead on arrival. No module-local test catches it, because each module's own suite fakes
the gate - only a cross-module sweep like this one can see it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.schemas.cost import DIAL_KEYS

pytestmark = pytest.mark.unit

_MODULES_DIR = Path(__file__).resolve().parents[1] / "app" / "modules"


def _feature_key(tasks_py: Path) -> str | None:
    """The module's ``_FEATURE = "..."`` literal, read via AST (never imported).

    AST rather than a regex or an import: a regex would match the constant inside a
    comment or docstring, and importing would drag Celery + settings into the test.
    """
    tree = ast.parse(tasks_py.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "_FEATURE"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    return None


def _modules_with_tasks() -> list[tuple[str, Path]]:
    """Every module package that owns a ``tasks.py`` (i.e. can spend)."""
    out: list[tuple[str, Path]] = []
    for pkg in sorted(p for p in _MODULES_DIR.iterdir() if p.is_dir()):
        tasks = pkg / "tasks.py"
        if tasks.is_file():
            out.append((pkg.name, tasks))
    return out


def test_the_sweep_actually_finds_modules() -> None:
    """Guard-for-the-guard: a discovery bug must FAIL, never vacuously pass."""
    found = _modules_with_tasks()
    assert len(found) >= 4, f"expected several task-owning modules, found {found}"


@pytest.mark.parametrize(
    ("module", "tasks_py"), _modules_with_tasks(), ids=[m for m, _ in _modules_with_tasks()]
)
def test_module_dial_key_is_registered(module: str, tasks_py: Path) -> None:
    """A module's gate key must exist in DIAL_FEATURES, or it is unswitchable-on."""
    key = _feature_key(tasks_py)
    if key is None:
        pytest.skip(f"{module} declares no _FEATURE (makes no metered call)")
    assert key in DIAL_KEYS, (
        f"{module}/tasks.py spends through the cost gate with _FEATURE={key!r}, which is "
        f"NOT in DIAL_FEATURES. dial_mode() would silently resolve it to 'off' and "
        f"PATCH /cost/dials would reject the key, so the module's paid path is dead on "
        f"arrival with no way for ops to enable it. Register it in app/schemas/cost.py "
        f"(or reuse the existing dial that already describes it). Registered: "
        f"{sorted(DIAL_KEYS)}"
    )


def test_no_duplicate_dial_keys() -> None:
    """DIAL_KEYS is a frozenset, so a duplicate key would silently vanish."""
    from app.schemas.cost import DIAL_FEATURES

    keys = [f.key for f in DIAL_FEATURES]
    assert len(keys) == len(set(keys)), f"duplicate dial key(s): {sorted(keys)}"
