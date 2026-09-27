"""The capture path that broke every design analysis of a tall page.

THE DEFECT (measured 2026-09-25). `screenshot@fullPage` renders a page top-to-bottom, and
Anthropic's Messages API REFUSES an image whose either dimension exceeds 8000 px with
`400 invalid_request_error: At least one of the image dimensions exceed max allowed size`.
It does not downscale for you. The seam's only guard was a 4 MB BYTE cap, which this shape
sails through: the capture of https://app.smarthealth.ae was 1.3 MB at 1920x9595. So the
vision call 400'd, `extract_site_design` reported `analysis_failed`, and the whole capture
degraded with nothing saved.

HOW COMMON IT IS, from a 45-URL sweep across 10 page kinds: roughly half the real pages
tested exceeded the limit - 8506, 8741, 9595, 10799, 11428, 15165, 18774 and 22210 px
among them. This was not an edge case, it was the normal case for a modern marketing site.

The fix is two-part and both parts are pinned here: DETECT the oversize (from the PNG
header, no imaging dependency) and RETRY with the viewport format so vision is retained
rather than silently dropped to text-only.

A SECOND defect the sweep surfaced: a 429 was treated as fatal, so 36 of 45 captures
degraded on rate limiting. A bulk capture - an agency onboarding a client - would have
produced text-only profiles for most of the batch and reported nothing wrong.
"""

from __future__ import annotations

import base64
import struct
import zlib
from typing import Any

import pytest

from integrations.firecrawl import (
    _MAX_SCREENSHOT_EDGE,
    _RATE_LIMIT_ATTEMPTS,
    FirecrawlPage,
    _bounded_b64,
    _retry_after_seconds,
    firecrawl_scrape,
    png_dimensions,
    screenshot_is_oversized,
)

pytestmark = pytest.mark.unit


def png(width: int, height: int) -> bytes:
    """A minimal valid PNG: signature + IHDR. Enough for a header dimension read."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = (
        struct.pack(">I", len(ihdr))
        + b"IHDR"
        + ihdr
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    )
    return b"\x89PNG\r\n\x1a\n" + chunk


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------------- #
# Reading the dimensions.
# --------------------------------------------------------------------------- #
def test_dimensions_come_from_the_png_header() -> None:
    assert png_dimensions(png(1920, 9595)) == (1920, 9595)
    assert png_dimensions(png(800, 600)) == (800, 600)


@pytest.mark.parametrize(
    "raw", [b"", b"not a png", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\nshort"],
)
def test_an_unreadable_header_is_unknown_not_a_guess(raw: bytes) -> None:
    """None means "dimensions unknown", and the caller lets it through: the byte cap and
    the API itself are still behind it, so an odd header must not drop a usable shot."""
    assert png_dimensions(raw) is None
    assert screenshot_is_oversized(raw) is False


# --------------------------------------------------------------------------- #
# The guard.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "height", [8506, 8741, 9595, 10799, 11428, 15165, 18774, 22210],
)
def test_the_real_heights_measured_in_the_sweep_are_all_refused(height: int) -> None:
    """Every one of these is an actual full-page capture height from the 45-URL sweep.
    Each would have 400'd the vision call."""
    assert screenshot_is_oversized(png(1920, height)) is True


def test_a_wide_image_is_refused_too() -> None:
    """The limit is per-DIMENSION, not height-only."""
    assert screenshot_is_oversized(png(9000, 400)) is True


def test_exactly_at_the_limit_is_allowed() -> None:
    """8000 is the documented maximum, not the first refused value - an off-by-one here
    would throw away usable captures."""
    assert screenshot_is_oversized(png(_MAX_SCREENSHOT_EDGE, _MAX_SCREENSHOT_EDGE)) is False


def test_an_ordinary_viewport_shot_passes() -> None:
    assert screenshot_is_oversized(png(1920, 1080)) is False


def test_the_bounded_decoder_drops_an_oversize_shot() -> None:
    """THE defect at its narrowest: 1.3 MB is inside the byte cap, 9595 px is not inside
    the dimension limit, and only one of those was being checked."""
    tall = png(1920, 9595)
    assert len(tall) < 4_000_000, "precondition: inside the byte cap"
    assert _bounded_b64(b64(tall)) is None
    assert _bounded_b64(b64(png(1920, 1080))) is not None


