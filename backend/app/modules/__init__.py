"""Feature modules -- one self-contained package per business feature.

This is the professional module-per-feature layout (Part 8, plan section 3). Each
package under ``app/modules/<name>/`` owns its own ``router`` + ``schemas`` +
``repo`` + ``service`` + ``tasks`` -- everything you need to read a feature as a
unit lives in one directory, instead of being scattered across ``routers/``,
``services/``, ``schemas/`` and ``db/``.

The public surface of a module is its ``router``. Register a module by appending
its router to ``MODULE_ROUTERS`` below; ``app/routers/__init__.py`` includes every
entry into the ``api_v1`` aggregator, so a new module needs exactly one line here
(plus one line in ``workers/celery_app.py`` if it owns Celery tasks).

The shared kernel (``app/core``, ``app/db/database.py``, ``app/rbac``) is imported
by modules, never re-implemented -- see ``README.md`` for the house style.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.keyword_research import router as keyword_research_router

# Every module's public router, in include order. ``app/routers/__init__.py``
# includes each entry into the ``api_v1`` aggregator, so a new module needs exactly
# one line here (plus one in ``workers/celery_app.py`` if it owns Celery tasks).
MODULE_ROUTERS: list[APIRouter] = [
    keyword_research_router,
]
