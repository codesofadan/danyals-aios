"""Local-SEO module (Part 8 Phase 2E): map-pack rank tracking + GBP profiles + NAP.

The module's public surface is its ``router`` (the house module contract). See
``router.py`` for the tables owned, the migration, the cost dial and the access gates.
"""

from __future__ import annotations

from app.modules.local_seo.router import router

__all__ = ["router"]
