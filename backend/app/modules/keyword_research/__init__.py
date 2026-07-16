"""Keyword-research module (Part 8 Phase 2A): the staff-only keyword bank tool.

Public surface is the router; the module owns its schemas / repo / service / tasks /
provider seam. See ``router.py`` for the endpoint map + the tables/migration it owns.
"""

from __future__ import annotations

from app.modules.keyword_research.router import router

__all__ = ["router"]
