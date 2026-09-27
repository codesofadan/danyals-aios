"""Resolving a pasted Maps link to a centre + a verified identity, with no network.

Every provider call is monkeypatched at this module's OWN seams (`_fetch_details`,
`_search_biased`, `_follow_short_link`), so these run offline and deterministically -
the same rule the grid provider's own suite keeps.

The properties worth protecting here are the honest-degrade ones. It is easy to write
this resolver so that a failed Places lookup silently yields a centre that LOOKS
verified; the whole design intent is that an unverified identity stays visibly
unverified all the way to the NAP write-back, which reads that exact flag.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.modules.grid_tracker import maps_center as mc

PLACE_URL = (
    "https://www.google.com/maps/place/Karachi+Biryani+House/"
    "@24.8607343,67.0011364,17z/data=!3m1!4b1!4m6!3m5!"
    "1s0x3eb33e06651d4bbf:0x82d6e1a4a37b8d1c!8m2!3d24.8612211!4d67.0009876!16s%2Fg%2F11abc"
)

PLACE_ID_URL = (
    "https://www.google.com/maps/search/?api=1&query=x&query_place_id=ChIJAbCdEfGhIjKlMn"
)

DETAILS_PAYLOAD = {
    "id": "ChIJAbCdEfGhIjKlMn",
    "displayName": {"text": "Karachi Biryani House"},
    "formattedAddress": "12 Main Boulevard, Karachi 75500, Pakistan",
    "addressComponents": [
        {"types": ["locality"], "longText": "Karachi"},
        {"types": ["administrative_area_level_1"], "longText": "Sindh"},
        {"types": ["postal_code"], "longText": "75500"},
    ],
    "nationalPhoneNumber": "021 3456 7890",
    "websiteUri": "https://example.test",
    "location": {"latitude": 24.8612211, "longitude": 67.0009876},
    "googleMapsUri": "https://maps.google.com/?cid=9427970967180381468",
}


@pytest.fixture
def settings() -> Settings:
    """Settings with a Places key present - the lookups are faked, the key only gates."""
    return Settings(google_places_api_key="test-key")  # type: ignore[arg-type]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any real provider seam is reached without being stubbed."""
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("a real network seam was called")

    monkeypatch.setattr(mc, "_fetch_details", boom)
    monkeypatch.setattr(mc, "_search_biased", boom)
    monkeypatch.setattr(mc, "_follow_short_link", boom)


def test_place_id_resolves_through_details(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact path: one listing, by key, with Google's own coordinate."""
    seen: dict[str, str] = {}

    def fake_details(api_key: str, place_id: str, **_k: object) -> dict:
        seen["place_id"] = place_id
        return DETAILS_PAYLOAD

    monkeypatch.setattr(mc, "_fetch_details", fake_details)
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: pytest.fail("searched"))

    center = mc.resolve_maps_url(settings, PLACE_ID_URL)

    assert seen["place_id"] == "ChIJAbCdEfGhIjKlMn"
    assert center.source == "places_details"
    assert center.identity_verified is True
    assert center.name == "Karachi Biryani House"
    assert center.city == "Karachi"
    assert center.region == "Sindh"
    assert center.postal_code == "75500"
    assert center.phone == "021 3456 7890"
    assert center.lat == pytest.approx(24.8612211)
    assert center.is_precise is True


def test_cid_url_searches_biased_to_the_pin(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No by-CID endpoint exists, so the fallback must be CONSTRAINED to the pin."""
    captured: dict[str, object] = {}

    def fake_search(api_key: str, query: str, lat: float, lng: float, **_k: object) -> dict:
        captured.update({"query": query, "lat": lat, "lng": lng})
        return DETAILS_PAYLOAD

    monkeypatch.setattr(mc, "_fetch_details", lambda *a, **k: None)
    monkeypatch.setattr(mc, "_search_biased", fake_search)

    center = mc.resolve_maps_url(settings, PLACE_URL)

    # Biased to the PIN, not the viewport - the same precedence the parser enforces.
    assert captured["lat"] == pytest.approx(24.8612211)
    assert captured["lng"] == pytest.approx(67.0009876)
    assert captured["query"] == "Karachi Biryani House"
    assert center.source == "places_biased"
    assert center.identity_verified is True


def test_a_match_far_from_the_pin_is_rejected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE REGRESSION TEST FOR THE DEFECT THIS FEATURE EXISTS TO PREVENT.

    Measured on the first live call: `locationBias` is a bias, not a restriction.
    Handed a 50m circle around a Karachi pin, Places answered with a business 11km
    away and the resolver reported it verified - a confident answer about the wrong
    business, produced by the code meant to stop exactly that.

    The distance check is ours precisely because the provider's constraint is advisory.
    """
    far_away = {
        **DETAILS_PAYLOAD,
        "displayName": {"text": "A Completely Different Restaurant"},
        "location": {"latitude": 24.9208326, "longitude": 67.1015918},  # ~11km off
    }
    monkeypatch.setattr(mc, "_fetch_details", lambda *a, **k: None)
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: far_away)

    center = mc.resolve_maps_url(settings, PLACE_URL)

    assert center.identity_verified is False
    assert center.reason == "match_too_far"
    assert center.name == ""  # the wrong business must not reach the NAP write-back
    # The operator's own pin survives - it was never the thing in doubt.
    assert center.lat == pytest.approx(24.8612211)
    assert center.lng == pytest.approx(67.0009876)


