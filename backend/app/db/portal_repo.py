"""Data access for the CLIENT PORTAL over the ``portal_*`` security-barrier views.

Every read uses ``client_for_user`` (anon key + the client's JWT), so PostgreSQL
RLS - via the views' ``current_client_id()`` self-filter - is the boundary: a
client can only ever see its OWN client, sites, and audits, and only the safe
column subset the views expose (no cost/error/paths/mrr/contacts). The repo holds
only the caller's token; methods are synchronous (supabase-py is sync) and the
router offloads them with ``asyncio.to_thread``. A single ``get_portal_repo``
dependency makes the layer trivially replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.core.auth import CurrentUserDep
from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class PortalRepo:
    """Thin repository over the ``portal_audits`` / ``portal_client`` /
    ``portal_sites`` views (user-JWT, RLS-scoped to the calling client)."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = self._client().table("portal_audits").select("*").order("created_at", desc=True)
        if limit is not None:
            query = query.range(offset, offset + limit - 1)
        resp = query.execute()
        return cast("_Rows", resp.data or [])

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        resp = (
            self._client().table("portal_audits").select("*").eq("id", audit_id).limit(1).execute()
        )
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None

    def get_client(self) -> dict[str, Any] | None:
        """The caller's own client row (the view returns exactly one row)."""
        resp = self._client().table("portal_client").select("*").limit(1).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None

    def list_sites(self) -> _Rows:
        resp = self._client().table("portal_sites").select("*").order("domain").execute()
        return cast("_Rows", resp.data or [])


def get_portal_repo(request: Request, _user: CurrentUserDep) -> PortalRepo:
    """Dependency: a repo bound to the caller's access token (RLS-scoped).

    Depends on ``get_current_user`` (via ``_user``) so auth resolves first and
    populates ``request.state.access_token`` before this factory reads it -
    independent of the sibling-dependency order in a route's signature.
    """
    token: str = getattr(request.state, "access_token", "")
    return PortalRepo(token)


PortalRepoDep = Annotated[PortalRepo, Depends(get_portal_repo)]
