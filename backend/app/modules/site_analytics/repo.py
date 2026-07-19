"""Data access for the site-analytics ledgers (``gsc_properties`` / ``ga4_properties``)
via the RLS-scoped ``rls_connection`` seam + the privileged ``ServiceSiteAnalyticsStore``
the sync workers write through.

Every read + mutation on ``SiteAnalyticsRepo`` is tenant/actor-scoped by Postgres RLS:
staff read the whole surface, clients are excluded (no base-table select policy), and
only leads (owner/admin/manager) may write (the ``0047`` insert/update policies + the
router's ``require_role`` gate). Methods are synchronous (psycopg is sync) - the
router offloads them with ``asyncio.to_thread``.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``), never
string-formatted; table/column names are static literals.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]


def _is_uuid(value: str) -> bool:
    """Whether ``value`` is a syntactically valid UUID. ``id`` is a ``uuid`` column,
    so a malformed path segment (e.g. a client hitting ``/properties/nonexistent``)
    would otherwise reach Postgres as a raw cast and raise
    ``InvalidTextRepresentation`` - an unhandled 500, not the clean 404 an unknown id
    gets. Every single-row lookup below checks this FIRST so a malformed id is
    indistinguishable from an unknown one, exactly like an RLS-hidden row."""
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


class SiteAnalyticsRepo:
    """Thin RLS-scoped repository over the GSC + GA4 property ledgers."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- GSC --------------------------------------------------------------
    def list_gsc(self, *, client_id: str | None = None) -> _Rows:
        if client_id is not None and not _is_uuid(client_id):
            return []
        query = "select * from public.gsc_properties"
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        query += " order by client_name, site_url"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_gsc(self, property_id: str) -> dict[str, Any] | None:
        if not _is_uuid(property_id):
            return None
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.gsc_properties where id = %s limit 1", (property_id,)
            )
            return cur.fetchone()

    def add_gsc(self, *, client_id: str, client_name: str, site_url: str) -> dict[str, Any]:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.gsc_properties (client_id, client_name, site_url) "
                "values (%s, %s, %s) returning *",
                (client_id, client_name, site_url),
            )
            row = cur.fetchone()
        assert row is not None  # an insert always returns its own row
        return row

    # --- GA4 --------------------------------------------------------------
    def list_ga4(self, *, client_id: str | None = None) -> _Rows:
        if client_id is not None and not _is_uuid(client_id):
            return []
        query = "select * from public.ga4_properties"
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        query += " order by client_name, property_id"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_ga4(self, property_id: str) -> dict[str, Any] | None:
        if not _is_uuid(property_id):
            return None
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.ga4_properties where id = %s limit 1", (property_id,)
            )
            return cur.fetchone()

    def add_ga4(self, *, client_id: str, client_name: str, property_id: str) -> dict[str, Any]:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.ga4_properties (client_id, client_name, property_id) "
                "values (%s, %s, %s) returning *",
                (client_id, client_name, property_id),
            )
            row = cur.fetchone()
        assert row is not None
        return row

    # --- shared -------------------------------------------------------------
    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or
        ``None`` - used to SNAPSHOT client_name so the internal client_id never
        surfaces."""
        if not _is_uuid(client_id):
            return None
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None


def get_site_analytics_repo(user: CurrentUserDep) -> SiteAnalyticsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return SiteAnalyticsRepo(user.id)


SiteAnalyticsRepoDep = Annotated[SiteAnalyticsRepo, Depends(get_site_analytics_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the OAuth callback + sync workers.
# --------------------------------------------------------------------------- #
class ServiceSiteAnalyticsStore:
    """Concrete site-analytics store over ``privileged_connection`` (BYPASSRLS).

    The oauth callback runs UNAUTHENTICATED (Google's redirect carries no bearer
    token - see the router module docstring), and the sync workers have no user
    JWT either, so both go through this privileged store exactly like
    ``ServiceLocalStore``.
    """

    def gsc_for_sync(self, property_id: str) -> dict[str, Any] | None:
        if not _is_uuid(property_id):
            return None
        with privileged_connection() as cur:
            cur.execute(
                "select id, client_id, site_url, oauth_connected, oauth_vault_ref "
                "from public.gsc_properties where id = %s limit 1",
                (property_id,),
            )
            return cur.fetchone()

    def ga4_for_sync(self, property_id: str) -> dict[str, Any] | None:
        if not _is_uuid(property_id):
            return None
        with privileged_connection() as cur:
            cur.execute(
                "select id, client_id, property_id, oauth_connected, oauth_vault_ref "
                "from public.ga4_properties where id = %s limit 1",
                (property_id,),
            )
            return cur.fetchone()

    def connect_gsc(self, property_id: str, *, oauth_vault_ref: str) -> None:
        """Mark a GSC property connected once the callback has sealed its token."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.gsc_properties set "
                "oauth_connected = true, oauth_vault_ref = %s where id = %s",
                (oauth_vault_ref, property_id),
            )

    def connect_ga4(self, property_id: str, *, oauth_vault_ref: str) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.ga4_properties set "
                "oauth_connected = true, oauth_vault_ref = %s where id = %s",
                (oauth_vault_ref, property_id),
            )

    def update_gsc_sync(
        self,
        property_id: str,
        *,
        clicks: int,
        impressions: int,
        ctr: float,
        avg_position: float,
        top_queries: list[dict[str, Any]],
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.gsc_properties set "
                "clicks_28d = %s, impressions_28d = %s, ctr_28d = %s, "
                "avg_position_28d = %s, top_queries = %s, last_synced_at = now() "
                "where id = %s",
                (clicks, impressions, ctr, avg_position, json.dumps(top_queries), property_id),
            )

    def update_ga4_sync(
        self, property_id: str, *, sessions: int, users: int, conversions: int
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.ga4_properties set "
                "sessions_28d = %s, users_28d = %s, conversions_28d = %s, last_synced_at = now() "
                "where id = %s",
                (sessions, users, conversions, property_id),
            )


def service_site_analytics_store() -> ServiceSiteAnalyticsStore:
    """The privileged store the oauth callback + sync workers use (service_role,
    BYPASSRLS)."""
    return ServiceSiteAnalyticsStore()
