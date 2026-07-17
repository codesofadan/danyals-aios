"""Rank-tracker module (Part 8 Phase 2B): the tracked-keyword board + nightly checks.

Public surface is the router; the module owns its schemas / repo / service / tasks /
provider seam. See ``router.py`` for the endpoint map + the tables/migration it owns.
"""

from __future__ import annotations

from app.modules.rank_tracker.router import router

__all__ = ["router"]
