"""Data access for the ``audits`` job ledger via the RLS-respecting user-JWT
client. Reads + the queued-row insert are tenant-scoped by Postgres RLS; the
worker's status updates use the service_role client instead (see
``workers/tasks/audit.py``). Methods are synchronous - the router offloads them
with ``asyncio.to_thread`` - and the single ``get_audits_repo`` dependency makes
the layer trivially replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.core.auth import CurrentUserDep
from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class AuditsRepo:
    """Thin repository over the ``audits`` table (user-JWT, RLS-scoped)."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = self._client().table("audits").select("*").order("created_at", desc=True)
        if limit is not None:
            query = query.range(offset, offset + limit - 1)
        resp = query.execute()
        return cast("_Rows", resp.data or [])

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        resp = self._client().table("audits").select("*").eq("id", audit_id).limit(1).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None

    def insert_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        resp = self._client().table("audits").insert(row).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0]


def get_audits_repo(request: Request, _user: CurrentUserDep) -> AuditsRepo:
    """Dependency: a repo bound to the caller's access token (RLS-scoped).

    Depends on ``get_current_user`` (via ``_user``) so auth resolves first and
    populates ``request.state.access_token`` before this factory reads it -
    independent of the sibling-dependency order in a route's signature.
    """
    token: str = getattr(request.state, "access_token", "")
    return AuditsRepo(token)


AuditsRepoDep = Annotated[AuditsRepo, Depends(get_audits_repo)]
