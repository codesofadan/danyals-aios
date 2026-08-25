"""P6.4: reading what a target WordPress site can actually do.

The compatibility half of these tests matters more than the feature half. Plugin 1.7.0
is on real client sites RIGHT NOW and cannot answer any of these questions, so the
platform must handle "I don't know" without changing how those sites are published to.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.editor_mode import resolve_editor_mode
from app.services.site_capabilities import parse_ping, verify_meta_write

pytestmark = pytest.mark.unit

_META = ["_yoast_wpseo_title", "_yoast_wpseo_metadesc", "_elementor_data"]


def _ping_170() -> dict[str, Any]:
    """Exactly what the shipped 1.7.0 plugin returns. No capabilities key."""
    return {"ok": True, "site": "https://client.test", "name": "Client",
            "plugin_version": "1.7.0"}


def _ping_180(**over: Any) -> dict[str, Any]:
    caps: dict[str, Any] = {
        "wp_version": "6.5.2",
        "active_theme": {"name": "Astra", "stylesheet": "astra", "template": "astra"},
        "elementor": True,
        "elementor_version": "3.21.0",
        "gutenberg": True,
        "registered_meta_keys": {
            "post": ["_yoast_wpseo_title", "_yoast_wpseo_metadesc"],
            "page": ["_yoast_wpseo_title"],
        },
    }
    caps.update(over)
    return {"ok": True, "site": "https://client.test", "name": "Client",
            "plugin_version": "1.8.0", "capabilities": caps}


class TestAnOldPluginDoesNotSilentlyDowngradeASite:
    """Reading "no capabilities" as "no Elementor" would downgrade every site running
    1.7.0 from Elementor to Gutenberg the moment this shipped - a fleet-wide
    regression, invisible, caused by upgrading the PLATFORM rather than the site."""

    def test_the_shipped_170_ping_parses_as_unknown_not_as_absent(self) -> None:
        caps = parse_ping(_ping_170())
        assert caps.known is False
        assert caps.plugin_version == "1.7.0"

    @pytest.mark.parametrize("configured", [True, False])
    def test_an_unknown_site_keeps_the_configured_default(self, configured: bool) -> None:
        caps = parse_ping(_ping_170())
        assert caps.elementor_available(configured_default=configured) is configured

    def test_the_resolver_behaves_exactly_as_before_for_an_old_plugin(self) -> None:
        """The end-to-end statement: publishing to a 1.7.0 site is unchanged."""
        caps = parse_ping(_ping_170())
        for requested in ("auto", "elementor", "gutenberg", "hybrid"):
            before = resolve_editor_mode(requested, elementor_available=True)
            after = resolve_editor_mode(
                requested, elementor_available=caps.elementor_available(configured_default=True)
            )
            assert before == after

    def test_the_reason_is_recorded_rather_than_silent(self) -> None:
        assert any("no capabilities" in n for n in parse_ping(_ping_170()).notes)


class TestASiteThatCanAnswerIsBelieved:
    def test_elementor_present_is_used_over_the_configured_default(self) -> None:
        """The operator's flag is a guess about a site none of us has looked at."""
        caps = parse_ping(_ping_180(elementor=True))
        assert caps.elementor_available(configured_default=False) is True

    def test_elementor_absent_is_used_over_the_configured_default(self) -> None:
        """The direction that actually saves a broken publish: the operator ticked the
        box, the plugin is not installed, and we would have written _elementor_data
        onto a site with nothing to read it."""
        caps = parse_ping(_ping_180(elementor=False, elementor_version=None))
        assert caps.elementor_available(configured_default=True) is False

    def test_the_reported_details_are_carried(self) -> None:
        caps = parse_ping(_ping_180())
        assert caps.wp_version == "6.5.2"
        assert caps.theme_name == "Astra" and caps.theme_stylesheet == "astra"
        assert caps.elementor_version == "3.21.0" and caps.gutenberg is True

    def test_elementor_active_without_a_version_is_noted(self) -> None:
        caps = parse_ping(_ping_180(elementor=True, elementor_version=""))
        assert caps.elementor is True
        assert any("no version" in n for n in caps.notes)


