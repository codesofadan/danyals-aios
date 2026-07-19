"""Site Analytics endpoints (7C): live Google Search Console + GA4, admin-dashboard
facing.

No ``frontend/lib/*.ts`` type mirrors this module yet - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape tests).

Tables owned: ``gsc_properties`` / ``ga4_properties`` (migration ``0047_site_analytics``).
Cost-gate dial: ``site_analytics`` (free-tier; logged for spend-visibility parity with
every other module, mirrors ``cwv``).

SCOPE: read-only. There is no write-back to Search Console or GA4 anywhere in this
module - it only ever reads a trailing-28-day snapshot.

Access: creating/listing/syncing a property requires ``require_role(owner, admin,
manager)`` - the LEADS - mirroring ``local_seo``'s gate (``view_reports`` for plain
reads). CONNECTING a property (minting the OAuth consent URL, sealing the resulting
refresh token into the vault) additionally requires ``manage_vault`` (owner/admin
only) - it is squarely an integration-credential action, the same permission that
gates the Key Vault itself.

THE ONE UNAUTHENTICATED ROUTE - ``GET /site-analytics/oauth/callback``: Google's
redirect back to us is a plain BROWSER NAVIGATION, which (per ``lib/api.ts``'s
"Bearer auth only - we NEVER send cookies" design) carries no Authorization header
at all. So this route cannot be gated the normal way; instead the one-time ``state``
token minted by the ``/connect`` endpoint (below) IS the capability - exactly the
``report_token`` pattern ``app/routers/public.py`` already uses for the anonymous
free-audit report. ``state`` is single-use (deleted from Redis on first read) and
short-lived (10 minutes), so a stolen/replayed callback URL is worthless after the
first hit or after the window closes.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import RedisDep, SettingsDep
from app.logging_setup import get_logger
from app.modules.site_analytics.repo import (
    ServiceSiteAnalyticsStore,
    SiteAnalyticsRepoDep,
    service_site_analytics_store,
)
from app.modules.site_analytics.schemas import (
    ConnectGoogleResponse,
    Ga4PropertyCreate,
    Ga4PropertyResponse,
    GscPropertyCreate,
    GscPropertyResponse,
    RefreshQueuedResponse,
)
from app.services.activity import record_activity
from integrations.google_oauth import authorize_url, exchange_code

router = APIRouter(tags=["site-analytics"])
logger = get_logger("routers.site_analytics")

# Reads add view_reports (all 6 staff roles); every mutation requires a LEAD
# (owner/admin/manager), mirroring local_seo's gate exactly. CONNECT additionally
# requires manage_vault (owner/admin only - see the module docstring).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]
ManageVault = Annotated[CurrentUser, Depends(require_perm("manage_vault"))]

_GSC_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="GSC property not found")
_GA4_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="GA4 property not found")
_CLIENT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Client not found")

_STATE_TTL_SECONDS = 600  # 10 minutes - plenty to complete Google's consent screen
_STATE_PREFIX = "site_analytics:oauth_state:"


def _state_key(state: str) -> str:
    return f"{_STATE_PREFIX}{state}"


def get_gsc_sync_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the read-only GSC sync (overridable in tests)."""

    def _enqueue(property_id: str) -> None:
        from app.modules.site_analytics.tasks import sync_gsc_property

        sync_gsc_property.delay(property_id)

    return _enqueue


