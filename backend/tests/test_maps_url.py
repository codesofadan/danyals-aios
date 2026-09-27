"""The Maps-URL parser: what a pasted link is allowed to assert.

The load-bearing test in this file is `test_pin_beats_viewport`. Every other property
here protects a field; that one protects the ACCURACY CLAIM the feature was built on.
A URL carries both the camera position and the listing's own pin, they differ by
whatever the operator panned before copying, and picking the wrong one produces a grid
that is off by a block with nothing on screen to say so.
"""

from __future__ import annotations

import pytest

from app.services.maps_url import is_maps_url, parse_maps_url

# A real place URL shape: viewport at @, pin in the data block, ftid, name slug.
PLACE_URL = (
    "https://www.google.com/maps/place/Karachi+Biryani+House/"
    "@24.8607343,67.0011364,17z/data=!3m1!4b1!4m6!3m5!"
    "1s0x3eb33e06651d4bbf:0x82d6e1a4a37b8d1c!8m2!3d24.8612211!4d67.0009876!16s%2Fg%2F11abc"
)


def test_recognises_google_hosts() -> None:
    for url in (
        "https://www.google.com/maps/place/X/@1,2,17z",
        "https://maps.google.com/?cid=123",
        "https://maps.app.goo.gl/AbCdEf123",
        "https://www.google.co.uk/maps/place/X/@1,2,17z",
        "https://www.google.com.pk/maps/place/X/@1,2,17z",
    ):
        assert is_maps_url(url), url


def test_rejects_lookalike_and_non_urls() -> None:
    # The substring trap: a host that merely CONTAINS google.com.
    assert not is_maps_url("https://google.com.evil.tld/maps/place/X/@1,2,17z")
    assert not is_maps_url("https://www.bing.com/maps?q=x")
    assert not is_maps_url("not a url at all")
    assert not is_maps_url("")
    assert not is_maps_url("ftp://www.google.com/maps")
    assert parse_maps_url("https://www.bing.com/maps?q=x") is None


def test_pin_beats_viewport() -> None:
    """The listing's own coordinate wins over the camera's. This is the whole point."""
    parsed = parse_maps_url(PLACE_URL)
    assert parsed is not None
    # The pin (!3d/!4d), NOT the viewport (@24.8607343,67.0011364).
    assert parsed.lat == pytest.approx(24.8612211)
    assert parsed.lng == pytest.approx(67.0009876)
    assert parsed.coord_source == "pin"
    assert parsed.is_precise is True


def test_viewport_used_only_when_there_is_no_pin() -> None:
    parsed = parse_maps_url("https://www.google.com/maps/@24.8607343,67.0011364,17z")
    assert parsed is not None
    assert parsed.lat == pytest.approx(24.8607343)
    assert parsed.coord_source == "viewport"
    assert parsed.is_precise is False
    # A dropped pin names no business.
    assert parsed.has_identity is False


def test_ftid_yields_the_cid_as_an_exact_decimal_string() -> None:
    """A CID is 64-bit. Any float in this path silently corrupts its last digits."""
    parsed = parse_maps_url(PLACE_URL)
    assert parsed is not None
    assert parsed.ftid == "0x3eb33e06651d4bbf:0x82d6e1a4a37b8d1c"
    assert parsed.cid == str(int("0x82d6e1a4a37b8d1c", 16))
    assert parsed.cid == "9427970967180381468"
    assert parsed.has_identity is True


def test_explicit_cid_url() -> None:
    parsed = parse_maps_url("https://maps.google.com/?cid=9427970967180381468")
    assert parsed is not None
    assert parsed.cid == "9427970967180381468"
    assert parsed.has_coords is False  # a cid link carries no coordinate


def test_place_id_from_query_and_from_q_param() -> None:
    a = parse_maps_url(
        "https://www.google.com/maps/search/?api=1&query=cafe"
        "&query_place_id=ChIJN1t_tDeuEmsRUsoyG83frY4"
    )
    assert a is not None and a.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"

    b = parse_maps_url(
        "https://www.google.com/maps/place/?q=place_id:ChIJN1t_tDeuEmsRUsoyG83frY4"
    )
    assert b is not None and b.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"


def test_short_link_is_reported_not_guessed() -> None:
    parsed = parse_maps_url("https://maps.app.goo.gl/AbCdEf123")
    assert parsed is not None
    assert parsed.needs_resolution is True
    assert parsed.has_coords is False
    assert parsed.has_identity is False


def test_name_slug_is_decoded_as_a_hint_only() -> None:
    parsed = parse_maps_url(PLACE_URL)
    assert parsed is not None
    assert parsed.name_hint == "Karachi Biryani House"


def test_impossible_coordinates_are_dropped_not_clamped() -> None:
    """A mis-parse must stay reportable. Clamped to 90 it would look like a real place."""
    parsed = parse_maps_url("https://www.google.com/maps/place/X/data=!3d999.5!4d67.0")
    assert parsed is not None
    assert parsed.has_coords is False
    assert parsed.coord_source == ""


def test_maps_link_with_no_payload_is_still_a_maps_link() -> None:
    """Not None: 'this names no business' is a better message than 'not a Maps link'."""
    parsed = parse_maps_url("https://www.google.com/maps")
    assert parsed is not None
    assert parsed.has_coords is False
    assert parsed.has_identity is False


def test_negative_coordinates_round_trip() -> None:
    parsed = parse_maps_url(
        "https://www.google.com/maps/place/X/@-33.8688,151.2093,17z/"
        "data=!4m2!3m1!8m2!3d-33.8700!4d151.2100"
    )
    assert parsed is not None
    assert parsed.lat == pytest.approx(-33.87)
    assert parsed.lng == pytest.approx(151.21)
