"""GMB (Google Business Profile) post module (Wave 5): AI-drafted, policy-checked GBP
posts with a human review gate; actual posting to Google is dormant (degrades honestly).

The module's public surface is its ``router``. See ``router.py`` for the table owned
(``gmb_posts``, migration 0053), the cost dial (``gmb``), and the access gates.
"""

from __future__ import annotations

from app.modules.gmb.router import router

__all__ = ["router"]