def get_ga4_sync_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the read-only GA4 sync (overridable in tests)."""

    def _enqueue(property_id: str) -> None:
        from app.modules.site_analytics.tasks import sync_ga4_property

        sync_ga4_property.delay(property_id)

    return _enqueue


GscSyncEnqueuerDep = Annotated[Callable[[str], None], Depends(get_gsc_sync_enqueuer)]
Ga4SyncEnqueuerDep = Annotated[Callable[[str], None], Depends(get_ga4_sync_enqueuer)]


# --- GSC --------------------------------------------------------------------


@router.get("/site-analytics/gsc/properties", response_model=list[GscPropertyResponse])
async def list_gsc_properties(
    repo: SiteAnalyticsRepoDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[GscPropertyResponse]:
    rows = await asyncio.to_thread(repo.list_gsc, client_id=client_id)
    return [GscPropertyResponse.from_row(r) for r in rows]


@router.post(
    "/site-analytics/gsc/properties",
    response_model=GscPropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gsc_property(
    body: GscPropertyCreate, repo: SiteAnalyticsRepoDep, actor: Lead
) -> GscPropertyResponse:
    """Register a Search Console site for a client (not yet connected)."""
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND
    row = await asyncio.to_thread(
        repo.add_gsc, client_id=body.client_id, client_name=client_name, site_url=body.site_url
    )
    await record_activity(
        actor, kind="client", action=f"added a GSC property ({body.site_url})",
        target=client_name, entity_type="client", entity_id=body.client_id,
    )
    return GscPropertyResponse.from_row(row)


@router.get("/site-analytics/gsc/properties/{property_id}/connect", response_model=ConnectGoogleResponse)
async def connect_gsc_property(
    property_id: str, repo: SiteAnalyticsRepoDep, redis: RedisDep, settings: SettingsDep, actor: ManageVault
) -> ConnectGoogleResponse:
    """Mint a Google consent-screen URL for this property, or an honest HOLD if no
    OAuth client is configured yet."""
    row = await asyncio.to_thread(repo.get_gsc, property_id)
    if row is None:
        raise _GSC_NOT_FOUND
    return await _connect(redis, settings, actor, property_type="gsc", property_id=property_id)


@router.post(
    "/site-analytics/gsc/properties/{property_id}/sync",
    response_model=RefreshQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_gsc_property_route(
    property_id: str, repo: SiteAnalyticsRepoDep, settings: SettingsDep, actor: Lead,
    enqueue: GscSyncEnqueuerDep,
) -> RefreshQueuedResponse:
    """Queue a READ-ONLY GSC sync. Returns 202 with ``held=true`` when no Google
    OAuth client is configured - mirrors ``local_seo``'s GBP sync pre-check."""
    row = await asyncio.to_thread(repo.get_gsc, property_id)
    if row is None:
        raise _GSC_NOT_FOUND
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        return RefreshQueuedResponse(id=property_id, queued=False, held=True, reason="no_oauth_client")
    enqueue(property_id)
    await record_activity(
        actor, kind="client", action="synced a GSC property",
        target=str(row.get("client_name", "") or ""), entity_type="client", entity_id=str(row["client_id"]),
    )
    return RefreshQueuedResponse(id=property_id, queued=True)


# --- GA4 --------------------------------------------------------------------


@router.get("/site-analytics/ga4/properties", response_model=list[Ga4PropertyResponse])
async def list_ga4_properties(
    repo: SiteAnalyticsRepoDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Ga4PropertyResponse]:
    rows = await asyncio.to_thread(repo.list_ga4, client_id=client_id)
    return [Ga4PropertyResponse.from_row(r) for r in rows]


