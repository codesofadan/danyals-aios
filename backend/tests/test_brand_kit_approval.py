"""A captured design is not the client's design system until a human says it is.

Migration 0146. `0089` made the design persistent and the pipeline now builds every
page to the client's kit - which closed one defect and opened another: whatever the
analyzer last produced silently became the thing dozens of pages are built to. The
analyzer can return a profile that VALIDATES and is wrong (a bot-blocked capture, a
cookie wall, a site mid-redesign, the vision fallback reading a screenshot loosely),
and publishing forty pages to a wrong design system is expensive to undo.

These pin the gate: generation reads an APPROVED kit, a lead's own capture is
approved on the spot, and everyone else's waits.
"""

from __future__ import annotations

from typing import Any

import pytest

from workers.tasks.content_pipeline import _design_profile_for

pytestmark = pytest.mark.unit


_BLUEPRINT = [
    {"kind": "hero", "heading": "Roofing in Austin", "items": 0},
    {"kind": "services", "heading": "What we do", "items": 3},
    {"kind": "proof", "heading": "Reviews", "items": 4},
    {"kind": "cta", "heading": "Get a quote", "items": 0},
]


class _FakeStore:
    """Stands in for ContentPlanningStore, recording which read was used."""

    def __init__(self, *, approved: dict[str, Any] | None) -> None:
        self._approved = approved
        self.reads: list[str] = []

    def approved_brand_kit(self, client_id: str) -> dict[str, Any] | None:
        self.reads.append("approved")
        return self._approved

    def active_brand_kit(self, client_id: str) -> dict[str, Any] | None:
        self.reads.append("active")
        # Deliberately different from the approved kit: a test that accidentally
        # reads this one must produce a visibly wrong answer, not a passing one.
        return {"blueprint": [{"kind": "WRONG"}], "raw_measurements": {}}


def _kit(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "kit-1",
        "blueprint": _BLUEPRINT,
        "palette": {"primary": "#0a0a0a"},
        "typography": {"heading_font": "Inter"},
        "components": {"button_style": "solid rounded"},
        "raw_measurements": {"container_width": "1180px", "section_order": ["hero"]},
        "approved_at": "2026-09-17T00:00:00Z",
    }
    row.update(over)
    return row


@pytest.fixture
def store_patch(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(store: _FakeStore) -> _FakeStore:
        monkeypatch.setattr(
            "app.modules.content_planning.repo.ContentPlanningStore",
            lambda: store,
            raising=True,
        )
        return store

    return _install


# --------------------------------------------------------------------------- #
# Generation reads the APPROVED kit
# --------------------------------------------------------------------------- #
def test_generation_builds_to_the_approved_kit(store_patch: Any) -> None:
    store = store_patch(_FakeStore(approved=_kit()))
    profile = _design_profile_for({"client_id": "cl-1"}, {})

    assert profile is not None
    assert [s["kind"] for s in profile["layout"]["blueprint"]] == [
        "hero", "services", "proof", "cta"
    ]
    assert store.reads == ["approved"]  # never the merely-active one


def test_the_measured_capacities_survive_into_generation(store_patch: Any) -> None:
    """Conformance is sections AND their capacity; the kit round-trip must keep both."""
    store_patch(_FakeStore(approved=_kit()))
    profile = _design_profile_for({"client_id": "cl-1"}, {})

    assert profile is not None
    services = profile["layout"]["blueprint"][1]
    assert services["items"] == 3


def test_an_unapproved_capture_does_not_shape_pages(store_patch: Any) -> None:
    """The gate. With nothing approved, generation falls back to what the request
    carried rather than building to an unreviewed capture. Re-inject by pointing
    _design_profile_for back at active_brand_kit and this fails."""
    store_patch(_FakeStore(approved=None))
    requested = {"layout": {"blueprint": [{"kind": "from_request"}]}}

    profile = _design_profile_for({"client_id": "cl-1"}, {"design_profile": requested})

    assert profile == requested


def test_no_approved_kit_and_no_request_profile_is_none_not_a_guess(
    store_patch: Any,
) -> None:
    store_patch(_FakeStore(approved=None))
    assert _design_profile_for({"client_id": "cl-1"}, {}) is None


def test_an_empty_kit_is_ignored_rather_than_used_as_an_empty_design(
    store_patch: Any,
) -> None:
    """A kit row with no blueprint and no section order carries no design. Using it
    would resolve to zero sections - which reads downstream as 'this design has no
    sections' rather than 'we have not measured this client'."""
    store_patch(_FakeStore(approved=_kit(blueprint=[], raw_measurements={})))
    requested = {"layout": {"blueprint": [{"kind": "from_request"}]}}

    assert _design_profile_for({"client_id": "cl-1"}, {"design_profile": requested}) == requested


def test_a_job_with_no_client_never_touches_the_store(store_patch: Any) -> None:
    store = store_patch(_FakeStore(approved=_kit()))
    _design_profile_for({}, {"design_profile": None})
    assert store.reads == []


def test_a_storage_failure_degrades_to_the_request_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database hiccup - or a deploy where 0146 has not been applied yet, so
    approved_at does not exist - must not fail the content job. It falls back and
    logs, rather than crashing a paid run."""
    class _Boom:
        def approved_brand_kit(self, client_id: str) -> dict[str, Any] | None:
            raise RuntimeError("column approved_at does not exist")

    monkeypatch.setattr(
        "app.modules.content_planning.repo.ContentPlanningStore", _Boom, raising=True
    )
    requested = {"layout": {"blueprint": [{"kind": "from_request"}]}}
    assert _design_profile_for({"client_id": "cl-1"}, {"design_profile": requested}) == requested