# --------------------------------------------------------------------------- #
# The retry that keeps vision.
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code: int, payload: Any, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class _RecordingClient:
    """An httpx-shaped double that returns a scripted response per call."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.formats_seen: list[list[str]] = []
        self.calls = 0

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls += 1
        self.formats_seen.append(list((kwargs.get("json") or {}).get("formats") or []))
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:  # pragma: no cover
        raise AssertionError("the inline data-URI path should not fetch")


def _scrape_payload(shot_png: bytes, markdown: str = "# Page") -> dict[str, Any]:
    """A Firecrawl v1 result carrying an inline data-URI screenshot."""
    return {"data": {"markdown": markdown,
                     "screenshot": f"data:image/png;base64,{b64(shot_png)}"}}


async def _run(client: _RecordingClient) -> FirecrawlPage | None:
    return await firecrawl_scrape(
        client,  # type: ignore[arg-type]
        api_key="k", base_url="https://api.firecrawl.dev",
        url="https://example.com/very/long/page", want_screenshot=True,
    )


async def test_a_tall_full_page_falls_back_to_the_viewport_and_keeps_vision() -> None:
    """THE fix. Without it the capture returns markdown and NO screenshot, and the design
    analysis silently loses vision on most real sites."""
    client = _RecordingClient([
        _FakeResponse(200, _scrape_payload(png(1920, 18774), "# full")),   # oversize
        _FakeResponse(200, _scrape_payload(png(1920, 1080), "# viewport")),  # usable
    ])
    page = await _run(client)
    assert page is not None
    assert page.screenshot_b64 is not None, "vision was lost"
    assert client.calls == 2, "the viewport retry did not happen"
    assert client.formats_seen[0] == ["markdown", "screenshot@fullPage"]
    assert client.formats_seen[1] == ["markdown", "screenshot"], "retry used the wrong format"


async def test_the_retry_keeps_the_full_page_markdown() -> None:
    """The viewport shot is clipped, but the MARKDOWN from the full-page pass covers the
    whole document - so section order is still read from everything, not just above the
    fold."""
    client = _RecordingClient([
        _FakeResponse(200, _scrape_payload(png(1920, 18774), "# the whole document")),
        _FakeResponse(200, _scrape_payload(png(1920, 1080), "# only the fold")),
    ])
    page = await _run(client)
    assert page is not None
    assert page.markdown == "# the whole document"


async def test_a_normal_page_makes_exactly_one_call() -> None:
    """The retry must cost nothing on the pages that never needed it."""
    client = _RecordingClient([_FakeResponse(200, _scrape_payload(png(1920, 1080)))])
    page = await _run(client)
    assert page is not None and page.screenshot_b64 is not None
    assert client.calls == 1


async def test_vision_is_dropped_honestly_when_even_the_viewport_is_unusable() -> None:
    """The markdown still comes back - a partial success - rather than the whole capture
    failing. That is the pre-existing contract and it must survive the fix."""
    client = _RecordingClient([
        _FakeResponse(200, _scrape_payload(png(1920, 18774))),
        _FakeResponse(200, _scrape_payload(png(9000, 9000))),  # still refused
    ])
    page = await _run(client)
    assert page is not None
    assert page.screenshot_b64 is None
    assert page.markdown


# --------------------------------------------------------------------------- #
# Rate limiting.
# --------------------------------------------------------------------------- #
async def test_a_429_is_retried_rather_than_treated_as_fatal() -> None:
    """A bulk capture hits the provider's rate limit routinely; a 429 used to fall into
    the generic non-200 branch and degrade the capture to text-only."""
    client = _RecordingClient([
        _FakeResponse(429, {}, {"retry-after": "0"}),
        _FakeResponse(200, _scrape_payload(png(1920, 1080))),
    ])
    page = await _run(client)
    assert page is not None and page.screenshot_b64 is not None
    assert client.calls == 2


async def test_a_persistent_429_degrades_rather_than_raising() -> None:
    """Bounded: the seam's contract is that it never raises, so exhausting the attempts
    returns None and the caller falls back."""
    client = _RecordingClient([_FakeResponse(429, {}, {"retry-after": "0"})])
    assert await _run(client) is None
    assert client.calls == _RATE_LIMIT_ATTEMPTS


def test_retry_after_is_read_only_when_it_is_a_usable_number() -> None:
    """Mis-parsing an HTTP-date into a multi-hour sleep inside a request an operator is
    waiting on would be worse than falling back to the local backoff."""
    assert _retry_after_seconds(_FakeResponse(429, {}, {"retry-after": "3"})) == 3.0
    assert _retry_after_seconds(_FakeResponse(429, {}, {"retry-after": "0"})) is None
    assert _retry_after_seconds(_FakeResponse(429, {}, {"retry-after": "-5"})) is None
    assert _retry_after_seconds(
        _FakeResponse(429, {}, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    ) is None
    assert _retry_after_seconds(_FakeResponse(429, {}, {})) is None


async def test_a_non_429_error_still_degrades_immediately() -> None:
    """Only rate limiting is transient here. A 401/404 must not be retried."""
    client = _RecordingClient([_FakeResponse(401, {})])
    assert await _run(client) is None
    assert client.calls == 1
