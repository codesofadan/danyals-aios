"""Every feature key the off-page WORKER gates on must be a registered dial.

The e8964de defect class: an unregistered key makes dial_mode() fall back to "off"
and the path is dead on arrival — or, the 2026-09-01 variant, a worker silently rides
a NEIGHBOR's dial (citation discovery gating on `backlinks`, whose byhand default
blocked every citation audit behind a 202). The existing registration guard sweeps
only app/modules/*/tasks.py's _FEATURE, which is exactly how workers/tasks/offpage.py
escaped it — this one reads that module's GateContext feature keys directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.schemas.cost import DIAL_FEATURES

pytestmark = pytest.mark.unit

_OFFPAGE = Path(__file__).resolve().parents[1] / "workers" / "tasks" / "offpage.py"


def _feature_keys_used() -> set[str]:
    src = _OFFPAGE.read_text(encoding="utf-8")
    # The module's convention: feature keys live in module constants ending _FEATURE.
    consts = dict(re.findall(r'^_(\w+_FEATURE)\s*=\s*"([^"]+)"', src, re.M))
    assert consts, "offpage.py stopped declaring _*_FEATURE constants - update this guard"
    return set(consts.values())


def test_every_offpage_gate_key_is_a_registered_dial() -> None:
    registered = {f.key for f in DIAL_FEATURES}
    used = _feature_keys_used()
    missing = used - registered
    assert not missing, (
        f"workers/tasks/offpage.py gates on unregistered dial key(s) {sorted(missing)}: "
        "dial_mode() will fall back to 'off' and the path is dead on arrival"
    )


def test_citation_discovery_has_its_own_dial_and_it_is_not_backlinks() -> None:
    """Re-point the citation monitor at _MONITOR_FEATURE and this goes red."""
    src = _OFFPAGE.read_text(encoding="utf-8")
    assert '_CITATION_DISCOVERY_FEATURE = "citation_discovery"' in src
    citation_fn = src[src.index("def run_citation_monitor") : src.index("def run_citation_monitor") + 1500]
    assert "_CITATION_DISCOVERY_FEATURE" in citation_fn
    assert "feature_key=_MONITOR_FEATURE" not in citation_fn
    assert any(f.key == "citation_discovery" and f.default_mode == "api" for f in DIAL_FEATURES)