@router.post(
    "/site-analytics/ga4/properties",
    response_model=Ga4PropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ga4_property(
    body: Ga4PropertyCreate, repo: SiteAnalyticsRepoDep, actor: Lead
) -> Ga4PropertyResponse:
    """Register a GA4 property for a client (not yet connected)."""
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND
    row = await asyncio.to_thread(
        repo.add_ga4, client_id=body.client_id, client_name=client_name, property_id=body.property_id
    )
    await record_activity(
        actor, kind="client", action=f"added a GA4 property ({body.property_id})",
        target=client_name, entity_type="client", entity_id=body.client_id,
    )
    return Ga4PropertyResponse.from_row(row)


@router.get("/site-analytics/ga4/properties/{property_id}/connect", response_model=ConnectGoogleResponse)
async def connect_ga4_property(
    property_id: str, repo: SiteAnalyticsRepoDep, redis: RedisDep, settings: SettingsDep, actor: ManageVault
) -> ConnectGoogleResponse:
    row = await asyncio.to_thread(repo.get_ga4, property_id)
    if row is None:
        raise _GA4_NOT_FOUND
    return await _connect(redis, settings, actor, property_type="ga4", property_id=property_id)


@router.post(
    "/site-analytics/ga4/properties/{property_id}/sync",
    response_model=RefreshQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_ga4_property_route(
    property_id: str, repo: SiteAnalyticsRepoDep, settings: SettingsDep, actor: Lead,
    enqueue: Ga4SyncEnqueuerDep,
) -> RefreshQueuedResponse:
    row = await asyncio.to_thread(repo.get_ga4, property_id)
    if row is None:
        raise _GA4_NOT_FOUND
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        return RefreshQueuedResponse(id=property_id, queued=False, held=True, reason="no_oauth_client")
    enqueue(property_id)
    await record_activity(
        actor, kind="client", action="synced a GA4 property",
        target=str(row.get("client_name", "") or ""), entity_type="client", entity_id=str(row["client_id"]),
    )
    return RefreshQueuedResponse(id=property_id, queued=True)


# --- shared connect + the ONE unauthenticated route --------------------------


async def _connect(
    redis: RedisDep, settings: SettingsDep, actor: CurrentUser, *, property_type: str, property_id: str
) -> ConnectGoogleResponse:
    """Mint a single-use ``state`` token + the Google consent URL, or HOLD when no
    OAuth client is configured yet."""
    if not (settings.google_oauth_client_id and settings.google_oauth_redirect_uri):
        return ConnectGoogleResponse(authorize_url=None, held=True, reason="no_oauth_client")
    state = secrets.token_urlsafe(32)
    payload = json.dumps({"property_type": property_type, "property_id": property_id, "actor_id": actor.id})
    await redis.set(_state_key(state), payload.encode(), ex=_STATE_TTL_SECONDS)
    return ConnectGoogleResponse(authorize_url=authorize_url(settings, state=state), held=False)


@router.get("/site-analytics/oauth/callback", include_in_schema=False)
async def oauth_callback(
    redis: RedisDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google's redirect back to us - UNAUTHENTICATED by necessity (see the module
    docstring). The ``state`` token is the capability: single-use, 10-minute TTL,
    minted only by an already-authenticated ``manage_vault`` holder's ``/connect``
    call. Always ends in a redirect to the frontend settings page with a
    ``googleConnect`` query flag the UI can toast."""
    return_to = settings.google_oauth_return_path
    if error or not (code and state):
        return RedirectResponse(f"{return_to}?googleConnect=error")

    raw = await redis.get(_state_key(state))
    if raw is None:
        return RedirectResponse(f"{return_to}?googleConnect=expired")
    await redis.delete(_state_key(state))  # single-use, even on a later failure

    try:
        payload = json.loads(raw)
        property_type = str(payload["property_type"])
        property_id = str(payload["property_id"])
        tokens = exchange_code(settings, code=code)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            # Google omits refresh_token on a re-consent it doesn't consider fresh;
            # authorize_url always sets prompt=consent precisely to avoid this, but
            # a stale grant can still land here - fail loud rather than silently
            # storing an access-only token that expires in an hour.
            logger.error("google_oauth_no_refresh_token", property_type=property_type)
            return RedirectResponse(f"{return_to}?googleConnect=error")

        from app.services.vault import add_key

        key_row = await asyncio.to_thread(
            add_key,
            provider="google",
            label=f"{property_type}:{property_id}",
            secret=str(refresh_token),
            created_by=str(payload.get("actor_id", "")),
            kind="client_access",
        )
        store: ServiceSiteAnalyticsStore = service_site_analytics_store()
        if property_type == "gsc":
            await asyncio.to_thread(store.connect_gsc, property_id, oauth_vault_ref=str(key_row["id"]))
        else:
            await asyncio.to_thread(store.connect_ga4, property_id, oauth_vault_ref=str(key_row["id"]))
        logger.info("google_oauth_connected", property_type=property_type, property_id=property_id)
    except Exception:
        logger.exception("google_oauth_callback_failed")
        return RedirectResponse(f"{return_to}?googleConnect=error")

    return RedirectResponse(f"{return_to}?googleConnect=success")
