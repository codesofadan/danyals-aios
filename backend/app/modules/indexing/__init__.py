"""Indexing module - submit published/on-demand URLs to search engines.

Three key-gated, degrade-safe mechanisms fan out from one service:
IndexNow, the Google Indexing API, and a best-effort sitemap ping. Every attempt is
appended to the ``index_submissions`` ledger (``0061``). The module's public surface is
its ``router`` (registered in ``app/modules/__init__.py``); its Celery task
``submit_urls_for_indexing`` fires best-effort after a successful content publish.
"""

from __future__ import annotations

from app.modules.indexing.router import router

__all__ = ["router"]
