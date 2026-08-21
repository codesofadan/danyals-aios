"""Real, deterministic website-design capture via Playwright: multi-viewport
screenshots + measured DOM/CSS (not a vision-LLM guess from one screenshot).

WHY THIS EXISTS. ``app/services/site_design.py`` extracts a "design profile" by
showing Claude ONE desktop screenshot and asking it to guess colours/fonts/layout
from pixels. That is a real, shipped fallback when nothing better exists, but it is
not measurement: two runs of the same site can yield different hex codes, and it
captures no tablet/mobile behaviour at all. This module instead NAVIGATES the real
page with a real browser at three viewports (desktop/tablet/mobile) and reads the
ACTUAL computed CSS (``getComputedStyle``) off the ACTUAL DOM - the same values the
browser itself used to paint the page - so the extracted typography/colours/layout
are exact, not inferred, and responsive behaviour (section reflow, font scaling) is
observed directly instead of guessed.

Playwright is an OPTIONAL dependency (``pip install -e .[automation]``), exactly
like ``integrations/citation_bot.py`` - lazy-imported so importing this module costs
nothing until a capture actually runs. Uses the SYNC API deliberately: this only
ever runs inside a Celery worker (``app/modules/site_builder/tasks.py``), never the
async FastAPI request path.

SSRF: the caller-supplied URL is validated with ``app.core.security.validate_public_host``
BEFORE any navigation is attempted (never inside the browser-impl class, so the guard
applies uniformly regardless of which :class:`SiteAnalyzer` is wired in, and a unit
test can prove the block without Playwright installed at all). Redirects are handled
by Playwright's own navigation (no manual redirect-following code here to re-validate),
and the DOM/CSS extraction never executes page-authored JS beyond the page's own
normal load - the extractor script we inject is READ-ONLY (no writes, no navigation).

Degrade, never crash: a missing Playwright install, a private/internal host, or a
navigation failure/timeout all return a clean ``status="degraded"`` result with a
machine-branchable ``reason`` - never an unhandled exception bubbling into the worker.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.core.security import PrivateAddressError, validate_public_host
from app.logging_setup import get_logger

logger = get_logger("integrations.site_analyzer")

_INSTALL_HINT = (
    "pip install -e .[automation] (Playwright) THEN `playwright install chromium` "
    "to enable real website design capture"
)

_NAV_TIMEOUT_MS = 30_000
_SETTLE_MS = 350  # a short pause after a viewport resize so CSS transitions/reflow settle

DEGRADE_NO_PLAYWRIGHT = "playwright_unconfigured"
DEGRADE_PRIVATE_HOST = "private_host_blocked"
DEGRADE_CAPTURE_FAILED = "capture_failed"


# --------------------------------------------------------------------------- #
# Viewport plan (desktop / tablet / mobile - the spec's three required breakpoints).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ViewportSpec:
    name: Literal["desktop", "tablet", "mobile"]
    width: int
    height: int


DEFAULT_VIEWPORTS: tuple[ViewportSpec, ...] = (
    ViewportSpec("desktop", 1440, 900),
    ViewportSpec("tablet", 834, 1194),
    ViewportSpec("mobile", 390, 844),
)


# --------------------------------------------------------------------------- #
# The captured shapes (plain, JSON-safe dataclasses - no Playwright types leak out).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TypographySample:
    """The ACTUAL computed style of the first visible instance of one tag."""

    tag: str
    font_family: str = ""
    font_size: str = ""
    font_weight: str = ""
    line_height: str = ""
    color: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "tag": self.tag, "font_family": self.font_family, "font_size": self.font_size,
            "font_weight": self.font_weight, "line_height": self.line_height, "color": self.color,
        }


@dataclass(frozen=True)
class SectionSnapshot:
    """One measured top-level block (header/nav/a main child/footer) at ONE viewport:
    its real bounding-box size + colours + a text sample - the deep structural capture
    a DesignIR blueprint is built from."""

    tag: str
    role: str
    heading: str = ""
    text_sample: str = ""
    bg_color: str = ""
    text_color: str = ""
    width: float = 0.0
    height: float = 0.0
    child_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag, "role": self.role, "heading": self.heading,
            "text_sample": self.text_sample, "bg_color": self.bg_color,
            "text_color": self.text_color, "width": self.width, "height": self.height,
            "child_count": self.child_count,
        }


@dataclass(frozen=True)
class AssetSnapshot:
    url: str
    alt: str = ""
    width: float = 0.0
    height: float = 0.0
    kind: Literal["logo", "image"] = "image"

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "alt": self.alt, "width": self.width, "height": self.height, "kind": self.kind}


@dataclass(frozen=True)
class ViewportCapture:
    """Everything measured at ONE viewport: the full-page screenshot + the
    section/typography/asset snapshot at that breakpoint."""

    viewport: str
    width: int
    height: int
    screenshot_b64: str = ""
    sections: list[SectionSnapshot] = field(default_factory=list)
    typography: list[TypographySample] = field(default_factory=list)
    assets: list[AssetSnapshot] = field(default_factory=list)
    container_width_px: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "viewport": self.viewport, "width": self.width, "height": self.height,
            "screenshot_b64": self.screenshot_b64,
            "sections": [s.as_dict() for s in self.sections],
            "typography": [t.as_dict() for t in self.typography],
            "assets": [a.as_dict() for a in self.assets],
            "container_width_px": self.container_width_px,
        }


@dataclass(frozen=True)
class SiteCapture:
    url: str
    title: str = ""
    viewports: list[ViewportCapture] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "viewports": [v.as_dict() for v in self.viewports]}

    def viewport(self, name: str) -> ViewportCapture | None:
        return next((v for v in self.viewports if v.viewport == name), None)


@dataclass(frozen=True)
class CaptureResult:
    status: Literal["ok", "degraded"]
    capture: SiteCapture | None
    reason: str = ""


# --------------------------------------------------------------------------- #
# The in-page extractor: READ-ONLY (no writes, no navigation) computed-style +
# layout measurement. One evaluate() call per viewport returns everything below.
# --------------------------------------------------------------------------- #
_EXTRACTOR_JS = """
() => {
  function styleOf(el) {
    const cs = window.getComputedStyle(el);
    return {
      fontFamily: cs.fontFamily, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
      lineHeight: cs.lineHeight, color: cs.color, backgroundColor: cs.backgroundColor,
      maxWidth: cs.maxWidth,
    };
  }
  function textSample(el, max) {
    const t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
    return t.slice(0, max || 160);
  }
  function roleOf(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'header' || el.getAttribute('role') === 'banner') return 'header';
    if (tag === 'nav') return 'nav';
    if (tag === 'footer' || el.getAttribute('role') === 'contentinfo') return 'footer';
    if (tag === 'aside') return 'aside';
    return 'section';
  }
  const out = {sections: [], typography: [], assets: [], containerWidthPx: null};

  const typeTags = ['h1', 'h2', 'h3', 'h4', 'p', 'a', 'button'];
  for (const tag of typeTags) {
    const el = document.querySelector(tag);
    if (!el) continue;
    const s = styleOf(el);
    out.typography.push({
      tag, fontFamily: s.fontFamily, fontSize: s.fontSize,
      fontWeight: s.fontWeight, lineHeight: s.lineHeight, color: s.color,
    });
  }

  const top = [];
  const header = document.querySelector('header');
  if (header) top.push(header);
  const nav = document.querySelector('nav');
  if (nav) top.push(nav);
  const main = document.querySelector('main') || document.body;
  const maxWidths = [];
  for (const child of Array.from(main.children)) {
    const tag = child.tagName.toLowerCase();
    if (['script', 'style', 'link', 'noscript', 'header', 'nav', 'footer'].includes(tag)) continue;
    const rect = child.getBoundingClientRect();
    if (rect.height < 40) continue;
    top.push(child);
    const mw = window.getComputedStyle(child).maxWidth;
    if (mw && mw.endsWith('px')) maxWidths.push(parseFloat(mw));
  }
  const footer = document.querySelector('footer');
  if (footer) top.push(footer);

  for (const el of top.slice(0, 24)) {
    const rect = el.getBoundingClientRect();
    const s = styleOf(el);
    const h = el.querySelector('h1, h2, h3');
    out.sections.push({
      tag: el.tagName.toLowerCase(),
      role: roleOf(el),
      heading: h ? textSample(h, 120) : '',
      textSample: textSample(el, 200),
      bgColor: s.backgroundColor,
      textColor: s.color,
      width: rect.width,
      height: rect.height,
      childCount: el.children.length,
    });
  }

  if (maxWidths.length) {
    maxWidths.sort((a, b) => a - b);
    out.containerWidthPx = maxWidths[Math.floor(maxWidths.length / 2)];
  }

  const imgs = Array.from(document.querySelectorAll('img')).slice(0, 30);
  for (const img of imgs) {
    if (!img.src) continue;
    const rect = img.getBoundingClientRect();
    if (rect.width < 16 || rect.height < 16) continue;
    const inChrome = !!img.closest('header, nav');
    out.assets.push({
      url: img.src, alt: img.alt || '', width: rect.width, height: rect.height,
      kind: inChrome ? 'logo' : 'image',
    });
  }

  return out;
}
"""


def _parse_extraction(raw: dict[str, Any]) -> tuple[list[SectionSnapshot], list[TypographySample], list[AssetSnapshot], float | None]:
    """Coerce the JS extractor's return value into typed dataclasses (tolerant of a
    missing/malformed field so a thin page still yields a partially-usable capture)."""
    sections = [
        SectionSnapshot(
            tag=str(s.get("tag") or ""), role=str(s.get("role") or "section"),
            heading=str(s.get("heading") or ""), text_sample=str(s.get("textSample") or ""),
            bg_color=str(s.get("bgColor") or ""), text_color=str(s.get("textColor") or ""),
            width=float(s.get("width") or 0.0), height=float(s.get("height") or 0.0),
            child_count=int(s.get("childCount") or 0),
        )
        for s in (raw.get("sections") or []) if isinstance(s, dict)
    ]
    typography = [
        TypographySample(
            tag=str(t.get("tag") or ""), font_family=str(t.get("fontFamily") or ""),
            font_size=str(t.get("fontSize") or ""), font_weight=str(t.get("fontWeight") or ""),
            line_height=str(t.get("lineHeight") or ""), color=str(t.get("color") or ""),
        )
        for t in (raw.get("typography") or []) if isinstance(t, dict)
    ]
    assets = [
        AssetSnapshot(
            url=str(a.get("url") or ""), alt=str(a.get("alt") or ""),
            width=float(a.get("width") or 0.0), height=float(a.get("height") or 0.0),
            kind="logo" if a.get("kind") == "logo" else "image",
        )
        for a in (raw.get("assets") or []) if isinstance(a, dict) and str(a.get("url") or "").strip()
    ]
    container = raw.get("containerWidthPx")
    container_width = float(container) if isinstance(container, (int, float)) else None
    return sections, typography, assets, container_width


# --------------------------------------------------------------------------- #
# The injectable seam (a Protocol so the DesignIR builder + Celery task unit-test
# against a fake, never a real browser).
# --------------------------------------------------------------------------- #
@runtime_checkable
class SiteAnalyzer(Protocol):
    def capture(self, url: str, *, viewports: tuple[ViewportSpec, ...]) -> CaptureResult: ...


class PlaywrightSiteAnalyzer:
    """Real :class:`SiteAnalyzer` backed by a headless Chromium via Playwright's SYNC
    API. Lazy-imports ``playwright.sync_api`` (optional ``[automation]`` extra) -
    absent the package, ``capture`` degrades cleanly instead of raising ImportError."""

    def capture(self, url: str, *, viewports: tuple[ViewportSpec, ...] = DEFAULT_VIEWPORTS) -> CaptureResult:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("site_analyzer_degraded", reason=DEGRADE_NO_PLAYWRIGHT)
            return CaptureResult(status="degraded", capture=None, reason=DEGRADE_NO_PLAYWRIGHT)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                try:
                    first = viewports[0]
                    context = browser.new_context(viewport={"width": first.width, "height": first.height})
                    page = context.new_page()
                    page.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
                    title = page.title()
                    captures: list[ViewportCapture] = []
                    for vp in viewports:
                        page.set_viewport_size({"width": vp.width, "height": vp.height})
                        page.wait_for_timeout(_SETTLE_MS)
                        raw = page.evaluate(_EXTRACTOR_JS)
                        sections, typography, assets, container_width = _parse_extraction(raw or {})
                        screenshot_bytes = page.screenshot(full_page=True, type="png")
                        captures.append(
                            ViewportCapture(
                                viewport=vp.name, width=vp.width, height=vp.height,
                                screenshot_b64=base64.b64encode(screenshot_bytes).decode("ascii"),
                                sections=sections, typography=typography, assets=assets,
                                container_width_px=container_width,
                            )
                        )
                    return CaptureResult(
                        status="ok",
                        capture=SiteCapture(url=url, title=title, viewports=captures),
                    )
                finally:
                    browser.close()
        except PlaywrightError:
            logger.info("site_analyzer_capture_failed", url=url)
            return CaptureResult(status="degraded", capture=None, reason=DEGRADE_CAPTURE_FAILED)
        except Exception:  # transport/timeout/anything unforeseen: degrade, never crash the worker
            logger.info("site_analyzer_capture_failed", url=url)
            return CaptureResult(status="degraded", capture=None, reason=DEGRADE_CAPTURE_FAILED)


def build_site_analyzer() -> SiteAnalyzer | None:
    """The real analyzer, or ``None`` when Playwright is not importable - mirrors
    every other optional-provider builder in this codebase (key/SDK-gated, never
    raises). The actual ImportError degrade happens inside ``capture`` too (so a
    directly-constructed :class:`PlaywrightSiteAnalyzer` is equally safe); this
    builder additionally avoids constructing the class at all when the SDK is
    absent, so callers that branch on ``is None`` never touch Playwright."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        logger.info("site_analyzer_degraded", reason=DEGRADE_NO_PLAYWRIGHT)
        return None
    return PlaywrightSiteAnalyzer()


