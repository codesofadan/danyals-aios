"""The per-platform content model, and the defect it exists to stop.

THE DEFECT, stated once: the pipeline drafted one ~900-word HTML article (~5,500
characters) and handed the identical bytes to every adapter. ``BlueskyClient`` publishes
``text[:300]``. So a Bluesky placement was the first 300 characters of a blog post, cut
mid-sentence, with the editorial backlink - the entire reason the property exists -
sliced off the end. The row then reported ``verified`` because the API returned a URL.

The tests below are in two halves:

* **provenance** - the spec's numbers must still match the ADAPTERS they were derived
  from. This is the half that matters in a year: a spec table nobody re-checks is exactly
  the drift 0135's header warns about, so the truncation facts are re-derived from the
  adapter source here rather than trusted.
* **consequence** - the word budget a spec produces must actually fit, with room left for
  the link, and a platform nobody has catalogued must be described as unknown rather than
  guessed at.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from app.modules.web2 import platform_spec as ps
from integrations import web2_publishers as pub

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Provenance: the spec must still describe the adapters
# --------------------------------------------------------------------------- #
def _adapter_max_chars() -> dict[str, int]:
    """Every ``_MAX_CHARS`` an adapter declares, keyed by the platform it publishes to.

    Read out of the SOURCE rather than imported, because the constant is what the adapter
    truncates with and the class attribute is the only place it is stated.
    """
    src = Path(inspect.getfile(pub)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        platform = limit = None
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or not isinstance(stmt.targets[0], ast.Name):
                continue
            name = stmt.targets[0].id
            if name == "platform":
                platform = getattr(pub, ast.unparse(stmt.value), None)
            elif name == "_MAX_CHARS" and isinstance(stmt.value, ast.Constant):
                limit = int(stmt.value.value)
        if platform and limit:
            found[platform] = limit
    return found


def test_every_declared_character_ceiling_matches_its_adapter() -> None:
    """A spec that drifts from its adapter is worse than no spec.

    If this fails, an adapter's ``_MAX_CHARS`` changed and the spec did not. The writer is
    now sized for a ceiling that no longer exists, which means either truncated posts
    again or needlessly tiny ones. Update ``PLATFORM_SPECS`` to the adapter's number.
    """
    for platform, limit in _adapter_max_chars().items():
        spec = ps.spec_for(platform)
        assert spec.max_body_chars == limit, (
            f"{platform}: the adapter truncates at {limit} characters but the spec says "
            f"{spec.max_body_chars}"
        )


def test_the_known_truncating_platforms_are_all_declared() -> None:
    """The specific platforms measured as truncating, pinned by name.

    Named explicitly rather than derived, so that DELETING a spec is also caught - a
    derivation-only check passes happily when both sides lose the same platform.
    """
    truncating = ps.truncating_platforms()
    for platform, limit in (
        (pub.PLATFORM_BLUESKY, 300),
        (pub.PLATFORM_WARPCAST, 320),
        (pub.PLATFORM_MASTODON, 500),
        (pub.PLATFORM_PIXELFED, 500),
        (pub.PLATFORM_MISSKEY, 3000),
    ):
        assert truncating.get(platform) == limit


def test_every_publishable_platform_has_a_spec_except_the_unsupported_one() -> None:
    """A platform the pipeline can publish to but cannot SHAPE for gets a 900-word
    article by default - which is the original defect, one platform at a time."""
    missing = sorted(pub.WEB2_PLATFORMS - set(ps.PLATFORM_SPECS) - ps.UNSUPPORTED_PLATFORMS)
    assert missing == [], f"these platforms publish but have no content model: {missing}"


def test_every_spec_cites_the_adapter_behaviour_it_came_from() -> None:
    """Provenance is not decoration here. A number with no stated origin cannot be
    re-checked, and this table is exactly the kind that rots quietly."""
    for platform, spec in ps.PLATFORM_SPECS.items():
        assert spec.evidence.strip(), f"{platform} has no evidence string"
        assert len(spec.evidence) > 20, f"{platform}'s evidence is too thin to re-check"


# --------------------------------------------------------------------------- #
# Consequence: the budget must actually fit, with the link intact
# --------------------------------------------------------------------------- #
def test_a_word_budget_leaves_room_for_the_link_the_property_exists_to_carry() -> None:
    """The subtle half of the defect.

    The adapters append ``anchor: url`` AFTER the body and then truncate the whole
    string. So a body sized to exactly the platform's ceiling publishes with the backlink
    cut off - a placement that cost a model call, looks published, and carries nothing.
    """
    for platform, limit in ps.truncating_platforms().items():
        spec = ps.spec_for(platform)
        projected = spec.word_target * ps.CHARS_PER_WORD
        assert projected <= limit - ps.LINK_RESERVE_CHARS + 1, (
            f"{platform}: a {spec.word_target}-word body is ~{projected:.0f} chars against "
            f"a {limit} ceiling, leaving no room for the appended link"
        )


def test_the_short_platforms_get_genuinely_short_budgets() -> None:
    """Pinned against the original behaviour: all of these used to get 900 words."""
    assert ps.word_target_for(pub.PLATFORM_BLUESKY) < 40
    assert ps.word_target_for(pub.PLATFORM_MASTODON) < 80
    assert ps.word_target_for(pub.PLATFORM_WARPCAST) < 40
    assert ps.word_target_for(pub.PLATFORM_BLOGGER) == ps.ARTICLE_WORD_TARGET


def test_a_platform_that_strips_markup_is_marked_so() -> None:
    """Twenty-one adapters run ``_html_to_text`` over the body. Headings and links the
    generator produced are discarded at publish time - tokens paid for and thrown away,
    and a writer that keeps producing them is being told nothing."""
    assert ps.spec_for(pub.PLATFORM_BLUESKY).strips_markup
    assert ps.spec_for(pub.PLATFORM_PASTEBIN).strips_markup
    assert not ps.spec_for(pub.PLATFORM_WORDPRESS).strips_markup
    assert not ps.spec_for(pub.PLATFORM_DEVTO).strips_markup


def test_the_note_platforms_do_not_ask_for_an_inline_link() -> None:
    """On a trailing-link platform an inline markdown link renders as literal syntax AND
    duplicates the link the adapter appends."""
    for platform in (pub.PLATFORM_BLUESKY, pub.PLATFORM_MASTODON, pub.PLATFORM_PASTEBIN):
        assert ps.spec_for(platform).link_style == "trailing"
    assert ps.spec_for(pub.PLATFORM_WORDPRESS).link_style == "inline"


def test_dev_to_tag_cap_matches_the_adapter_slice() -> None:
    assert ps.spec_for(pub.PLATFORM_DEVTO).max_tags == pub.DevToClient._MAX_TAGS


# --------------------------------------------------------------------------- #
# Honest defaults
# --------------------------------------------------------------------------- #
def test_an_uncatalogued_platform_promises_nothing() -> None:
    """A safe default is not a judgement. An unknown platform gets a plain article and a
    description that says nothing is known - never a confident set of conventions."""
    spec = ps.spec_for("Some New Blog 2029")
    assert spec is ps.UNKNOWN_SPEC
    assert spec.max_body_chars is None
    assert "nothing is known" in spec.evidence


def test_medium_has_no_content_model_and_is_refused_on_the_publish_path() -> None:
    """M05 A12: a platform marked unsupported has no publishing code path at all.

    The adapter still exists in this tree, so the refusal lives here - ``strict=True`` is
    what the publish path passes. Drafting stays permissive so an operator can still
    preview what a placement would look like.
    """
    assert pub.PLATFORM_MEDIUM not in ps.PLATFORM_SPECS
    assert pub.PLATFORM_MEDIUM in ps.UNSUPPORTED_PLATFORMS
    with pytest.raises(ps.PlatformUnsupported):
        ps.spec_for(pub.PLATFORM_MEDIUM, strict=True)
    assert ps.spec_for(pub.PLATFORM_MEDIUM) is ps.UNKNOWN_SPEC  # preview still works


def test_describe_states_the_hard_limit_in_words_a_writer_can_act_on() -> None:
    note = ps.spec_for(pub.PLATFORM_BLUESKY).describe()
    assert "HARD LIMIT 300" in note
    assert "TRUNCATES" in note
    assert re.search(r"about \d+ words", note)
    assert "do NOT write it inline" in note
