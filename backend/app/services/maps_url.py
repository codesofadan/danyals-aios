"""Read a pasted Google Maps link for what it actually asserts about a business.

WHY THIS EXISTS. ``grid_tracker`` has exactly two centre sources and says so in
``GridDefinitionCreate``: coordinates an operator typed (``center_source='operator'``)
or the Places text-search anchor (``'places'``). Both are lossy in the same way - the
text anchor searches for a NAME and takes the top hit, so a business with a common name
or a nearby namesake can anchor the whole grid on the wrong pin, and nothing on the heat
map looks wrong afterwards. The operator path avoids that only by making a human read
coordinates off a screen and retype them.

A pasted Maps URL removes the guess from both. The operator has *already* found the
business on Google; the link they copied carries the pin's own coordinates and an
identifier for that exact listing. Nothing is searched, so nothing can be mis-matched.

THIS MODULE IS PURE. No network, no DB, no settings - it reads a string and reports
what the string contains. Short links (``maps.app.goo.gl``) carry nothing at all, so
they are REPORTED as needing resolution rather than resolved here; that redirect is a
network call with an SSRF contract and belongs in the service layer.

WHAT A MAPS URL ACTUALLY CARRIES, AND WHICH PART TO BELIEVE
-----------------------------------------------------------
A place URL looks like::

    https://www.google.com/maps/place/Some+Cafe/@24.8607,67.0011,17z/
      data=!4m6!3m5!1s0x3eb33e06651d4bbf:0x82d6e1a4a37b8d1c!8m2!3d24.8612!4d67.0009!16s...

There are TWO coordinate pairs in that string and they are not the same thing:

* ``@lat,lng,zoom`` is the **viewport** - where the camera was when the link was made.
  Pan the map before copying and this moves. It is the business's neighbourhood, not
  the business.
* ``!3d<lat>!4d<lng>`` inside ``data=`` is the **pin** - the coordinate Google holds
  for the listing itself.

The pin wins whenever both are present, and that precedence IS the accuracy gain this
feature was asked for. Taking the viewport would re-introduce, silently, the same
"centre is near the business" error the operator pasted a link to avoid. A grid centred
200m off does not look broken; it just reports the wrong side of the street.

IDENTIFIERS, IN DESCENDING ORDER OF DIRECTNESS
-----------------------------------------------
* ``place_id`` (``ChIJ...``) - the stable Places API key. Arrives via ``?query_place_id=``
  or ``?q=place_id:``. Look it up and there is nothing to disambiguate.
* ``ftid`` (``0xHEX:0xHEX``) - the feature id embedded in ``data=``. Its SECOND half is
  the CID in hex, so a URL with no ``place_id`` still yields a precise listing handle.
* ``cid`` (decimal) - the classic ``?cid=`` form, and what an ftid converts to.

A URL can carry coordinates and no identifier (a dropped pin), or an identifier and no
coordinates (a short ``?cid=`` link). Both are useful and neither is complete, so the
result reports each field independently and the caller decides what it can do with what
came back. Nothing here infers a missing half from the half it has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

__all__ = ["ParsedMapsUrl", "is_maps_url", "parse_maps_url"]

#: Hosts whose links we will read. Checked against the parsed hostname, never with a
#: substring test: ``google.com.evil.tld`` must not pass, and ``"google.com" in host``
#: would wave it through.
_PLACE_HOSTS: frozenset[str] = frozenset({
    "google.com", "www.google.com", "maps.google.com",
    "goo.gl", "maps.app.goo.gl", "g.co",
})

#: The short-link hosts that carry NOTHING in the URL itself - the whole payload is
#: behind a redirect. Reported via ``needs_resolution`` for the service layer to follow.
_SHORT_HOSTS: frozenset[str] = frozenset({"maps.app.goo.gl", "goo.gl", "g.co"})

#: A country TLD (``google.co.uk``, ``google.com.pk``) is the same product. Matched as a
#: whole label sequence so only a real google domain qualifies.
_GOOGLE_CC = re.compile(r"^(?:www\.|maps\.)?google\.[a-z]{2,3}(?:\.[a-z]{2})?$")

#: ``!3d<lat>!4d<lng>`` - the PIN. Kept adjacent in the pattern because the pair is
#: meaningless split: a ``!3d`` from one data block and a ``!4d`` from another would
#: mint a coordinate that exists nowhere.
_PIN_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")

#: ``@lat,lng`` followed by the zoom token - the VIEWPORT. The trailing ``z`` (or a
#: further ``,`` for the 3D camera forms) anchors it so a bare "@" in a business name
#: cannot match.
_VIEWPORT_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),[\d.]+[zmayht]")

#: ``0xHEX:0xHEX`` - the feature id. The second half is the CID in hex.
_FTID_RE = re.compile(r"(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)")

#: A Places ``place_id``. They are base64url-ish and start ``ChIJ`` in overwhelming
#: practice, but other prefixes (``GhIJ``, ``EicR``, ``EhI``) are real, so the prefix is
#: not hard-coded - the surrounding key is what identifies it.
_PLACE_ID_RE = re.compile(r"(?:place_id[:=]|!19s)([A-Za-z0-9_\-]{15,})")

#: The business name slug in ``/maps/place/<name>/``. A display label only - it is the
#: string a human typed or Google slugged, never authoritative NAP.
_PLACE_NAME_RE = re.compile(r"/maps/place/([^/@]+)")


@dataclass(frozen=True)
class ParsedMapsUrl:
    """What one Maps URL asserts. Every field is independently optional.

    ``lat``/``lng`` are the PIN when the URL carried one and the viewport otherwise -
    ``coord_source`` says which, because the difference decides whether the caller
    should trust the centre or go and look the place up properly.
    """

    url: str
    lat: float | None = None
    lng: float | None = None
    #: ``"pin"`` (``!3d/!4d``, authoritative) | ``"viewport"`` (``@``, approximate) | ``""``
    coord_source: str = ""
    place_id: str = ""
    #: Decimal CID, as a string - it exceeds 2^53 routinely, so it never becomes a float.
    cid: str = ""
    ftid: str = ""
    #: The slug from ``/maps/place/<name>/``, URL-decoded. A hint for the operator's
    #: confirmation screen, NEVER written to a NAP field.
    name_hint: str = ""
    #: True for a ``maps.app.goo.gl`` style link: valid, but empty until redirected.
    needs_resolution: bool = False

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None

    @property
    def has_identity(self) -> bool:
        """Whether this URL names a SPECIFIC listing (vs. just a point on the earth)."""
        return bool(self.place_id or self.cid)

    @property
    def is_precise(self) -> bool:
        """Whether the coordinate came from the listing's own pin."""
        return self.coord_source == "pin"


