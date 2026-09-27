"""The client's approved design must reach the PUBLISHED page, not just the outline.

THE DEFECT, found by running a real job end to end (2026-09-25). The pipeline resolved
the client's approved brand kit server-side, so "analyse once, conform forever" was true
for the page's STRUCTURE. The publish path did not: ``_resolve_row_blueprint``,
``_design_css_text`` and ``_is_full_width_page`` each read only
``source_pack["design_profile"]``.

A job created WITHOUT an inline profile - the normal case once a client HAS a kit, and
exactly what the dashboard sends - therefore published with:

  * structure from the kit (correct, via the pipeline), and
  * styling from ``_classic_style_block()`` - a generic look carrying none of the
    client's measured palette or fonts, and
  * the narrow article measure with no native-block render, because that decision reads
    the same absent key.

So the operator captured a design, approved it, saw it shape the outline, and got a page
that looked nothing like it. Two readers of one decision is how that happened; there is
now one (``effective_design_profile``).
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit

_KIT = {
    "palette": {"primary": "#3F6D99", "accent": "#E2197F", "text": "#16233D"},
    "typography": {"heading_font": "'Poppins', sans-serif", "body_font": "'Inter', sans-serif"},
    "components": {"button_style": "pill", "card_style": "soft shadow"},
    # FOUR SECTIONS. Under four, a measurement is read as a failed capture and loses to
    # the audited template (`page_blueprints._MIN_MEASURED_SECTIONS`) - so a three-section
    # fixture would make the homepage assertion below fail for a reason this test is not
    # about.
    "blueprint": [
        {"kind": "hero"}, {"kind": "services"}, {"kind": "proof"}, {"kind": "cta"},
    ],
    "blueprints": {"homepage": [
        {"kind": "hero"}, {"kind": "services"}, {"kind": "proof"}, {"kind": "cta"},
    ]},
    "source_page_type": "homepage",
    "raw_measurements": {"section_order": ["hero", "services", "proof", "cta"],
                         "container_width": "1220px"},
    "approved_at": "2026-09-25T00:00:00Z",
}


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "CJ-9001",
        "client_id": "cl-1",
        "page_type": "blog",
        "topic": "The importance of physical fitness in life",
        "source_pack": {},          # NO inline design_profile - the normal case
    }
    row.update(over)
    return row


def _as_profile() -> dict[str, Any]:
    """The kit shaped as a design profile, mirroring `_kit_design_profile`."""
    raw = _KIT["raw_measurements"]
    return {
        "palette": _KIT["palette"],
        "typography": _KIT["typography"],
        "components": _KIT["components"],
        "layout": {
            "blueprint": _KIT["blueprint"],
            "blueprints": _KIT["blueprints"],
            "source_page_type": _KIT["source_page_type"],
            "section_order": raw["section_order"],
            "container_width": raw["container_width"],
            "hero_style": "centered",
            "cta_style": "banner",
        },
    }


def _patch_kit(monkeypatch: pytest.MonkeyPatch, profile: dict[str, Any] | None) -> None:
    import workers.tasks.content as content

    monkeypatch.setattr(content, "_kit_design_profile", lambda client_id: profile)


# --------------------------------------------------------------------------- #
# The resolver.
# --------------------------------------------------------------------------- #
def test_the_approved_kit_is_used_when_the_job_carries_no_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE defect. Re-inject by reading source_pack only and this fails."""
    from workers.tasks.content import effective_design_profile

    _patch_kit(monkeypatch, _as_profile())
    profile = effective_design_profile(_row())
    assert profile is not None
    assert profile["palette"]["primary"] == "#3F6D99"
    assert "Poppins" in profile["typography"]["heading_font"]


def test_the_kit_outranks_an_inline_request_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matches the pipeline's documented precedence: a per-request profile is whatever a
    wizard held in React state at launch; the kit is what the design system IS."""
    from workers.tasks.content import effective_design_profile

    _patch_kit(monkeypatch, _as_profile())
    row = _row(source_pack={"design_profile": {"palette": {"primary": "#000000"}}})
    profile = effective_design_profile(row)
    assert profile is not None
    assert profile["palette"]["primary"] == "#3F6D99", "the kit must win"


def test_the_inline_profile_is_used_when_there_is_no_kit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client who has never been analysed keeps exactly today's behaviour."""
    from workers.tasks.content import effective_design_profile

    _patch_kit(monkeypatch, None)
    row = _row(source_pack={"design_profile": {"palette": {"primary": "#123456"}}})
    profile = effective_design_profile(row)
    assert profile is not None
    assert profile["palette"]["primary"] == "#123456"


def test_no_kit_and_no_inline_profile_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from workers.tasks.content import effective_design_profile

    _patch_kit(monkeypatch, None)
    assert effective_design_profile(_row()) is None


