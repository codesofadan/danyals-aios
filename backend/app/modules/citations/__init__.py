"""Citation-builder module (7B-4): business profiles, the directory catalog, and
citation SUBMISSION (as opposed to ``app/routers/offpage.py``, which only monitors
whether a listing already exists). See ``router.py`` for the endpoint surface and
``tasks.py`` for the worker."""

from __future__ import annotations

from app.modules.citations.router import router

__all__ = ["router"]
