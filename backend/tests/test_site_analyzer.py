"""``integrations.site_analyzer``: the SSRF guard runs BEFORE any browser is
touched, a missing analyzer degrades cleanly, and the JS extractor's tolerant
parser survives a malformed/partial payload - all without a real Playwright
install or a real browser.
"""

from __future__ import annotations

from typing import Any

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


def test_bare_domain_is_normalized_to_https_before_the_analyzer_sees_it() -> None:
    """A schemeless input ("example.com") passes validate_public_host fine (it only
    checks the HOST), but Playwright's page.goto needs a fully-qualified URL or it
    fails almost instantly against about:blank's origin - this is the exact bug that
    produced 'analysis_failed:capture_failed' on a real bare-domain wizard input."""
    fake = _FakeAnalyzer(_ok_result("https://example.com"))
    result = analyze_website("example.com", analyzer=fake)
    assert result.status == "ok"
    assert fake.calls == ["https://example.com"]


def test_already_schemed_url_is_untouched() -> None:
    fake = _FakeAnalyzer(_ok_result("http://example.com"))
    result = analyze_website("http://example.com/pricing", analyzer=fake)
    assert result.status == "ok"
    assert fake.calls == ["http://example.com/pricing"]


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

class TestAMissingBrowserIsNotAFailedPage:
    """`pip install .[automation]` without `playwright install chromium` is the common
    half-done deploy, and it used to report every capture as "that site would not load" -
    sending the operator to look at the CLIENT'S website for a problem on ours."""

    def test_the_missing_binary_gets_its_own_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from integrations.site_analyzer import (
            DEGRADE_NO_BROWSER,
            PlaywrightSiteAnalyzer,
        )

        class _FakeLaunchError(Exception):
            pass

        def _boom(*_a: Any, **_k: Any) -> Any:
            raise _FakeLaunchError(
                "BrowserType.launch: Executable doesn't exist at "
                "/ms-playwright/chromium-1091/chrome-linux/chrome. "
                "Looks like Playwright was just installed or updated. "
                "Please run the following command to download new browsers: "
                "playwright install"
            )

        import sys
        import types

        fake = types.ModuleType("playwright.sync_api")
        fake.Error = _FakeLaunchError  # type: ignore[attr-defined]
        fake.sync_playwright = _boom  # type: ignore[attr-defined]
        pkg = types.ModuleType("playwright")
        monkeypatch.setitem(sys.modules, "playwright", pkg)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)

        out = PlaywrightSiteAnalyzer().capture("https://example.com")
        assert out.status == "degraded"
        assert out.reason == DEGRADE_NO_BROWSER

    def test_a_real_page_failure_still_reads_as_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from integrations.site_analyzer import (
            DEGRADE_CAPTURE_FAILED,
            PlaywrightSiteAnalyzer,
        )

        class _FakeLaunchError(Exception):
            pass

        def _boom(*_a: Any, **_k: Any) -> Any:
            raise _FakeLaunchError("page.goto: net::ERR_NAME_NOT_RESOLVED at https://example.com")

        import sys
        import types

        fake = types.ModuleType("playwright.sync_api")
        fake.Error = _FakeLaunchError  # type: ignore[attr-defined]
        fake.sync_playwright = _boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)

        out = PlaywrightSiteAnalyzer().capture("https://example.com")
        assert out.reason == DEGRADE_CAPTURE_FAILED
