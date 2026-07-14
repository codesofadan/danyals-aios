"""Supabase client seams + an async readiness ping.

Two client factories with very different trust levels:

* ``get_admin_client`` builds the SERVICE-ROLE client. The service_role key
  BYPASSES Row-Level Security - it can read and write every row of every tenant.
  It is SERVER-ONLY: never return this client (or its key) to a browser, never
  log the key, never ship it in a frontend bundle. Cached as a process-wide
  singleton because it is stateless and identical for every server-side call.

* ``client_for_user`` builds an RLS-RESPECTING client for one end user, using the
  ANON key plus that user's JWT. It MUST use the anon key: a service_role JWT
  would ignore the user's role and silently bypass RLS. It MUST be per-request
  and is deliberately NOT cached - caching would leak one user's authorization to
  the next request.
"""

from __future__ import annotations

from functools import lru_cache

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.config import get_settings
from app.schemas.health import DependencyStatus

_DEPENDENCY_NAME = "supabase"


class SupabaseNotConfiguredError(RuntimeError):
    """Raised when a Supabase client is requested but its config is missing."""


@lru_cache
def get_admin_client() -> Client:
    """Return the process-wide service-role Supabase client (bypasses RLS).

    SERVER-ONLY. Never return this client or its key to a client; never log it.

    Raises ``SupabaseNotConfigured`` when the URL or service_role key is absent.
    Because the error path raises (rather than returning ``None``), ``lru_cache``
    never caches a mis-configured result - once config is fixed the next call
    builds the real client.
    """
    settings = get_settings()
    url = settings.supabase_url
    key = settings.supabase_service_role_key
    if not url or not key:
        raise SupabaseNotConfiguredError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for the admin client"
        )
    options = SyncClientOptions(persist_session=False, auto_refresh_token=False)
    return create_client(url, key.get_secret_value(), options)


def client_for_user(jwt: str) -> Client:
    """Return a per-request, RLS-respecting client scoped to one user's JWT.

    Uses the ANON key (never service_role) so Postgres RLS evaluates the user's
    role. NEVER cache this: it is bound to a single JWT and must not be shared
    across requests or users.
    """
    settings = get_settings()
    url = settings.supabase_url
    anon = settings.supabase_anon_key
    if not url or not anon:
        raise SupabaseNotConfiguredError(
            "SUPABASE_URL and SUPABASE_ANON_KEY are required for a user client"
        )
    options = SyncClientOptions(
        headers={"Authorization": f"Bearer {jwt}"},
        persist_session=False,
        auto_refresh_token=False,
    )
    return create_client(url, anon.get_secret_value(), options)


async def ping(client: httpx.AsyncClient, url: str | None, timeout: float) -> DependencyStatus:
    """Readiness ping for Supabase. Never raises; returns a sanitized status.

    ``/auth/v1/health`` proves the API gateway + auth service are reachable only,
    NOT that Postgres/PostgREST is healthy; upgrade to a PostgREST touch in Part 2.
    """
    if not url:
        return DependencyStatus(name=_DEPENDENCY_NAME, status="not_configured")
    # Supabase gates /auth/v1/health behind the anon apikey; without it the gateway
    # returns 401 and readiness would falsely report Supabase as down.
    headers: dict[str, str] = {}
    anon = get_settings().supabase_anon_key
    if anon:
        headers["apikey"] = anon.get_secret_value()
    try:
        resp = await client.get(f"{url}/auth/v1/health", headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        return DependencyStatus(name=_DEPENDENCY_NAME, status="timeout", detail="request timed out")
    except httpx.HTTPError:
        # Sanitized: never echo the url, key, or raw exception text.
        return DependencyStatus(name=_DEPENDENCY_NAME, status="error", detail="request failed")
    if resp.is_success:
        return DependencyStatus(name=_DEPENDENCY_NAME, status="ok")
    return DependencyStatus(
        name=_DEPENDENCY_NAME, status="error", detail=f"unexpected status {resp.status_code}"
    )
