"""Unit tests for the JSON-LD structured-data generator + validator (P7A-5).

Pure/deterministic - no DB, no network, no LLM. Covers, per page type: the
correct @types emitted; SAB (areaServed) vs storefront (address); the
match-visible-content rejection; the fake-aggregateRating rejection; FAQ/HowTo
flagged non-rich-result; a missing required property flagged; and primary_type.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.content_schema import (
    AggregateRating,
    Author,
    Breadcrumb,
    Business,
    FaqItem,
    GeoCoordinates,
    HowToStep,
    OpeningHours,
    Page,
    PostalAddress,
    VisibleContent,
    build_json_ld,
    rich_result_eligible,
    validate_json_ld,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #
def _storefront() -> Business:
    return Business(
        name="Verde Plumbing",
        url="https://verdeplumbing.example",
        logo="https://verdeplumbing.example/logo.png",
        image="https://verdeplumbing.example/shop.jpg",
        telephone="+1 512-555-0100",
        business_type="Plumber",
        has_public_address=True,
        address=PostalAddress(
            street_address="12 Main Boulevard",
            address_locality="Austin",
            address_region="TX",
            postal_code="78701",
            address_country="US",
        ),
        geo=GeoCoordinates(latitude=30.2672, longitude=-97.7431),
        opening_hours=(OpeningHours(days=("Monday", "Tuesday"), opens="09:00", closes="17:00"),),
        price_range="$$",
        same_as=("https://facebook.com/verde",),
    )


def _sab() -> Business:
    return Business(
        name="Verde Mobile Plumbing",
        url="https://verdemobile.example",
        telephone="512-555-0111",
        business_type="Plumber",
        has_public_address=False,  # service-area business: no public address
        address=PostalAddress(street_address="secret depot", address_locality="Austin"),
        area_served=("Austin", "Round Rock"),
        price_range="$$",
    )


_BREADCRUMBS = (
    Breadcrumb(name="Home", url="https://verdeplumbing.example/"),
    Breadcrumb(name="Services", url="https://verdeplumbing.example/services"),
    Breadcrumb(name="Drain Cleaning"),
)


def _types(graph: dict) -> list[str]:
    return [n.get("@type") for n in graph["@graph"]]


# --------------------------------------------------------------------------- #
# service
# --------------------------------------------------------------------------- #
def test_service_emits_service_breadcrumb_and_organization() -> None:
    biz = _storefront()
    page = Page(
        url="https://verdeplumbing.example/drain-cleaning",
        title="Drain Cleaning",
        service_type="Drain Cleaning",
        area_served=("Austin",),
        description="Fast drain cleaning.",
    )
    graph = build_json_ld("service", biz, page, _BREADCRUMBS)
    assert graph["@context"] == "https://schema.org"
    assert _types(graph) == ["Service", "BreadcrumbList", "Organization"]

    service = graph["@graph"][0]
    assert service["serviceType"] == "Drain Cleaning"
    # provider references the Organization node by @id (correct nesting).
    assert service["provider"] == {"@id": "https://verdeplumbing.example#organization"}
    assert service["areaServed"] == ["Austin"]

    visible = VisibleContent(text="Drain Cleaning in Austin by Verde Plumbing. Call 512-555-0100.")
    result = validate_json_ld(graph, visible)
    assert result.valid, result.errors
    assert result.primary_type == "Service"


def test_service_missing_service_type_is_flagged() -> None:
    biz = _storefront()
    page = Page(url="https://verdeplumbing.example/x", title="Verde Plumbing")  # no service_type
    graph = build_json_ld("service", biz, page)
    result = validate_json_ld(graph, VisibleContent(text="Verde Plumbing"))
    assert not result.valid
    assert any("missing required property 'serviceType'" in e for e in result.errors)


# --------------------------------------------------------------------------- #
# local: storefront vs SAB
# --------------------------------------------------------------------------- #
def test_local_storefront_uses_address_not_area_served() -> None:
    biz = _storefront()
    page = Page(url="https://verdeplumbing.example/", title="Verde Plumbing")
    graph = build_json_ld("local", biz, page, _BREADCRUMBS)
    assert _types(graph) == ["Plumber", "BreadcrumbList", "Organization"]

    local = graph["@graph"][0]
    assert "address" in local
    assert "areaServed" not in local
    assert local["address"]["@type"] == "PostalAddress"
    assert local["address"]["addressCountry"] == "US"
    assert local["geo"] == {"@type": "GeoCoordinates", "latitude": 30.2672, "longitude": -97.7431}

    result = validate_json_ld(
        graph,
        VisibleContent(text="Verde Plumbing, 12 Main Boulevard, Austin, TX 78701. Call 512-555-0100."),
    )
    assert result.valid, result.errors
    assert result.primary_type == "Plumber"


def test_local_sab_uses_area_served_not_address() -> None:
    biz = _sab()
    page = Page(url="https://verdemobile.example/", title="Verde Mobile Plumbing")
    graph = build_json_ld("local", biz, page)
    local = graph["@graph"][0]
    # SAB: address is HIDDEN even though one was supplied; areaServed is used.
    assert "address" not in local
    assert local["areaServed"] == ["Austin", "Round Rock"]

    result = validate_json_ld(
        graph,
        VisibleContent(text="Verde Mobile Plumbing serving Austin and Round Rock. Call 512-555-0111."),
    )
    assert result.valid, result.errors


def test_local_missing_telephone_is_flagged() -> None:
    biz = Business(
        name="No Phone Co",
        url="https://nophone.example",
        business_type="LocalBusiness",
        has_public_address=False,
        area_served=("Austin",),
    )
    page = Page(url="https://nophone.example/", title="No Phone Co")
    graph = build_json_ld("local", biz, page)
    result = validate_json_ld(graph, VisibleContent(text="No Phone Co serving Austin"))
    assert not result.valid
    assert any("missing required property 'telephone'" in e for e in result.errors)


def test_local_without_address_or_area_served_is_flagged() -> None:
    biz = Business(
        name="Nowhere Co",
        url="https://nowhere.example",
        telephone="512-555-0000",
        business_type="LocalBusiness",
        has_public_address=False,  # no address published...
        area_served=(),  # ...and no area either
    )
    page = Page(url="https://nowhere.example/", title="Nowhere Co")
    graph = build_json_ld("local", biz, page)
    result = validate_json_ld(graph, VisibleContent(text="Nowhere Co 512-555-0000"))
    assert not result.valid
    assert any("address" in e and "areaServed" in e for e in result.errors)


# --------------------------------------------------------------------------- #
# blog
# --------------------------------------------------------------------------- #
def test_blog_emits_blogposting_breadcrumb_and_publisher_org() -> None:
    biz = _storefront()
    page = Page(
        url="https://verdeplumbing.example/blog/how-to-unclog",
        title="How to Unclog a Drain",
        author=Author(name="Jane Verde"),
        date_published="2026-07-01",
        date_modified="2026-07-10",
        description="A guide.",
        image="https://verdeplumbing.example/blog/hero.jpg",
    )
    graph = build_json_ld("blog", biz, page, _BREADCRUMBS)
    assert _types(graph) == ["BlogPosting", "BreadcrumbList", "Organization"]

    article = graph["@graph"][0]
    assert article["headline"] == "How to Unclog a Drain"
    assert article["author"] == {"@type": "Person", "name": "Jane Verde"}
    assert article["publisher"] == {"@id": "https://verdeplumbing.example#organization"}
    assert article["datePublished"] == "2026-07-01"

    result = validate_json_ld(graph, VisibleContent(text="How to Unclog a Drain - by Jane Verde"))
    assert result.valid, result.errors
    assert result.primary_type == "BlogPosting"


def test_blog_missing_author_is_flagged() -> None:
    biz = _storefront()
    page = Page(
        url="https://verdeplumbing.example/blog/x",
        title="Headline Here",
        date_published="2026-07-01",
    )  # no author
    graph = build_json_ld("blog", biz, page)
    result = validate_json_ld(graph, VisibleContent(text="Headline Here"))
    assert not result.valid
    assert any("missing required property 'author'" in e for e in result.errors)


# --------------------------------------------------------------------------- #
# match-visible-content
# --------------------------------------------------------------------------- #
def test_match_visible_rejects_claim_absent_from_page() -> None:
    biz = _storefront()
    page = Page(
        url="https://verdeplumbing.example/water-heater",
        title="Water Heater Install",
        service_type="Water Heater Installation",
        area_served=("Austin",),
    )
    graph = build_json_ld("service", biz, page)
    # Visible text never mentions "Water Heater Installation" -> rejected.
    visible = VisibleContent(text="We offer drain cleaning in Austin. Call 512-555-0100.")
    result = validate_json_ld(graph, visible)
    assert not result.valid
    assert any(
        "serviceType" in e and "not present in the visible content" in e for e in result.errors
    )


def test_match_visible_accepts_phone_despite_formatting() -> None:
    biz = _storefront()  # telephone "+1 512-555-0100"
    page = Page(url="https://verdeplumbing.example/", title="Verde Plumbing")
    graph = build_json_ld("local", biz, page)
    # Visible phone formatted differently, no country code - still matches.
    visible = VisibleContent(
        text="Verde Plumbing, 12 Main Boulevard, Austin, TX 78701. Phone: (512) 555.0100"
    )
    result = validate_json_ld(graph, visible)
    assert result.valid, result.errors


# --------------------------------------------------------------------------- #
# fake / self-serving aggregateRating
# --------------------------------------------------------------------------- #
def test_aggregate_rating_without_visible_reviews_is_rejected() -> None:
    biz = replace(_storefront(), aggregate_rating=AggregateRating(rating_value=4.9, review_count=87))
    page = Page(url="https://verdeplumbing.example/", title="Verde Plumbing")
    graph = build_json_ld("local", biz, page)
    assert "aggregateRating" in graph["@graph"][0]

    # has_reviews defaults False -> the rating is unbacked / self-serving.
    visible = VisibleContent(
        text="Verde Plumbing, 12 Main Boulevard, Austin, TX 78701. Call 512-555-0100.",
        has_reviews=False,
    )
    result = validate_json_ld(graph, visible)
    assert not result.valid
    assert any("self-serving/fake rating" in e for e in result.errors)


def test_aggregate_rating_with_real_reviews_is_accepted() -> None:
    biz = replace(_storefront(), aggregate_rating=AggregateRating(rating_value=4.9, review_count=87))
    page = Page(url="https://verdeplumbing.example/", title="Verde Plumbing")
    graph = build_json_ld("local", biz, page)
    visible = VisibleContent(
        text="Verde Plumbing, 12 Main Boulevard, Austin, TX 78701. Call 512-555-0100. 87 reviews.",
        has_reviews=True,
    )
    result = validate_json_ld(graph, visible)
    assert result.valid, result.errors


def test_generator_omits_aggregate_rating_when_no_reviews() -> None:
    biz = replace(_storefront(), aggregate_rating=AggregateRating(rating_value=5.0, review_count=0))
    page = Page(url="https://verdeplumbing.example/", title="Verde Plumbing")
    graph = build_json_ld("local", biz, page)
    # review_count == 0 -> the generator never emits the block.
    assert "aggregateRating" not in graph["@graph"][0]


# --------------------------------------------------------------------------- #
# FAQ / HowTo: emitted but flagged non-rich-result
# --------------------------------------------------------------------------- #
def test_faq_and_howto_are_emitted_but_flagged_non_rich() -> None:
    biz = _storefront()
    page = Page(
        url="https://verdeplumbing.example/blog/unclog",
        title="How to Unclog a Drain",
        author=Author(name="Jane Verde"),
        date_published="2026-07-01",
        faqs=(FaqItem(question="Is drain cleaning safe?", answer="Yes, when done by a pro."),),
        how_to_steps=(HowToStep(name="Turn off the water", text="Shut the valve."),),
    )
    graph = build_json_ld("blog", biz, page, _BREADCRUMBS)
    types = _types(graph)
    assert "FAQPage" in types and "HowTo" in types

    visible = VisibleContent(
        text=(
            "How to Unclog a Drain by Jane Verde. Is drain cleaning safe? "
            "Yes, when done by a pro. Turn off the water. Shut the valve."
        )
    )
    result = validate_json_ld(graph, visible)
    assert result.valid, result.errors
    assert result.rich_result_types["FAQPage"] is False
    assert result.rich_result_types["HowTo"] is False
    # But the article + breadcrumb ARE rich-eligible.
    assert result.rich_result_types["BlogPosting"] is True
    assert result.rich_result_types["BreadcrumbList"] is True
    assert result.rich_result_eligible is True


def test_rich_result_eligible_helper() -> None:
    assert rich_result_eligible("FAQPage") is False
    assert rich_result_eligible("HowTo") is False
    assert rich_result_eligible("LocalBusiness") is True
    assert rich_result_eligible("Plumber") is True
    assert rich_result_eligible("BlogPosting") is True
    assert rich_result_eligible("BreadcrumbList") is True
    # A node with errors is never eligible, whatever the type.
    assert rich_result_eligible("BlogPosting", has_errors=True) is False


# --------------------------------------------------------------------------- #
# correct nesting
# --------------------------------------------------------------------------- #
def test_address_as_bare_string_is_rejected() -> None:
    # A hand-rolled malformed graph: address is a string, not a PostalAddress.
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "LocalBusiness",
                "@id": "https://x.example#lb",
                "name": "Verde Plumbing",
                "telephone": "512-555-0100",
                "address": "12 Main Boulevard, Austin, TX",
            }
        ],
    }
    result = validate_json_ld(
        graph,
        VisibleContent(text="Verde Plumbing 12 Main Boulevard, Austin, TX 512-555-0100"),
    )
    assert not result.valid
    assert any("must be a PostalAddress object" in e for e in result.errors)


def test_breadcrumb_itemlist_must_be_well_formed() -> None:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "BreadcrumbList", "@id": "x#b", "itemListElement": [{"@type": "ListItem"}]}
        ],
    }
    result = validate_json_ld(graph, VisibleContent(text=""))
    assert not result.valid
    assert any("itemListElement" in e for e in result.errors)


# --------------------------------------------------------------------------- #
# primary_type + degenerate input
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("page_type", "expected"),
    [("service", "Service"), ("local", "Plumber"), ("blog", "BlogPosting")],
)
def test_primary_type_is_the_first_node_type(page_type: str, expected: str) -> None:
    biz = _storefront()
    page = Page(
        url="https://verdeplumbing.example/p",
        title="Verde Plumbing",
        service_type="Drain Cleaning",
        author=Author(name="Jane Verde"),
        date_published="2026-07-01",
    )
    graph = build_json_ld(page_type, biz, page)
    result = validate_json_ld(graph, VisibleContent(text="Verde Plumbing Drain Cleaning Jane Verde"))
    assert result.primary_type == expected


def test_empty_graph_is_invalid() -> None:
    result = validate_json_ld({"@context": "https://schema.org", "@graph": []}, VisibleContent())
    assert not result.valid
    assert result.primary_type is None
    assert any("no typed nodes" in e for e in result.errors)