def _is_google_host(host: str) -> bool:
    host = host.lower().strip()
    if host in _PLACE_HOSTS:
        return True
    return bool(_GOOGLE_CC.match(host))


def is_maps_url(value: str) -> bool:
    """Whether ``value`` is a Google Maps link we will attempt to read.

    Deliberately host-based and nothing more. A URL that is a Maps link but carries no
    usable payload is still a Maps link; rejecting it here would report "not a Google
    Maps link" for a link the operator can see is one, which sends them looking for the
    wrong problem.
    """
    try:
        parts = urlparse(value.strip())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return _is_google_host(parts.hostname or "")


def _cid_from_ftid(ftid_second_half: str) -> str:
    """The decimal CID encoded in an ftid's second hex word.

    Returned as a STRING: a CID is a full 64-bit value and routinely exceeds the 2^53
    a float can hold exactly, so any path that touches a float here corrupts the last
    digits of a perfectly good identifier and the lookup then quietly finds nothing.
    """
    try:
        return str(int(ftid_second_half, 16))
    except (ValueError, TypeError):
        return ""


def parse_maps_url(value: str) -> ParsedMapsUrl | None:
    """Read a Google Maps URL. ``None`` when it is not one at all.

    A recognised host with an unreadable body is NOT ``None`` - it comes back as a
    ``ParsedMapsUrl`` with empty fields, so the caller can say "this is a Maps link but
    it names no business" instead of the much less useful "not a Maps link".
    """
    raw = (value or "").strip()
    if not is_maps_url(raw):
        return None

    parts = urlparse(raw)
    host = (parts.hostname or "").lower()
    if host in _SHORT_HOSTS:
        # A short link's path is an opaque token. Saying so is the whole answer here.
        return ParsedMapsUrl(url=raw, needs_resolution=True)

    query = parse_qs(parts.query or "")
    # The fragment is in play because the older `/maps/place/...#...` forms park the
    # data block there; searching the whole string keeps both shapes working.
    whole = raw

    lat: float | None = None
    lng: float | None = None
    coord_source = ""
    pin = _PIN_RE.search(whole)
    if pin:
        lat, lng, coord_source = float(pin.group(1)), float(pin.group(2)), "pin"
    else:
        view = _VIEWPORT_RE.search(whole)
        if view:
            lat, lng, coord_source = float(view.group(1)), float(view.group(2)), "viewport"

    # A coordinate outside the earth is a mis-parse, not a location. Dropping the pair
    # (rather than clamping it) keeps a bad read reportable instead of plausible.
    if lat is not None and lng is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None
        coord_source = ""

    place_id = ""
    for key in ("query_place_id", "placeid", "place_id"):
        found = query.get(key)
        if found and found[0].strip():
            place_id = found[0].strip()
            break
    if not place_id:
        match = _PLACE_ID_RE.search(whole)
        if match:
            place_id = match.group(1)

    cid = ""
    for key in ("cid", "ludocid"):
        found = query.get(key)
        if found and found[0].strip().isdigit():
            cid = found[0].strip()
            break

    ftid = ""
    ftid_match = _FTID_RE.search(whole)
    if ftid_match:
        ftid = f"{ftid_match.group(1)}:{ftid_match.group(2)}"
        if not cid:
            cid = _cid_from_ftid(ftid_match.group(2))

    name_hint = ""
    name_match = _PLACE_NAME_RE.search(parts.path or "")
    if name_match:
        name_hint = unquote(name_match.group(1)).replace("+", " ").strip()

    return ParsedMapsUrl(
        url=raw,
        lat=lat,
        lng=lng,
        coord_source=coord_source,
        place_id=place_id,
        cid=cid,
        ftid=ftid,
        name_hint=name_hint,
    )