def test_a_match_at_the_pin_is_accepted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tolerance must not be so tight that Google's own rooftop coordinate fails."""
    # ~40m from the pin: a rooftop-vs-entrance difference for the SAME premises.
    nearby = {**DETAILS_PAYLOAD, "location": {"latitude": 24.8615800, "longitude": 67.0009876}}
    monkeypatch.setattr(mc, "_fetch_details", lambda *a, **k: None)
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: nearby)

    center = mc.resolve_maps_url(settings, PLACE_URL)

    assert center.identity_verified is True
    assert center.name == "Karachi Biryani House"


def test_metres_between_is_sane() -> None:
    """A wrong distance function would silently disable the guard above."""
    # One degree of latitude is ~111km.
    assert mc._metres_between(0.0, 0.0, 1.0, 0.0) == pytest.approx(111_195, rel=0.01)
    assert mc._metres_between(24.86, 67.0, 24.86, 67.0) == pytest.approx(0.0, abs=1e-6)


def test_lookup_failure_degrades_to_the_pin_and_says_so(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider failure keeps the coordinate and REFUSES to claim an identity."""
    monkeypatch.setattr(mc, "_fetch_details", lambda *a, **k: None)
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: None)

    center = mc.resolve_maps_url(settings, PLACE_URL)

    assert center.lat == pytest.approx(24.8612211)
    assert center.source == "maps_pin"
    assert center.identity_verified is False
    assert center.reason == "identity_lookup_failed"
    # The URL slug must NOT leak into a field the NAP write-back would copy.
    assert center.name == ""
    assert center.address == ""


def test_keyless_deploy_still_gets_a_centre(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Places key is a degrade, not a failure - the pin is in the URL already."""
    monkeypatch.setattr(mc, "_fetch_details", lambda *a, **k: pytest.fail("called"))
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: pytest.fail("called"))

    center = mc.resolve_maps_url(Settings(), PLACE_URL)

    assert center.lat == pytest.approx(24.8612211)
    assert center.identity_verified is False
    assert center.reason == "no_places_key"


def test_short_link_is_expanded_then_parsed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mc, "_follow_short_link", lambda url, **k: PLACE_URL)
    monkeypatch.setattr(mc, "_fetch_details", lambda *a, **k: None)
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: DETAILS_PAYLOAD)

    center = mc.resolve_maps_url(settings, "https://maps.app.goo.gl/AbCdEf123")

    assert center.identity_verified is True
    assert center.lat == pytest.approx(24.8612211)


def test_unexpandable_short_link_refuses_with_a_usable_message(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mc, "_follow_short_link", lambda url, **k: "")

    with pytest.raises(mc.MapsUrlError) as excinfo:
        mc.resolve_maps_url(settings, "https://maps.app.goo.gl/AbCdEf123")
    assert excinfo.value.code == "short_link_unresolved"


def test_not_a_maps_url_refuses(settings: Settings, no_network: None) -> None:
    with pytest.raises(mc.MapsUrlError) as excinfo:
        mc.resolve_maps_url(settings, "https://www.bing.com/maps?q=x")
    assert excinfo.value.code == "not_a_maps_url"


def test_maps_url_with_no_location_refuses(settings: Settings, no_network: None) -> None:
    with pytest.raises(mc.MapsUrlError) as excinfo:
        mc.resolve_maps_url(settings, "https://www.google.com/maps")
    assert excinfo.value.code == "no_location_in_url"


def test_place_without_coordinates_is_not_a_centre_of_zero_zero(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Details reply missing `location` must fall through, never become (0, 0)."""
    monkeypatch.setattr(
        mc, "_fetch_details",
        lambda *a, **k: {**DETAILS_PAYLOAD, "location": None},
    )
    monkeypatch.setattr(mc, "_search_biased", lambda *a, **k: None)

    center = mc.resolve_maps_url(settings, PLACE_URL)

    assert (center.lat, center.lng) != (0.0, 0.0)
    assert center.lat == pytest.approx(24.8612211)
    assert center.identity_verified is False
