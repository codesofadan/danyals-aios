"""Serving a citation's proof screenshot, without ever handing out a path.

`citations.proof_url` holds a RELATIVE KEY (`ab12cd34.png`). It used to hold the absolute
server path the Playwright bot returned - which meant a column named `*_url` carried
`/var/lib/aios/citations/...`, so anything that rendered it produced a dead link and
anything that serialised the row leaked the server's directory layout.

A key needs a reader, and this is it: resolve the key inside a fixed root, refuse anything
that escapes, and serve the bytes. The path is never returned to the caller - the same
discipline `app/services/audit_artifacts.py` applies to audit reports, reused here rather
than re-derived.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings


class CitationEvidenceStore:
    """Traversal-safe reader for the citation proof-screenshot root."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def resolve(self, key: str) -> Path | None:
        """Resolve a stored key to a real file inside the root, or ``None``.

        Refuses any key that escapes the root (`..`, an absolute path, a symlink out),
        so a crafted `proof_url` can never read an arbitrary file off the server. The
        check is done on the RESOLVED paths, because `..` only becomes visible after
        normalisation."""
        if not key:
            return None
        root = self._root.resolve()
        target = (self._root / key).resolve()
        if not target.is_relative_to(root):
            return None
        return target if target.is_file() else None


def citation_evidence_store(settings: Settings) -> CitationEvidenceStore | None:
    """Build the store, or ``None`` when no artifact root is configured.

    Unconfigured is a legitimate state - the bot then captures no screenshot and
    `proof_url` stays honestly empty - so this degrades rather than raising."""
    root = settings.citation_artifact_dir
    return CitationEvidenceStore(root) if root else None
