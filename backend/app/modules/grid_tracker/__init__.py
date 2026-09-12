"""Grid tracker (0138): local-search GRID tracking - map-pack position across a
service area, not at a single representative point.

The module's public surface is its ``router`` (the house module contract). See
``router.py`` for the access gates, ``provider.py`` for why a coordinate-capable
vendor is mandatory, and ``service.py`` for the one rule the numbers rest on: every
ratio divides by MEASURED points.
"""

from __future__ import annotations

from app.modules.grid_tracker.router import router

__all__ = ["router"]
