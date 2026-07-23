"""Audit artifact storage: move a run's report PDF + findings.json out of the
engine's working tree into a controlled root the API can serve.

The worker copies the two files into ``<root>/<audit_id>/`` and records the
returned relative keys on the row (which drive the frontend pdf/json flags). The
download endpoint resolves a key back to a path, refusing anything that escapes
the root (path-traversal guard). ``LocalArtifactStore`` targets the single-VPS
deploy where the API + worker share a filesystem; the ``ArtifactStore`` seam
lets a Supabase-Storage/signed-URL backend slot in later without touching either
caller.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from app.config import Settings

_PDF_NAME = "report.pdf"
_JSON_NAME = "findings.json"
# The self-contained HTML report the dashboard viewer renders. It is a sibling of
# report.pdf under ``<root>/<audit_id>/`` and is resolved by convention from the
# audit id (no DB column) - see ``resolve_report_html``.
REPORT_HTML_NAME = "report.html"

# Response headers for serving report.html. It is a static, self-contained document
# (inline CSS, no scripts) the dashboard fetches into a sandboxed srcdoc viewer.
# These harden the case where it is opened directly on the API origin: no
# scripts/frames/network, only inline styles + data: images/fonts. Shared by the
# staff, portal, and public serving routes so the policy lives in one place.
REPORT_HTML_VIEW_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"
    ),
    "X-Content-Type-Options": "nosniff",
}


class ArtifactStore(Protocol):
    """Persist a run's artifacts; return ``(pdf_key, json_key)`` (None if absent).

    ``html_src`` (the self-contained report.html) is copied alongside the PDF but
    is resolved by convention at serve time, so its key is not part of the return.
    """

    def store(
        self,
        audit_id: str,
        *,
        pdf_src: str | None,
        findings_src: str | None,
        html_src: str | None = None,
    ) -> tuple[str | None, str | None]: ...


class LocalArtifactStore:
    """Copies artifacts into ``<root>/<audit_id>/`` on a shared filesystem."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def store(
        self,
        audit_id: str,
        *,
        pdf_src: str | None,
        findings_src: str | None,
        html_src: str | None = None,
    ) -> tuple[str | None, str | None]:
        dest_dir = self._root / audit_id
        # report.html is copied best-effort (it drives the viewer) but its key is
        # not returned: routes resolve it by convention via ``resolve_report_html``.
        self._copy(html_src, dest_dir, REPORT_HTML_NAME, audit_id)
        return (
            self._copy(pdf_src, dest_dir, _PDF_NAME, audit_id),
            self._copy(findings_src, dest_dir, _JSON_NAME, audit_id),
        )

    def _copy(self, src: str | None, dest_dir: Path, name: str, audit_id: str) -> str | None:
        if not src:
            return None
        srcp = Path(src)
        if not srcp.is_file():
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(srcp, dest_dir / name)
        return f"{audit_id}/{name}"

    def resolve(self, key: str) -> Path | None:
        """Resolve a stored key to a real file within the root, or ``None``.

        Refuses any key that escapes the root (``..`` / absolute), so a crafted
        key can never read an arbitrary file.
        """
        if not key:
            return None
        root = self._root.resolve()
        target = (self._root / key).resolve()
        if not target.is_relative_to(root):
            return None
        return target if target.is_file() else None

    def resolve_report_html(self, audit_id: str) -> Path | None:
        """Resolve the self-contained report.html for a run, or ``None``.

        report.html is written as a sibling of report.pdf under
        ``<root>/<audit_id>/``, so it is resolved from the audit id alone - no DB
        column, and independent of whether a PDF was produced (an engine with no
        PDF backend still emits the HTML). Traversal-safe via ``resolve``.
        """
        return self.resolve(f"{audit_id}/{REPORT_HTML_NAME}")


def local_store_from_settings(settings: Settings) -> LocalArtifactStore | None:
    """Build the local artifact store, or ``None`` when unconfigured."""
    root = settings.audit_artifact_dir
    return LocalArtifactStore(root) if root else None
