"""Client-onboarding module (Part 8 Phase 2F): the staff-only activation checklist.

Public surface is the router; the module owns its constants (the versioned 11-step
template) / schemas / repo / service. It owns no Celery task - onboarding is driven
by humans, not a worker. See ``router.py`` for the endpoint map + the tables/migration
it owns.
"""

from __future__ import annotations

from app.modules.client_onboarding.router import router

__all__ = ["router"]
