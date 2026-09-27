"""The plugin half of the whole-site delivery contract, read out of the PHP.

WHY A TEST THAT READS SOURCE. The AIOS Publisher plugin runs inside WordPress; there is
no PHP runtime in this repo's toolchain and no WordPress to host it, so its behaviour
cannot be exercised here. The alternative to a structural check is no check at all - and
the defect this pins was a plugin-side unconditional write that emptied live client
pages, so "no check at all" is not an option.

These assertions are about STRUCTURE AND PRESENCE, never formatting: which function
performs a write, whether a write sits behind a guard, whether both routes call the same
implementation. A reformat does not fail them; deleting a guard does.

THE FOUR GUARANTEES:

1. ``post_content`` is never written unconditionally. An absent ``content`` key means
   "leave the body alone" - the navigation rebuild sends no bodies, and writing '' over
   them blanked every page in a client's menu.
2. The ``/site`` route applies SEO meta, schema, design CSS and the full-width flag
   through the SAME functions ``/publish`` uses - it previously had no way to write any
   of them, so a page delivered as part of a site arrived with no meta at all.
3. There is exactly ONE Elementor-tree writer. Two copies is how the site route's copy
   came to lack the image-localization pass that the publish route's had.
4. Open Graph / Twitter values are written for both SEO plugins, and Rank Math's
   "mirror Facebook onto Twitter" switch is turned off so the explicit values apply.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PLUGIN = Path(__file__).resolve().parents[2] / "wordpress-plugin" / "aios-publisher"
_INCLUDES = _PLUGIN / "includes"


def _src(name: str) -> str:
    path = _INCLUDES / name
    assert path.is_file(), f"missing plugin include: {path}"
    return path.read_text(encoding="utf-8")


def _function_body(src: str, name: str) -> str:
    """The text of one PHP function, by brace matching from its signature."""
    match = re.search(rf"^function\s+{re.escape(name)}\s*\(", src, re.M)
    assert match, f"function {name} not found"
    start = src.index("{", match.end() - 1)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


# --------------------------------------------------------------------------- #
# 1. The body is never written unconditionally.
# --------------------------------------------------------------------------- #
def test_upsert_page_never_writes_post_content_unconditionally() -> None:
    """THE defect, pinned at its source. The old line was

        'post_content' => $content,

    inside the `$postarr` literal, so it ran for every delivery including the ones
    carrying no body. It must now be a guarded assignment.
    """
    body = _function_body(_src("site-assembler.php"), "aios_publisher_upsert_page")
    # Not present in the array literal that is always built...
    array_literal = body[body.index("$postarr = array("): body.index("// --- the body")]
    assert "post_content" not in array_literal, (
        "post_content is back in the unconditional $postarr literal - a delivery with "
        "no body would blank the live page"
    )
    # ...and the only assignment to it sits behind the write guard.
    assert "if ( $write_body ) {" in body
    guard_pos = body.index("if ( $write_body ) {")
    assignment_pos = body.index("$postarr['post_content']")
    assert assignment_pos > guard_pos, "post_content is assigned before/outside the guard"


def test_the_write_guard_distinguishes_absent_from_empty() -> None:
    """`array_key_exists`, not `empty()` / `isset()`: an explicitly empty body is a
    legitimate instruction and must still be written, while an ABSENT key must not."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_upsert_page")
    assert "array_key_exists( 'content', $page )" in body
    assert "$write_body   = $has_content && ( $is_new || ! $seed_only );" in body


def test_a_seed_body_is_only_written_when_creating_the_page() -> None:
    """The auto-created family hub's placeholder must never overwrite real landing copy
    an operator wrote on it."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_upsert_page")
    assert "content_only_if_new" in body
    assert "$is_new       = ! ( $existing instanceof WP_Post );" in body


# --------------------------------------------------------------------------- #
# 2. The post is targeted precisely (no more empty duplicates).
# --------------------------------------------------------------------------- #
def test_the_plan_post_is_resolved_by_id_then_by_type_then_by_the_other_type() -> None:
    body = _function_body(_src("site-assembler.php"), "aios_publisher_resolve_plan_post")
    id_pos = body.index("get_post( $post_id )")
    typed_pos = body.index("get_page_by_path( $slug, OBJECT, $post_type )")
    other_pos = body.index("get_page_by_path( $slug, OBJECT, $other )")
    assert id_pos < typed_pos < other_pos, "the lookup order is the fix; it must not reorder"


def test_no_lookup_hardcodes_the_page_post_type() -> None:
    """The duplicate-page defect was a hardcoded 'page' in the only lookup."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_resolve_plan_post")
    assert "OBJECT, 'page'" not in body


