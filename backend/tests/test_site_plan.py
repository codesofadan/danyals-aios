"""P6.5: turning produced pages into ONE site order.

The publish path sent one page at a time and nothing built a menu, set a homepage or
nested a page - verified by grep: `wp_create_nav_menu`, `page_on_front`, `post_parent`
and `menu_order` appear nowhere on either side. So fifty individually-correct,
individually-Elementor-editable pages arrived as fifty unlinked drafts, and the client
assembled the site by hand.

These tests are mostly about what the plan REFUSES to send, because it writes to a live
WordPress install.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.site_plan import MAX_MENU_DEPTH, build_site_plan, slugify

pytestmark = pytest.mark.unit


def _page(slug: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"slug": slug, "title": slug.replace("-", " ").title(),
                            "content": "<p>x</p>"}
    base.update(over)
    return base


class TestSlugIdentity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("Slab Leak Repair", "slab-leak-repair"), ("  Water Heater  ", "water-heater"),
         ("Emergency/24-7", "emergency-24-7"), ("Café Service", "caf-service"),
         ("---", ""), ("", "")],
    )
    def test_the_slug_matches_what_wordpress_will_store(self, raw: str, expected: str) -> None:
        """Identity matters more than prettiness here. If our key differs from the one
        WordPress stores, a page is created once and never matched again - and every
        republish makes a duplicate."""
        assert slugify(raw) == expected

    def test_a_page_with_only_a_title_gets_a_slug(self) -> None:
        plan = build_site_plan([{"title": "Slab Leak Repair"}])
        assert plan.pages[0].slug == "slab-leak-repair"

    def test_a_page_with_neither_is_an_issue_not_a_guess(self) -> None:
        plan = build_site_plan([{"content": "orphan"}])
        assert not plan.valid and "neither" in plan.issues[0]


class TestWhatItRefusesToSend:
    def test_duplicate_slugs_are_refused(self) -> None:
        """WordPress would rename the second to "-2" and the plan's parent references
        would then resolve to the wrong page."""
        plan = build_site_plan([_page("services"), _page("services")])
        assert not plan.valid
        assert "duplicate slug" in plan.issues[0]

    def test_a_parent_outside_the_plan_is_refused(self) -> None:
        """WordPress would silently create the child at the top level, so the site
        would come out flat and nobody would be told."""
        plan = build_site_plan([_page("slab-leak", parent_slug="services")])
        assert not plan.valid
        assert "not in this plan" in plan.issues[0]

    def test_a_parent_cycle_is_caught_here_not_on_the_clients_server(self) -> None:
        """A cycle would make the plugin's parent resolution loop forever."""
        plan = build_site_plan([
            _page("a", parent_slug="b"), _page("b", parent_slug="a")])
        assert not plan.valid
        assert any("cycle" in i for i in plan.issues)

    def test_a_three_page_cycle_is_caught(self) -> None:
        plan = build_site_plan([
            _page("a", parent_slug="c"), _page("b", parent_slug="a"),
            _page("c", parent_slug="b")])
        assert any("cycle" in i for i in plan.issues)

    def test_a_front_page_not_in_the_plan_is_refused(self) -> None:
        plan = build_site_plan([_page("about")], front_page_slug="home")
        assert not plan.valid

    def test_an_empty_plan_is_refused(self) -> None:
        assert not build_site_plan([]).valid

    def test_an_invalid_plan_still_reports_everything_wrong_with_it(self) -> None:
        """One issue at a time would mean an operator fixes, resubmits, fixes again."""
        plan = build_site_plan(
            [_page("a"), _page("a"), _page("b", parent_slug="ghost")],
            front_page_slug="nowhere",
        )
        assert len(plan.issues) >= 3


class TestTheLiveSiteSafeties:
    def test_the_front_page_is_untouched_unless_asked_for(self) -> None:
        """`show_on_front` changes what every visitor sees. Silence must mean no."""
        plan = build_site_plan([_page("about")])
        assert plan.front_page_slug == ""
        assert plan.payload()["front_page_slug"] == ""
        assert any("untouched" in n for n in plan.notes)

    def test_an_existing_menu_is_not_replaced_by_default(self) -> None:
        """The client's navigation is theirs."""
        plan = build_site_plan([_page("about")], menu_location="primary")
        assert plan.payload()["menu"]["replace_existing"] is False

    def test_replacing_a_menu_must_be_asked_for_explicitly(self) -> None:
        plan = build_site_plan([_page("a")], menu_location="primary",
                               replace_existing_menu=True)
        assert plan.payload()["menu"]["replace_existing"] is True

    def test_the_default_status_is_draft(self) -> None:
        """A human presses Publish on the WordPress side, as the plugin has always
        required."""
        assert build_site_plan([_page("a")]).payload()["status"] == "draft"

    def test_nothing_in_the_payload_can_delete(self) -> None:
        """A page the client wrote is not ours to remove, and a plan that can delete is
        a plan that can lose their work on a bad slug."""
        payload = build_site_plan([_page("a")]).payload()
        flat = str(payload).lower()
        for word in ("delete", "remove", "trash", "purge"):
            assert word not in flat


class TestHierarchyAndMenu:
    def test_a_valid_parent_child_plan_is_accepted(self) -> None:
        plan = build_site_plan([
            _page("services"), _page("slab-leak", parent_slug="services")])
        assert plan.valid
        assert plan.pages[1].parent_slug == "services"

    def test_deep_nesting_is_allowed_but_flagged(self) -> None:
        """Most themes render two levels. The page should still exist - it just may not
        appear in the nav, and saying so beats silently dropping it."""
        pages = [_page("a"), _page("b", parent_slug="a"), _page("c", parent_slug="b")]
        plan = build_site_plan(pages)
        assert plan.valid
        assert any("levels deep" in n for n in plan.notes)

    def test_pages_can_be_excluded_from_the_menu(self) -> None:
        plan = build_site_plan([_page("a"), _page("thanks", in_menu=False)])
        assert plan.payload()["pages"][1]["in_menu"] is False

    def test_a_menu_location_with_no_navigable_pages_is_noted(self) -> None:
        plan = build_site_plan([_page("a", in_menu=False)], menu_location="primary")
        assert any("no page is marked in_menu" in n for n in plan.notes)

    def test_menu_order_is_carried(self) -> None:
        plan = build_site_plan([_page("a", menu_order=3)])
        assert plan.payload()["pages"][0]["menu_order"] == 3


class TestThePayload:
    def test_elementor_data_rides_along_per_page(self) -> None:
        """This is what makes the delivered site editable: each page carries its own
        widget tree, so the client opens any of them in Elementor and edits natively."""
        plan = build_site_plan([_page("a", elementor_data='[{"elType":"section"}]')])
        assert plan.payload()["pages"][0]["elementor_data"].startswith("[")

    def test_the_payload_shape_is_stable(self) -> None:
        payload = build_site_plan([_page("a")], menu_location="primary").payload()
        assert set(payload) == {"status", "pages", "menu", "front_page_slug"}
        assert set(payload["menu"]) == {"name", "location", "replace_existing"}
