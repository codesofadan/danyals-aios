"""Site Analytics module (7C): live Google Search Console + GA4, admin-dashboard
facing. Read-only.

Public surface is the router; the module owns its schemas / repo / router / tasks.
See ``router.py`` for the endpoint map, the tables/migration it owns, and the
access rules.
"""

from __future__ import annotations

from app.modules.site_analytics.router import router

__all__ = ["router"]