class TestAHostileOrBrokenPingCannotBreakPublishing:
    """The body comes from a client's server. A publish path must not be breakable by
    what it returns."""

    @pytest.mark.parametrize(
        "payload",
        [None, [], "", 0, {"capabilities": "not-a-dict"}, {"capabilities": []}],
    )
    def test_an_unreadable_response_degrades_to_unknown(self, payload: Any) -> None:
        """No usable capabilities block at all is the same state as an old plugin:
        we learned nothing, so nothing about the site's handling changes."""
        caps = parse_ping(payload)
        assert caps.known is False
        assert caps.elementor_available(configured_default=True) is True

    @pytest.mark.parametrize(
        "payload",
        [{"capabilities": {"registered_meta_keys": "nope"}},
         {"capabilities": {"active_theme": "nope", "elementor": "yes"}},
         {"capabilities": {}}],
    )
    def test_a_readable_block_with_garbage_fields_answers_safely(self, payload: Any) -> None:
        """DIFFERENT from unknown, deliberately. The site DID answer - it just could
        not confirm Elementor - so the answer is taken and it is "no". Gutenberg
        renders on every WordPress install; writing `_elementor_data` to a site with
        nothing to read it produces a page that shows nothing at all. Degrading is the
        safe direction and overriding the operator's flag here is the point."""
        caps = parse_ping(payload)
        assert caps.known is True
        assert caps.elementor_available(configured_default=True) is False

    def test_a_garbage_theme_does_not_break_the_rest_of_the_report(self) -> None:
        caps = parse_ping({"capabilities": {"active_theme": "nope", "gutenberg": True}})
        assert caps.theme_name == "" and caps.gutenberg is True

    def test_a_string_true_is_not_a_boolean_true(self) -> None:
        """`"yes"` and `1` are truthy in Python. Only a real `true` means Elementor is
        installed, or a site could enable it with any non-empty value."""
        for value in ("yes", 1, "true", [1]):
            caps = parse_ping(_ping_180(elementor=value))
            assert caps.elementor is False, value


class TestTheMetaKeysThatWouldBeSilentlyDropped:
    def test_registered_keys_are_writable_and_the_rest_are_held(self) -> None:
        """WordPress drops an unregistered REST meta write and answers 200 with the OLD
        value. Declining to send it and reporting HELD is an honest outcome; sending it
        and reporting success is not."""
        plan = parse_ping(_ping_180()).meta_plan(_META, post_type="post")
        assert set(plan.writable) == {"_yoast_wpseo_title", "_yoast_wpseo_metadesc"}
        assert plan.held == ("_elementor_data",)
        assert any("silently dropped" in n for n in plan.notes())

    def test_registration_is_per_post_type(self) -> None:
        plan = parse_ping(_ping_180()).meta_plan(_META, post_type="page")
        assert plan.writable == ("_yoast_wpseo_title",)
        assert "_yoast_wpseo_metadesc" in plan.held

    def test_an_old_plugin_leaves_every_key_unverified_and_still_sends_it(self) -> None:
        """Withholding on a maybe would break every site running an older plugin.
        They are sent, then confirmed by re-read."""
        plan = parse_ping(_ping_170()).meta_plan(_META)
        assert plan.unverified == tuple(_META)
        assert plan.writable == () and plan.held == ()
        assert set(plan.to_send) == set(_META)

    def test_held_keys_are_never_sent(self) -> None:
        plan = parse_ping(_ping_180()).meta_plan(_META)
        assert "_elementor_data" not in plan.to_send

    def test_duplicate_keys_are_collapsed(self) -> None:
        plan = parse_ping(_ping_180()).meta_plan(["_yoast_wpseo_title"] * 3)
        assert plan.writable == ("_yoast_wpseo_title",)


class TestVerifyingAWriteActuallyLanded:
    """The check `WordPressClient.update_post` says the caller must perform."""

    def test_a_matching_value_is_confirmed(self) -> None:
        confirmed, dropped = verify_meta_write(
            {"_yoast_wpseo_title": "Slab Leak Repair"},
            {"meta": {"_yoast_wpseo_title": "Slab Leak Repair"}},
        )
        assert confirmed == ("_yoast_wpseo_title",) and dropped == ()

    def test_the_old_value_coming_back_is_a_drop_not_a_success(self) -> None:
        """This is the whole failure mode: status 200, old value, nothing written."""
        confirmed, dropped = verify_meta_write(
            {"_yoast_wpseo_title": "New Title"},
            {"meta": {"_yoast_wpseo_title": "Old Title"}},
        )
        assert confirmed == () and dropped == ("_yoast_wpseo_title",)

    def test_an_absent_key_is_a_drop(self) -> None:
        _c, dropped = verify_meta_write({"rank_math_title": "x"}, {"meta": {}})
        assert dropped == ("rank_math_title",)

    def test_a_response_with_no_meta_at_all_is_all_dropped(self) -> None:
        _c, dropped = verify_meta_write({"a": "1", "b": "2"}, {"id": 7})
        assert set(dropped) == {"a", "b"}

    def test_a_number_round_tripped_as_a_string_still_counts_as_written(self) -> None:
        """WordPress stores meta as strings; `1` coming back as `"1"` is not a drop."""
        confirmed, dropped = verify_meta_write({"_elementor_edit_mode": 1},
                                               {"meta": {"_elementor_edit_mode": "1"}})
        assert confirmed == ("_elementor_edit_mode",) and dropped == ()

    def test_a_malformed_response_is_treated_as_everything_dropped(self) -> None:
        """The safe direction: report nothing landed rather than claim it did."""
        _c, dropped = verify_meta_write({"a": "1"}, "not a dict")
        assert dropped == ("a",)
