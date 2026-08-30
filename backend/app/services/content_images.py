"""Content-image hosting: give a generated PNG a real, served ``https`` URL.

The image provider (``gpt-image-2``, and ``gpt-image-1`` before it) returns the
image as base64 (``b64_json``), NEVER a hosted url (unlike dall-e-3). The draft
pipeline needs a URL it can embed
as ``![alt](url)`` markdown that then flows into the stored ``draft_md``, the
Elementor tree, AND the published WordPress body - and inlining a multi-MB base64
``data:`` URI into every draft would bloat the draft / DB / WordPress payload.

So the decoded PNG bytes are HOSTED here: written under a controlled root
(``content_image_dir``, defaulting under the shared artifact root, mirroring
``citation_artifact_dir`` / ``content_artifact_dir``) with a CONTENT-HASH filename
(``sha256(bytes).png`` -> dedup + cache-friendly), and served read-only by the
public ``GET /api/v1/public/content-images/{name}`` route (an image embedded in a
published page is fetched by a browser with NO bearer token, so it MUST be
unauthenticated). :meth:`resolve` is the traversal-safe reverse that route uses -
the same guard as ``LocalArtifactStore`` / ``LocalContentArtifactStore``.

This mirrors the audit/content artifact stores; the ``OpenAIImageGenerator`` in
``integrations.images`` is handed one of these as its injected image host (its
``host_png`` seam), keeping ``integrations`` free of any app-layer import.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import Settings

# The read-only PUBLIC route the served content images hang off. It lives on the
# public funnel router (``app/routers/public.py`` prefix ``/public``, mounted under
# ``/api/v1``), so it is UNAUTHENTICATED by design: a published WordPress page loads
# these ``<img>`` URLs with no bearer token. Keep this in lock-step with that route.
CONTENT_IMAGE_ROUTE = "/api/v1/public/content-images"


def _trim_overlap(base_url: str, route: str) -> str:
    """Drop any leading part of ``route`` that ``base_url`` already ends with.

    ``PUBLIC_FILE_BASE_URL`` is documented as an ORIGIN (``https://api.example.com``),
    but ``/api/v1`` is the most natural thing in the world to paste onto the end of an
    API base - and the route below ALREADY carries it. Concatenating blindly then mints
    ``https://host/api/v1/api/v1/public/content-images/<sha>.png``, which 404s.

    That failure is invisible where it happens. The bytes are hosted correctly, the
    stage reports success, the cost is real, the draft passes QA - and the broken URL
    is only discovered as a missing image on the client's published page, by the
    client. MEASURED on this deploy: every generated page carried the doubled path.

    So an overlap is trimmed rather than trusted. It is not silent about it either:
    a wrong-but-plausible base still round-trips to a working URL, and the operator
    keeps the value they meant.
    """
    if not base_url or not route:
        return base_url
    segments = [s for s in route.strip("/").split("/") if s]
    # Longest overlap first: "/api/v1" must win over "/api".
    for depth in range(len(segments), 0, -1):
        suffix = "/" + "/".join(segments[:depth])
        if base_url.endswith(suffix):
            return base_url[: -len(suffix)]
    return base_url


class LocalContentImageStore:
    """Host a generated PNG under a controlled root and mint its served URL.

    ``host_png`` writes the decoded bytes to ``<root>/<sha256>.png`` (identical bytes
    reuse the same file -> dedup) and returns the URL the draft markdown embeds:
    ``<base_url><route>/<sha256>.png``. ``base_url`` blank yields a relative URL
    (``/api/v1/public/content-images/...`` - same-origin dashboard preview works; set
    ``PUBLIC_FILE_BASE_URL`` in prod so a WordPress-embedded image resolves).
    """

    def __init__(
        self, root: str | Path, *, base_url: str = "", route: str = CONTENT_IMAGE_ROUTE
    ) -> None:
        self._root = Path(root)
        self._route = "/" + route.strip("/")
        self._base_url = _trim_overlap(base_url.rstrip("/"), self._route)

    def host_png(self, data: bytes) -> str:
        """Persist ``data`` (PNG bytes) and return its served URL. Raises on empty
        bytes (a caught, degrade-safe error for the generator - never a broken image)."""
        if not data:
            raise ValueError("cannot host empty image bytes")
        self._root.mkdir(parents=True, exist_ok=True)
        name = f"{hashlib.sha256(data).hexdigest()}.png"
        target = self._root / name
        if not target.exists():  # content-hash name => identical bytes, identical file
            target.write_bytes(data)
        return f"{self._base_url}{self._route}/{name}"

    def resolve(self, name: str) -> Path | None:
        """Resolve a served filename to a real file within the root, or ``None``.

        Refuses any name that escapes the root (``..`` / absolute / separators), so a
        crafted name can never read an arbitrary file (mirrors ``LocalArtifactStore``).
        """
        if not name:
            return None
        root = self._root.resolve()
        target = (self._root / name).resolve()
        if not target.is_relative_to(root):
            return None
        return target if target.is_file() else None


def content_image_dir(settings: Settings) -> str | None:
    """The content-image hosting root, or ``None`` when NO artifact root is configured.

    Prefers ``content_image_dir``; else nests under the shared ``content_artifact_dir``
    (or ``audit_artifact_dir``) so a single-root deploy needs to set only one path.
    """
    if settings.content_image_dir:
        return settings.content_image_dir
    base = settings.content_artifact_dir or settings.audit_artifact_dir
    return str(Path(base) / "content-images") if base else None


def content_image_store_from_settings(settings: Settings) -> LocalContentImageStore | None:
    """Build the content-image store, or ``None`` when no hosting root is configured
    (the b64 image path then degrades to skipped, never a crash)."""
    root = content_image_dir(settings)
    if not root:
        return None
    return LocalContentImageStore(root, base_url=settings.public_file_base_url)
