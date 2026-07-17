"""Competitor-intel module (Part 8 Phase 2C): the competitive set + keyword gaps.

Public surface is the router; the module owns its schemas / repo / service / tasks /
provider seam. See ``router.py`` for the endpoint map + the tables/migration it owns.
"""

from __future__ import annotations

from app.modules.competitor_intel.router import router

__all__ = ["router"]
