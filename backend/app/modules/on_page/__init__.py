"""On-page optimizer module (Part 8 Phase 2D): review + APPLY on-page fixes.

Public surface is the router; the module owns its schemas / repo / service / tasks.
See ``router.py`` for the endpoint map + the tables/migration it owns, and ``tasks.py``
for the apply path's drift-guard + write-verify contract (it mutates a LIVE site).
"""

from __future__ import annotations

from app.modules.on_page.router import router

__all__ = ["router"]
