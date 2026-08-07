"""Indexing endpoints - submit URLs to search engines + read the submission ledger.

No ``frontend/lib/*.ts`` type mirrors this module; the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape tests).

Table owned: ``index_submissions`` (migration ``0061_indexing``).

Access: submitting is a publish-adjacent action, so ``POST /indexing/submit`` requires
``publish_content`` (the same permission that pushes content past the review gate);
reading the ledger requires ``view_reports`` (all 6 staff roles). Clients are excluded
by the 0061 ``is_staff()`` select policy.

The fan-out runs SYNCHRONOUSLY on the request over the shared ``httpx.AsyncClient`` (the
seams are async + non-raising); each engine key-gated + degrade-safe. IndexNow + Google
Indexing are FREE, so there is NO cost dial here (nothing metered).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentUser, require_perm
from app.core.deps import HttpClientDep, SettingsDep
from app.core.pagination import PageDep
from app.modules.indexing.repo import IndexingRepoDep, ServiceIndexingStore, service_indexing_store
from app.modules.indexing.schemas import (
    SubmissionResponse,
    SubmitRequest,
    SubmitResponse,
)
from app.modules.indexing.service import submit_urls
from app.services.activity import record_activity
from integrations.google_indexing import google_indexing_from_settings
from integrations.indexnow import indexnow_from_settings

router = APIRouter(tags=["indexing"])

# Submitting pushes a page to the engines (publish-adjacent) -> publish_content; reading
# the ledger -> view_reports (every staff role).
Publisher = Annotated[CurrentUser, Depends(require_perm("publish_content"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]


def get_indexing_store() -> ServiceIndexingStore:
    """Dependency: the privileged append store (overridable in tests)."""
    return service_indexing_store()


IndexingStoreDep = Annotated[ServiceIndexingStore, Depends(get_indexing_store)]


@router.post("/indexing/submit", response_model=SubmitResponse)
async def submit_for_indexing(
    body: SubmitRequest,
    store: IndexingStoreDep,
    http: HttpClientDep,
    settings: SettingsDep,
    actor: Publisher,
) -> SubmitResponse:
    """Fan a set of URLs out to the chosen engines (default: all three) and record the
    outcome per attempt. Each engine degrades independently when unconfigured (records
    a ``skipped`` row), so this endpoint never fails on a missing key."""
    summary = await submit_urls(
        store,
        http=http,
        indexnow=indexnow_from_settings(settings),
        google=google_indexing_from_settings(settings),
        settings=settings,
        urls=body.urls,
        engines=[str(e) for e in body.engines] if body.engines is not None else None,
        client_id=body.client_id,
    )
    await record_activity(
        actor,
        kind="content",
        action=f"submitted {len(body.urls)} URL(s) for indexing",
        target="",
        entity_type="client" if body.client_id else None,
        entity_id=body.client_id,
    )
    return SubmitResponse(
        submitted=len(summary.rows),
        ok=summary.ok,
        skipped=summary.skipped,
        errors=summary.errors,
        results=[SubmissionResponse.from_row(r) for r in summary.rows],
    )


@router.get("/indexing/submissions", response_model=list[SubmissionResponse])
async def list_submissions(
    repo: IndexingRepoDep,
    _user: ViewReports,
    page: PageDep,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[SubmissionResponse]:
    """The indexing history, newest-first (staff-only). Optionally filtered by client."""
    rows = await asyncio.to_thread(repo.list_submissions, client_id=client_id, limit=page.limit)
    return [SubmissionResponse.from_row(r) for r in rows]
