"""P6B-8: the CONTEXT RETRIEVAL API + FRESHNESS GATE endpoints.

Four routes, two trust levels:

* STAFF (``require_perm("view_reports")`` - held by all six staff roles, never a
  client) read any entity's living context + freshness + top-k chunks
  (``GET /context/{entity_type}/{entity_id}``), a per-entity freshness signal
  (``.../health``), and the org-wide rollup (``GET /context/health``). RLS is still
  the real boundary: the repo is bound to the caller's verified id.
* A PORTAL CLIENT (``CurrentClientDep``) reads ONLY its OWN client-level
  summary+facts (``GET /portal/context``) through the ``portal_context``
  security-barrier view - never another tenant, never the vectors or internals.

The heavy lifting (the freshness policy + namespace-scoped retrieval) lives in
``app.services.context_service``; these handlers just wire the RLS repo + a
cost-gated providers bundle and offload the blocking work with ``to_thread``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentClientDep, require_perm
from app.core.deps import SettingsDep
from app.db.context_repo import ContextRepoDep
from app.schemas.context import (
    ContextHealth,
    ContextView,
    OrgContextHealth,
    PortalContextResponse,
)
from app.services.context_service import (
    UnknownEntityTypeError,
    context_health,
    get_context,
    org_context_health,
    validate_entity_type,
)
from integrations.context_providers import ContextProviders
from workers.tasks.context import gated_providers_for

router = APIRouter(tags=["context"])

# Every staff read is gated on ``view_reports`` (all staff hold it; clients do not,
# so a client is 403'd from the whole /context surface).
_STAFF_READ = Depends(require_perm("view_reports"))

# A factory that builds the (cost-gated) providers bundle for one entity, or None
# (degraded) when keys are absent - injected so tests can swap in the fakes bundle.
ProviderFactory = Callable[[str, str], ContextProviders | None]


def get_context_provider_factory(settings: SettingsDep) -> ProviderFactory:
    """Dependency: a per-entity cost-gated providers factory (or ``None`` degraded).

    Wraps ``gated_providers_for`` so the ``?fresh`` synchronous recompaction and the
    query embedder are metered against the money-dial exactly like the worker.
    Overridable in tests with the deterministic fakes bundle.
    """

    def _factory(entity_type: str, entity_id: str) -> ContextProviders | None:
        return gated_providers_for(settings, entity_type, entity_id)

    return _factory


ProviderFactoryDep = Annotated[ProviderFactory, Depends(get_context_provider_factory)]


def _bad_entity(exc: UnknownEntityTypeError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/context/health", response_model=OrgContextHealth, dependencies=[_STAFF_READ])
async def get_org_context_health(repo: ContextRepoDep) -> OrgContextHealth:
    """The org-wide freshness rollup: worst lag + stale/degraded/error counts."""
    return await asyncio.to_thread(org_context_health, repo=repo)


@router.get(
    "/context/{entity_type}/{entity_id}/health",
    response_model=ContextHealth,
    dependencies=[_STAFF_READ],
)
async def get_entity_context_health(
    entity_type: str, entity_id: str, repo: ContextRepoDep
) -> ContextHealth:
    """One entity's freshness signal (lag / stale / status / version). Read-only."""
    try:
        return await asyncio.to_thread(context_health, entity_type, entity_id, repo=repo)
    except UnknownEntityTypeError as exc:
        raise _bad_entity(exc) from exc


@router.get(
    "/context/{entity_type}/{entity_id}",
    response_model=ContextView,
    dependencies=[_STAFF_READ],
)
async def read_entity_context(
    entity_type: str,
    entity_id: str,
    repo: ContextRepoDep,
    settings: SettingsDep,
    factory: ProviderFactoryDep,
    query: Annotated[str | None, Query(description="Optional retrieval query for top-k chunks")] = None,
    fresh: Annotated[bool, Query(description="Bounded, cost-gated synchronous recompaction if stale")] = False,
) -> ContextView:
    """An entity's CURRENT context + freshness + (for a ``query``) top-k chunks.

    ``fresh=false`` (default) never blocks - serve current, re-arm the worker.
    ``fresh=true`` on a stale context runs a bounded cost-gated sync recompaction;
    if the spend is blocked or providers are absent it still returns 200, stale.
    """
    try:
        validate_entity_type(entity_type)
    except UnknownEntityTypeError as exc:
        raise _bad_entity(exc) from exc

    def _run() -> ContextView:
        providers = factory(entity_type, entity_id)
        return get_context(
            entity_type,
            entity_id,
            query=query,
            fresh=fresh,
            providers=providers,
            repo=repo,
            settings=settings,
        )

    return await asyncio.to_thread(_run)


@router.get("/portal/context", response_model=PortalContextResponse, tags=["portal"])
async def read_portal_context(
    repo: ContextRepoDep, _client: CurrentClientDep
) -> PortalContextResponse:
    """The calling client's OWN client-level summary+facts (security-barrier view).

    ``CurrentClientDep`` 403s any staff caller; the view self-filters to the
    caller's tenant, so a client can never see another client, the vectors, or any
    internal freshness column.
    """
    row = await asyncio.to_thread(repo.read_portal_context)
    return PortalContextResponse.from_row(row)
