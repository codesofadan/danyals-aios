"""HTML to PDF, through a headless browser.

WHY A BROWSER AND NOT A PDF LIBRARY. The document is already a stylesheet with
`@page` rules, `page-break-before`, and inline SVG charts. A browser is the only
renderer that agrees with what the operator sees on screen, so the PDF a client
receives and the page a reviewer approved are the same document. A second engine
would be a second layout to keep in sync, and the first divergence would ship
without anyone noticing.

WHAT IT WILL NOT DO. It will not fail an audit. Chrome is not present in every
environment this runs in, and a missing browser has to degrade to "no PDF this
run" rather than losing the workbook, the CSVs and the HTML that were already
written. Every failure path returns None and logs; none of them raise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app.logging_setup import get_logger

logger = get_logger("app.report_pdf")

#: Where a browser usually lives. Ordered: a real Chrome first, then the
#: Chromium a container is more likely to have, then Edge.
_CANDIDATES: tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
_ON_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")

#: A report is a few dozen pages of static HTML with no network access. Anything
#: past this is a hung browser, not a slow render.
_TIMEOUT_SEC = 120


#: Env vars that name a browser, in order. `SEO_AUDIT_CHROME` is already set in
#: the backend image and points at a wrapper that prepends --disable-dev-shm-usage
#: (without it headless chromium crashes on the container's small /dev/shm), so
#: honouring it reuses a configuration that is already correct rather than
#: rediscovering the bare binary beside it.
_ENV_KEYS = ("AIOS_CHROME", "SEO_AUDIT_CHROME")


def find_browser() -> str | None:
    for key in _ENV_KEYS:
        override = os.environ.get(key)
        if override and Path(override).is_file():
            return override
    for path in _CANDIDATES:
        if Path(path).is_file():
            return path
    for name in _ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    return None


def render(html_path: str | Path, pdf_path: str | Path) -> Path | None:
    """Render one HTML file to PDF. Returns the path, or None if it could not."""
    src, out = Path(html_path), Path(pdf_path)
    if not src.is_file():
        logger.warning("report_pdf_source_missing", path=str(src))
        return None
    browser = find_browser()
    if browser is None:
        logger.info("report_pdf_skipped_no_browser", path=str(out))
        return None

    # NO `--user-data-dir`. Measured on Chrome 1xx/macOS: passing one - even an
    # empty temp dir, even with --no-first-run --no-default-browser-check - makes
    # headless --print-to-pdf hang until killed, while the default profile renders
    # this document in ~3s. The engine's own PDF reporter passes no profile either.
    cmd = [
        browser,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-pdf-header-footer",
        f"--print-to-pdf={out}",
        src.resolve().as_uri(),
    ]
    try:
        # Fixed argv, no shell: nothing here is interpolated from user input.
        proc = subprocess.run(
            cmd, capture_output=True, timeout=_TIMEOUT_SEC, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("report_pdf_render_failed",
                       error=f"{type(exc).__name__}: {exc}", path=str(out))
        return None

    # Chrome exits 0 having written nothing often enough that the exit code alone
    # is not evidence. The file is.
    if not out.is_file() or out.stat().st_size == 0:
        logger.warning("report_pdf_not_written", returncode=proc.returncode,
                       stderr=proc.stderr[-400:].decode("utf-8", "replace"), path=str(out))
        return None
    logger.info("report_pdf_written", path=str(out), bytes=out.stat().st_size)
    return out