def test_a_job_with_no_client_never_looks_a_kit_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public free-audit funnel and ad-hoc jobs have no tenant; a lookup would be
    meaningless and must not happen."""
    import workers.tasks.content as content

    calls: list[str] = []
    monkeypatch.setattr(content, "_kit_design_profile",
                        lambda cid: calls.append(cid) or None)  # type: ignore[func-returns-value]
    content.effective_design_profile(_row(client_id=None))
    assert calls == [""] or calls == [], "a blank client id must not reach a real lookup"


# --------------------------------------------------------------------------- #
# The three consumers that were reading the wrong thing.
# --------------------------------------------------------------------------- #
def test_the_design_css_carries_the_kit_palette_and_fonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The visible half of the defect: without this the page shipped with
    `_classic_style_block()` - a generic look with none of the client's colours."""
    from workers.tasks.content import _design_css_text

    _patch_kit(monkeypatch, _as_profile())
    css = _design_css_text(_row())
    assert css, "a client with an approved kit must get design CSS"
    assert "#3F6D99" in css or "#3f6d99" in css.lower(), "the kit's primary colour is missing"
    assert "Poppins" in css, "the kit's heading font is missing"


def test_a_client_with_a_kit_gets_the_designed_full_width_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_is_full_width_page` gates the post type AND the native-block render. A blog page
    for a client WITH an approved design is a designed page, not a narrow article."""
    from workers.tasks.content import _is_full_width_page

    _patch_kit(monkeypatch, _as_profile())
    assert _is_full_width_page(_row()) is True


def test_a_blog_for_a_client_with_no_kit_stays_a_narrow_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard against over-correcting: no design means no designed page, and a blog
    keeps the reading measure it should have."""
    from workers.tasks.content import _is_full_width_page

    _patch_kit(monkeypatch, None)
    assert _is_full_width_page(_row()) is False


def test_the_blueprint_still_resolves_per_page_type_through_the_kit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kit here was measured on a HOMEPAGE, so a blog page must take the audited blog
    template - not the homepage's sequence (migration 0154). This is the interaction
    between the two fixes, which is where a regression would actually land."""
    from app.services.page_blueprints import TEMPLATES
    from workers.tasks.content import _resolve_row_blueprint

    _patch_kit(monkeypatch, _as_profile())
    specs = _resolve_row_blueprint(_row(page_type="blog"))
    assert [s.kind for s in specs] == [s.kind for s in TEMPLATES["blog"].sections]

    # ...and a page of the type that WAS measured takes the measured sequence.
    specs = _resolve_row_blueprint(_row(page_type="homepage"))
    assert [s.kind for s in specs] == ["hero", "services", "proof", "cta"]


def test_a_kit_read_failure_degrades_to_the_request_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A styling lookup must never fail a publish: an unreachable store falls back to
    whatever the job itself carries. The swallow lives in `_kit_design_profile`, so this
    exercises the real seam rather than a patched-out one."""
    import app.modules.content_planning.repo as repo_mod
    import workers.tasks.content as content

    class _Exploding:
        def approved_brand_kit(self, client_id: str) -> dict[str, Any]:
            raise RuntimeError("db down")

    monkeypatch.setattr(repo_mod, "ContentPlanningStore", _Exploding)
    row = _row(source_pack={"design_profile": {"palette": {"primary": "#abcdef"}}})
    profile = content.effective_design_profile(row)
    assert profile is not None
    assert profile["palette"]["primary"] == "#abcdef"


def test_the_kit_lookup_itself_swallows_storage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_kit_design_profile` is where the degrade lives: an unreachable store returns
    None so the caller falls back, rather than a publish dying on a styling read."""
    import workers.tasks.content as content

    class _Exploding:
        def approved_brand_kit(self, client_id: str) -> dict[str, Any]:
            raise RuntimeError("db down")

    import app.modules.content_planning.repo as repo_mod

    monkeypatch.setattr(repo_mod, "ContentPlanningStore", _Exploding)
    assert content._kit_design_profile("cl-1") is None


def test_an_unapproved_or_empty_kit_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """A kit with no blueprint and no section order carries no design to conform to."""
    import app.modules.content_planning.repo as repo_mod
    import workers.tasks.content as content

    class _Empty:
        def approved_brand_kit(self, client_id: str) -> dict[str, Any]:
            return {"palette": {}, "typography": {}, "blueprint": [], "blueprints": {},
                    "raw_measurements": {}}

    monkeypatch.setattr(repo_mod, "ContentPlanningStore", _Empty)
    assert content._kit_design_profile("cl-1") is None


def test_the_kit_lookup_carries_the_page_type_map_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0154's two fields must survive the shaping, or the resolver cannot tell which page
    type the measurement was of."""
    import app.modules.content_planning.repo as repo_mod
    import workers.tasks.content as content

    class _Store:
        def approved_brand_kit(self, client_id: str) -> dict[str, Any]:
            return dict(_KIT)

    monkeypatch.setattr(repo_mod, "ContentPlanningStore", _Store)
    profile = content._kit_design_profile("cl-1")
    assert profile is not None
    layout = profile["layout"]
    assert layout["source_page_type"] == "homepage"
    assert list(layout["blueprints"]) == ["homepage"]
