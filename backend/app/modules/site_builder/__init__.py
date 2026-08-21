"""Site Builder module: the website-reconstruction pipeline's persisted, versioned
DesignIR + the one end-to-end site-generation job (migration 0069).

Phase 1+2 of the "website reconstruction" build: a real (Playwright-measured, not
vision-guessed) website analyzer feeds a platform-independent :class:`DesignIR`,
tracked through :class:`SiteGenerationJob`'s single state machine (queued ->
analyzing -> generating -> uploading_assets -> rendering -> validating ->
correcting -> publishing -> completed/failed) - the one progress bar the future
website-builder wizard polls. Later phases add the renderer(s) + visual QA that
advance a job through the remaining states; this phase implements analyze only
(``generating``.. onward are reachable states not yet driven by any task).

No ``frontend/lib/*.ts`` type mirrors this module (new surface) - shapes are
SERVER-AUTHORITATIVE and owned by ``schemas.py``.
"""

from __future__ import annotations

from app.modules.site_builder.router import router

__all__ = ["router"]
