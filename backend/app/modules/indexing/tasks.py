"""Indexing worker: fire URL submissions to the search engines off the request path.

``submit_urls_for_indexing`` is enqueued best-effort after a successful content publish
(see ``workers/tasks/content.py``) and by any future scheduled sweep. It wires the
privileged append store + the key-gated seams + a short-lived ``httpx.AsyncClient`` and
runs the SAME ``app.modules.indexing.service.submit_urls`` fan-out the endpoint uses.

NO COST DIAL: IndexNow + the Google Indexing API are FREE, so this module declares no
``_FEATURE`` and never touches the cost gate (``test_dial_registration`` skips it).

Never re-raises: with ``task_acks_late`` a raised exception would redeliver the job and
re-submit; the seams are already non-raising, and the outer guard swallows even a
store/settings construction failure so a redelivery never double-fires.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings
from app.logging_setup import get_logger
from app.modules.indexing.repo import service_indexing_store
from app.modules.indexing.service import submit_urls
from integrations.google_indexing import google_indexing_from_settings
from integrations.indexnow import indexnow_from_settings

logger = get_logger("workers.indexing")

_HTTP_TIMEOUT = 30.0


async def _run(urls: list[str], engines: list[str] | None, client_id: str | None) -> dict[str, Any]:
    settings = get_settings()
    store = service_indexing_store()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as http:
        summary = await submit_urls(
            store,
            http=http,
            indexnow=indexnow_from_settings(settings),
            google=google_indexing_from_settings(settings),
            settings=settings,
            urls=urls,
            engines=engines,
            client_id=client_id,
        )
    return {"submitted": len(summary.rows), "ok": summary.ok, "skipped": summary.skipped, "errors": summary.errors}


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app after the pure core, per the template).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="submit_urls_for_indexing")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def submit_urls_for_indexing(
    urls: list[str], engines: list[str] | None = None, client_id: str | None = None
) -> dict[str, Any]:
    """Fan a set of URLs out to the search engines + record every attempt. Never
    re-raises (``task_acks_late`` would otherwise redeliver + re-submit)."""
    try:
        return asyncio.run(_run(urls, engines, client_id))
    except Exception:
        logger.exception("submit_urls_for_indexing_failed", url_count=len(urls))
        return {"submitted": 0, "ok": 0, "skipped": 0, "errors": 0, "state": "error"}