def test_an_existing_post_keeps_its_own_type() -> None:
    """Re-typing a live post would change its permalink and orphan every link to it."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_upsert_page")
    assert "$effective_type = ( $existing instanceof WP_Post ) ? $existing->post_type : $post_type;" in body


def test_only_a_hierarchical_type_gets_a_post_parent() -> None:
    body = _function_body(_src("site-assembler.php"), "aios_publisher_apply_hierarchy")
    assert "is_post_type_hierarchical( $child_type )" in body


def test_the_menu_scan_and_writes_are_post_type_aware() -> None:
    """A menu item pointing at a `post` was invisible to the de-dup scan (so each
    rebuild appended a duplicate) and was registered under the wrong object type."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_apply_menu")
    assert "in_array( $item->object, array( 'page', 'post' ), true )" in body
    assert "'menu-item-object'    => 'page'" not in body, "menu items still hardcode 'page'"
    assert body.count("$types[ $slug ]") >= 2


def test_only_a_page_can_become_the_front_page() -> None:
    """`show_on_front = page` pointing at a blog post shows visitors nothing."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_apply_front_page")
    assert "only a page can be the front page" in body


# --------------------------------------------------------------------------- #
# 3. Both routes share one implementation of every per-page write.
# --------------------------------------------------------------------------- #
_SHARED_WRITES = (
    "aios_publisher_apply_seo_meta",
    "aios_publisher_apply_schema_jsonld",
    "aios_publisher_apply_design_css",
    "aios_publisher_apply_elementor_tree",
)


@pytest.mark.parametrize("func", _SHARED_WRITES)
def test_each_shared_write_is_defined_exactly_once(func: str) -> None:
    """A duplicate definition is a PHP fatal error, and a near-duplicate is worse: the
    site route's own copy of the Elementor writer silently lacked image localization."""
    defined = sum(
        len(re.findall(rf"^function\s+{func}\s*\(", _src(name), re.M))
        for name in ("core-connector.php", "auto-publisher.php",
                     "design-reconstruction.php", "theme-adapter.php", "site-assembler.php")
    )
    assert defined == 1, f"{func} is defined {defined} times"


def test_the_site_route_applies_the_same_writes_as_the_publish_route() -> None:
    publish = _function_body(_src("auto-publisher.php"), "aios_publisher_rest_publish")
    site = _function_body(_src("site-assembler.php"), "aios_publisher_upsert_page")
    for func in ("aios_publisher_apply_seo_meta", "aios_publisher_apply_schema_jsonld",
                 "aios_publisher_apply_full_width", "aios_publisher_mark_managed"):
        assert func in publish, f"/publish no longer calls {func}"
        assert func in site, f"/site does not call {func} - pages arrive without it"
    assert "aios_publisher_apply_design_css" in site
    assert "aios_publisher_apply_elementor_tree" in site


def test_the_site_route_does_not_resideload_an_existing_featured_image() -> None:
    """A second delivery of the same plan would otherwise import a duplicate copy of
    the image on every run."""
    body = _function_body(_src("site-assembler.php"), "aios_publisher_upsert_page")
    assert "! has_post_thumbnail( $post_id )" in body


def test_an_image_already_on_this_site_is_never_resideloaded() -> None:
    """Sharing the Elementor writer with the IDEMPOTENT `/site` route is what makes this
    load-bearing. A local URL still matches `^https?://`, so without a host check every
    navigation rebuild would import a fresh copy of every image on every page and grow
    the client's media library without bound."""
    body = _function_body(
        _src("design-reconstruction.php"), "aios_publisher_localize_elementor_images"
    )
    assert "$own_host" in body
    assert "! $is_ours &&" in body, "the sideload is no longer gated on the host check"


# --------------------------------------------------------------------------- #
# 4. The social card.
# --------------------------------------------------------------------------- #
_YOAST_SOCIAL = (
    "_yoast_wpseo_opengraph-title",
    "_yoast_wpseo_opengraph-description",
    "_yoast_wpseo_opengraph-image",
    "_yoast_wpseo_twitter-title",
    "_yoast_wpseo_twitter-description",
    "_yoast_wpseo_twitter-image",
)
_RANK_MATH_SOCIAL = (
    "rank_math_facebook_title",
    "rank_math_facebook_description",
    "rank_math_facebook_image",
    "rank_math_twitter_title",
    "rank_math_twitter_description",
    "rank_math_twitter_image",
)


