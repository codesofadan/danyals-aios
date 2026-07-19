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

from app.modules.billing import router as billing_router
from app.modules.citations import router as citations_router
from app.modules.client_onboarding import router as client_onboarding_router
from app.modules.competitor_intel import router as competitor_intel_router
from app.modules.data_import import router as data_import_router
from app.modules.keyword_research import router as keyword_research_router
from app.modules.local_seo import router as local_seo_router
from app.modules.on_page import router as on_page_router
from app.modules.rank_tracker import router as rank_tracker_router
from app.modules.site_analytics import router as site_analytics_router
from app.modules.tool_workspaces import router as tool_workspaces_router

# Every module's public router, in include order. ``app/routers/__init__.py``
# includes each entry into the ``api_v1`` aggregator, so a new module needs exactly
# one line here (plus one in ``workers/celery_app.py`` if it owns Celery tasks).
MODULE_ROUTERS: list[APIRouter] = [
    keyword_research_router,
    client_onboarding_router,
    billing_router,
    local_seo_router,
    on_page_router,
    rank_tracker_router,
    competitor_intel_router,
    # Read-only /workspace adapters for the nine tools whose modules predate Part 8;
    # owns no tables and no tasks (see app/modules/tool_workspaces/router.py).
    tool_workspaces_router,
    data_import_router,
    # 7B-4: citation SUBMISSION (business profiles + directory catalog + campaign
    # dispatch) - the write half of off-page; app/routers/offpage.py keeps the
    # read/monitoring half.
    citations_router,
    # 7C: live Google Search Console + GA4 (read-only), admin-dashboard facing.
    site_analytics_router,
]
