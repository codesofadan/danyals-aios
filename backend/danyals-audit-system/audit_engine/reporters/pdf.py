"""PDF reporter.

Renders the HTML reports to PDF. Three backends, tried in priority order:
  1. System Chrome / Edge headless `--print-to-pdf`. No extra download,
     works out of the box on any Windows / macOS with a Chromium browser
     installed. This is the default backend.
  2. Playwright + bundled Chromium. Use when the system browser is
     unavailable and `playwright install chromium` has been run.
  3. WeasyPrint. CSS-paged-media compliant but needs GTK on Windows.

All three graceful-degrade: if no backend works, audit pipeline still emits
HTML + Markdown + JSON deliverables.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from audit_engine.logging_setup import get_logger

log = get_logger(__name__)


_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def _find_system_chrome() -> str | None:
    env_override = os.environ.get("SEO_AUDIT_CHROME")
    if env_override and Path(env_override).is_file():
        return env_override
    for c in _CHROME_CANDIDATES:
        if Path(c).is_file():
            return c
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _system_chrome_pdf(html_path: Path, pdf_path: Path) -> bool:
    chrome = _find_system_chrome()
    if chrome is None:
        log.info("system_chrome_not_found")
        return False
    # Big reports (3,000+ findings -> ~400 KB HTML) need more than 60s to render.
    # Override via SEO_AUDIT_PDF_TIMEOUT_SEC if you have an even larger deliverable.
    import os
    timeout_sec = int(os.getenv("SEO_AUDIT_PDF_TIMEOUT_SEC", "300"))
    cmd = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            log.info("pdf_written_chrome", path=str(pdf_path), bytes=pdf_path.stat().st_size)
            return True
        log.warning(
            "system_chrome_pdf_empty",
            html=str(html_path),
            stderr=result.stderr[:300],
        )
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("system_chrome_pdf_failed", html=str(html_path), error=f"{type(e).__name__}: {e}")
        return False


def _playwright_pdf_sync(html_path: Path, pdf_path: Path) -> bool:
    """Inner worker: runs Playwright's sync API. Must NOT be called from an
    asyncio event loop directly — Playwright's sync_playwright() detects a
    running loop and raises. Use `_playwright_pdf()` instead, which dispatches
    to a worker thread when needed.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # noqa: BLE001
        log.info("playwright_unavailable", error=type(e).__name__)
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.emulate_media(media="print")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "right": "16mm", "bottom": "20mm", "left": "16mm"},
                prefer_css_page_size=True,
            )
            browser.close()
        log.info("pdf_written_playwright", path=str(pdf_path))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("playwright_pdf_failed", html=str(html_path), error=f"{type(e).__name__}: {e}")
        return False


def _playwright_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Render HTML to PDF via Playwright. Detects whether we're inside an
    asyncio event loop; if so, runs the sync Playwright API in a worker
    thread so it doesn't trip Playwright's loop-collision guard.
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
        in_async = True
    except RuntimeError:
        in_async = False

    if not in_async:
        return _playwright_pdf_sync(html_path, pdf_path)

    # We're inside an asyncio loop (e.g. called from `_run_full`). Push to a
    # thread so Playwright sees a "clean" interpreter with no loop running.
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_playwright_pdf_sync, html_path, pdf_path)
            return future.result(timeout=300)
    except Exception as e:  # noqa: BLE001
        log.warning("playwright_pdf_thread_failed", error=f"{type(e).__name__}: {e}")
        return False


def _weasyprint_pdf(html_path: Path, pdf_path: Path) -> bool:
    try:
        from weasyprint import HTML  # type: ignore
    except Exception as e:  # noqa: BLE001
        log.info("weasyprint_unavailable", error=type(e).__name__)
        return False
    try:
        HTML(filename=str(html_path), base_url=str(html_path.parent)).write_pdf(str(pdf_path))
        log.info("pdf_written_weasyprint", path=str(pdf_path))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("weasyprint_pdf_failed", html=str(html_path), error=f"{type(e).__name__}: {e}")
        return False


def html_to_pdf(html_path: Path, *, pdf_path: Path | None = None) -> Path | None:
    """Convert an HTML file to PDF. Returns the PDF path or None on failure.

    Tries system Chrome/Edge, then bundled Chromium via Playwright, then WeasyPrint.
    """
    out = pdf_path or html_path.with_suffix(".pdf")
    if _system_chrome_pdf(html_path, out):
        return out
    if _playwright_pdf(html_path, out):
        return out
    if _weasyprint_pdf(html_path, out):
        return out
    return None


def write_all_pdfs(html_paths: dict[str, Path]) -> dict[str, Path]:
    """Convert each HTML report to its PDF counterpart. Skips failures
    silently; returns only the PDFs that succeeded.
    """
    out: dict[str, Path] = {}
    for key, html_path in html_paths.items():
        if not key.endswith("_html"):
            continue
        pdf = html_to_pdf(html_path)
        if pdf is not None:
            out[key.replace("_html", "_pdf")] = pdf
    return out
