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
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings

_PDF_NAME = "report.pdf"
_JSON_NAME = "findings.json"
# Role-based remediation sheets (xlsx + csvs) live in this subdir of the run's
# artifact dir. They are derived from findings.json by ``audit_sheets`` and
# resolved by convention from the audit id (no DB column) - see ``resolve_sheet``.
_SHEETS_SUBDIR = "sheets"
# The self-contained HTML report the dashboard viewer renders. It is a sibling of
# report.pdf under ``<root>/<audit_id>/`` and is resolved by convention from the
# audit id (no DB column) - see ``resolve_report_html``.
REPORT_HTML_NAME = "report.html"
#: The CONSULTING report this platform builds, under <root>/<audit_id>/sheets/.
#: Kept as a literal rather than imported from audit_report: that module imports
#: REPORT_PDF_NAME from HERE, so importing it back would close a cycle.
_BUILT_REPORT_NAME = "audit-report.html"
#: The platform's own client report, written into `<audit_id>/sheets/` by the
#: ingest step. Defined here rather than in `audit_report` because this module is
#: the lower layer: the store must be able to find the file without importing the
#: builder that writes it.
REPORT_PDF_NAME = "audit-report.pdf"

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
        """Resolve the report HTML for a run, richest document first, or ``None``.

        TWO documents can exist for one run and they are not equivalent:

        * ``sheets/audit-report.html`` - the CONSULTING report this platform builds
          (``audit_report.render``): scored dimensions, the ranked findings body,
          the phased plan, the page table.
        * ``report.html`` - what the ENGINE emitted, a sibling of report.pdf.

        The consulting document is preferred wherever it exists, and this ordering
        is load-bearing rather than cosmetic. Serving the engine file is what made
        the free public page look empty: on a ``--mode free`` run the engine's own
        HTML is heavily condensed (1 table / 7 rows against a paid run's 7 / 54),
        so a visitor saw headings with nothing under them and concluded the audit
        had found nothing - while that run's ``findings.json`` held the same ~176
        findings a paid run produces. Preferring the built report also makes the
        free and paid pages ONE document instead of two that drift.

        Falls back to the engine file so a run from before the consulting report
        existed - or one whose render failed - still serves something. Resolved
        from the audit id alone (no DB column) and traversal-safe via ``resolve``.
        """
        built = self.resolve(f"{audit_id}/{_SHEETS_SUBDIR}/{_BUILT_REPORT_NAME}")
        if built is not None:
            return built
        return self.resolve(f"{audit_id}/{REPORT_HTML_NAME}")

    def sheets_dir(self, audit_id: str) -> Path:
        """The (created) directory holding a run's remediation sheets.

        ``<root>/<audit_id>/sheets/`` - the sheet builder writes the xlsx + csvs
        here; downloads resolve them by convention via :meth:`resolve_sheet`.
        """
        dest = self._root / audit_id / _SHEETS_SUBDIR
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    def resolve_sheet(self, audit_id: str, name: str) -> Path | None:
        """Resolve a named remediation sheet for a run, or ``None``.

        Resolved from the audit id + file name alone (no DB column), the same way
        report.html is. Traversal-safe via :meth:`resolve` - the caller must also
        restrict ``name`` to the known sheet allow-list before serving it.
        """
        return self.resolve(f"{audit_id}/{_SHEETS_SUBDIR}/{name}")


def local_store_from_settings(settings: Settings) -> LocalArtifactStore | None:
    """Build the local artifact store, or ``None`` when unconfigured."""
    root = settings.audit_artifact_dir
    return LocalArtifactStore(root) if root else None


def honest_artifact_flags(
    store: LocalArtifactStore | None, row: Mapping[str, Any]
) -> tuple[bool, bool]:
    """Return ``(pdf_available, json_available)`` for an audit row - the truth the UI
    can trust to decide whether to show a download button.

    The row's ``pdf_path`` / ``json_path`` columns record the keys the worker set
    when it COPIED the artifacts. Those columns can outlive the file on disk (an
    artifact volume that was not carried across a redeploy, a copy the worker never
    actually made because the store write failed). Serving a download from a stale
    column then 404s - exactly the "button appears but the file is not on the
    server" bug. So when an artifact store IS configured we DOWNGRADE each flag to
    on-disk reality: resolve the key and require the file to exist. When NO store is
    configured we cannot check, so we trust the columns (prior behavior; keeps the
    flags meaningful in a store-less deploy and in unit tests).

    NOTE: ``resolve`` does filesystem ``stat`` calls; callers on an async route must
    invoke this via ``asyncio.to_thread`` so the event loop is never blocked.
    """
    pdf_present = bool(row.get("pdf_path"))
    json_present = bool(row.get("json_path"))
    if store is None:
        return pdf_present, json_present
    pdf_ok = pdf_present and store.resolve(str(row.get("pdf_path") or "")) is not None
    json_ok = json_present and store.resolve(str(row.get("json_path") or "")) is not None
    if not pdf_ok:
        # The platform's own report is written by the ingest step, not the engine,
        # so it has no column of its own and a run whose engine PDF backend was
        # unavailable still has a PDF to serve. The flag has to know that or the
        # button stays hidden over a file that exists.
        audit_id = str(row.get("id") or "")
        pdf_ok = bool(audit_id) and store.resolve_sheet(audit_id, REPORT_PDF_NAME) is not None
    return pdf_ok, json_ok