@pytest.mark.parametrize("key", _YOAST_SOCIAL + _RANK_MATH_SOCIAL)
def test_every_social_meta_key_is_written(key: str) -> None:
    """AIOS's own audit engine flags incomplete Open Graph (TECH-086/087) - including,
    before this, pages this plugin had just created."""
    body = _function_body(_src("auto-publisher.php"), "aios_publisher_apply_seo_meta")
    assert f"'{key}'" in body


def test_rank_math_is_told_not_to_mirror_facebook_onto_twitter() -> None:
    """Rank Math ignores the rank_math_twitter_* values unless this is 'off', so
    without it the explicit Twitter values are written and never used."""
    body = _function_body(_src("auto-publisher.php"), "aios_publisher_apply_seo_meta")
    assert "'rank_math_twitter_use_facebook', 'off'" in body


def test_the_social_values_fall_back_to_the_search_snippet() -> None:
    """A caller supplying only meta_title/meta_description means its card should match
    its search snippet - and both plugins would otherwise derive it through their own
    title TEMPLATE, which is neither controllable nor predictable."""
    body = _function_body(_src("auto-publisher.php"), "aios_publisher_apply_seo_meta")
    assert "$og_title = $meta_title;" in body
    assert "$og_desc = $meta_desc;" in body


def test_the_card_type_is_constrained_to_the_two_documented_values() -> None:
    body = _function_body(_src("auto-publisher.php"), "aios_publisher_apply_seo_meta")
    assert "array( 'summary', 'summary_large_image' )" in body


def test_no_seo_field_is_ever_blanked() -> None:
    """EVERY meta write in this function sits inside a conditional, because both routes
    can legitimately deliver a page without knowing its meta - and overwriting a good
    SEO title with '' is worse than leaving it.

    Checked by brace depth rather than by eyeballing: a write at depth 1 is directly in
    the function body, i.e. unconditional. Add an unguarded `update_post_meta` anywhere
    in this function and this fails, whatever it is named.
    """
    body = _function_body(_src("auto-publisher.php"), "aios_publisher_apply_seo_meta")
    depth = 0
    unguarded: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        # The write's depth is the depth BEFORE this line's own braces are counted.
        if "update_post_meta(" in stripped and depth <= 1:
            unguarded.append(stripped)
        depth += line.count("{") - line.count("}")
    assert not unguarded, f"unconditional meta writes would blank live values: {unguarded}"
    # And the guards are non-empty checks, not truthiness tests that would also skip a
    # legitimate "0" value.
    assert body.count("if ( '' !== ") >= 6
    assert body.count("update_post_meta(") >= 12


def test_the_capability_probe_reports_the_new_meta_keys() -> None:
    """The platform asks the site which meta keys it will accept. A key we write but do
    not declare is invisible to that negotiation."""
    body = _function_body(_src("core-connector.php"), "aios_publisher_known_meta_keys")
    for key in _YOAST_SOCIAL + _RANK_MATH_SOCIAL:
        assert f"'{key}'" in body, f"{key} is written but not declared"


# --------------------------------------------------------------------------- #
# 5. Structural sanity (no PHP runtime here, so this is the load-time check).
# --------------------------------------------------------------------------- #
def test_no_plugin_function_is_called_without_being_defined() -> None:
    files = [_PLUGIN / "aios-publisher.php", *sorted(_INCLUDES.glob("*.php"))]
    defined: set[str] = set()
    called: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        defined |= set(re.findall(r"^function\s+(aios_publisher_\w+)\s*\(", text, re.M))
        called |= set(re.findall(r"\b(aios_publisher_\w+)\s*\(", text))
    missing = sorted(called - defined)
    assert not missing, f"called but never defined (PHP fatal at call time): {missing}"


def test_the_plugin_version_was_bumped_for_this_contract() -> None:
    """The platform's `/site` caller reports a version in its error message when the
    route is missing; a plugin shipping these writes must be distinguishable."""
    main = (_PLUGIN / "aios-publisher.php").read_text(encoding="utf-8")
    match = re.search(r"AIOS_PUBLISHER_VERSION', '(\d+)\.(\d+)\.(\d+)'", main)
    assert match, "version constant not found"
    major, minor, _patch = (int(g) for g in match.groups())
    assert (major, minor) >= (1, 14), "these writes ship in 1.14.0 or newer"