# --------------------------------------------------------------------------- #
# The public, pure-of-browser entry point: SSRF-validates FIRST, then delegates.
# --------------------------------------------------------------------------- #
def analyze_website(
    url: str, *, analyzer: SiteAnalyzer | None, viewports: tuple[ViewportSpec, ...] = DEFAULT_VIEWPORTS
) -> CaptureResult:
    """Validate ``url`` is a public host, THEN capture it with ``analyzer``.

    The SSRF check runs here - BEFORE any analyzer is invoked - so the guard applies
    uniformly regardless of which :class:`SiteAnalyzer` is wired in, and this branch
    is testable with no Playwright installed at all. Blocking ``socket.getaddrinfo``:
    callers on an async path must offload this whole function with
    ``asyncio.to_thread`` (it also is not, since this only ever runs inside a Celery
    worker, which is itself synchronous).
    """
    try:
        validate_public_host(url)
    except PrivateAddressError:
        logger.info("site_analyzer_degraded", reason=DEGRADE_PRIVATE_HOST)
        return CaptureResult(status="degraded", capture=None, reason=DEGRADE_PRIVATE_HOST)
    if analyzer is None:
        return CaptureResult(status="degraded", capture=None, reason=DEGRADE_NO_PLAYWRIGHT)
    return analyzer.capture(url, viewports=viewports)
