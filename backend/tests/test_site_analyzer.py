"""``integrations.site_analyzer``: the SSRF guard runs BEFORE any browser is
touched, a missing analyzer degrades cleanly, and the JS extractor's tolerant
parser survives a malformed/partial payload - all without a real Playwright
install or a real browser.
"""

from __future__ import annotations

import pytest

from integrations.site_analyzer import (
    DEGRADE_NO_PLAYWRIGHT,
    DEGRADE_PRIVATE_HOST,
    CaptureResult,
    SiteCapture,
    ViewportCapture,
    ViewportSpec,
    _parse_extraction,
    analyze_website,
)

pytestmark = pytest.mark.unit


class _FakeAnalyzer:
    """A stand-in :class:`SiteAnalyzer` - no Playwright, no network."""

    def __init__(self, result: CaptureResult) -> None:
        self._result = result
        self.calls: list[str] = []

    def capture(self, url: str, *, viewports: tuple[ViewportSpec, ...]) -> CaptureResult:
        self.calls.append(url)
        return self._result


def _ok_result(url: str) -> CaptureResult:
    return CaptureResult(
        status="ok",
        capture=SiteCapture(
            url=url, title="Example",
            viewports=[ViewportCapture(viewport="desktop", width=1440, height=900)],
        ),
    )


def test_private_host_blocked_before_any_analyzer_call() -> None:
    fake = _FakeAnalyzer(_ok_result("http://127.0.0.1"))
    result = analyze_website("http://127.0.0.1/admin", analyzer=fake)
    assert result.status == "degraded"
    assert result.reason == DEGRADE_PRIVATE_HOST
    assert fake.calls == []  # the analyzer must NEVER be invoked on a private host


def test_metadata_endpoint_blocked() -> None:
    fake = _FakeAnalyzer(_ok_result("http://169.254.169.254"))
    result = analyze_website("http://169.254.169.254/latest/meta-data", analyzer=fake)
    assert result.status == "degraded"
    assert result.reason == DEGRADE_PRIVATE_HOST
    assert fake.calls == []


def test_no_analyzer_degrades_cleanly() -> None:
    result = analyze_website("https://example.com", analyzer=None)
    assert result.status == "degraded"
    assert result.reason == DEGRADE_NO_PLAYWRIGHT


def test_public_host_delegates_to_the_injected_analyzer() -> None:
    fake = _FakeAnalyzer(_ok_result("https://example.com"))
    result = analyze_website("https://example.com/pricing", analyzer=fake)
    assert result.status == "ok"
    assert result.capture is not None
    assert result.capture.title == "Example"
    assert fake.calls == ["https://example.com/pricing"]


def test_capture_viewport_lookup() -> None:
    capture = SiteCapture(
        url="https://example.com",
        viewports=[
            ViewportCapture(viewport="desktop", width=1440, height=900),
            ViewportCapture(viewport="mobile", width=390, height=844),
        ],
    )
    assert capture.viewport("mobile") is not None
    assert capture.viewport("mobile").width == 390  # type: ignore[union-attr]
    assert capture.viewport("tablet") is None


def test_parse_extraction_tolerates_a_malformed_payload() -> None:
    """A missing/garbage field never crashes the parser - it just yields an empty
    or default-filled record, exactly like every other tolerant parser in this
    codebase (``site_design.build_profile``)."""
    sections, typography, assets, container = _parse_extraction({})
    assert sections == []
    assert typography == []
    assert assets == []
    assert container is None

    sections, typography, assets, container = _parse_extraction(
        {
            "sections": [{"tag": "div", "role": "section", "heading": "Welcome"}, "not-a-dict"],
            "typography": [{"tag": "h1", "fontFamily": "Sora"}, 42],
            "assets": [{"url": "https://example.com/logo.png", "kind": "logo"}, {"url": ""}],
            "containerWidthPx": 1200,
        }
    )
    assert len(sections) == 1
    assert sections[0].heading == "Welcome"
    assert len(typography) == 1
    assert typography[0].font_family == "Sora"
    assert len(assets) == 1  # the blank-url asset is dropped
    assert assets[0].kind == "logo"
    assert container == 1200.0


def test_capture_result_as_dict_round_trips_shape() -> None:
    vp = ViewportCapture(viewport="desktop", width=1440, height=900, screenshot_b64="Zm9v")
    capture = SiteCapture(url="https://example.com", title="Example", viewports=[vp])
    d = capture.as_dict()
    assert d["url"] == "https://example.com"
    assert d["viewports"][0]["viewport"] == "desktop"
    assert d["viewports"][0]["screenshot_b64"] == "Zm9v"
