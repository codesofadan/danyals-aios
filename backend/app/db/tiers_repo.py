"""Per-client delivery-tier data access via the RLS-scoped user-JWT client."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.core.auth import CurrentUserDep
from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]
_COLS = "id,name,industry,contact_color,delivery_tier"


class TiersRepo:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    def list_tier_clients(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = self._client().table("clients").select(_COLS).order("name")
        if limit is not None:
            query = query.range(offset, offset + limit - 1)
        resp = query.execute()
        return cast("_Rows", resp.data or [])

    def set_delivery_tier(self, client_id: str, tier: str) -> dict[str, Any] | None:
        resp = (
            self._client().table("clients").update({"delivery_tier": tier}).eq("id", client_id).execute()
        )
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None


def get_tiers_repo(request: Request, _user: CurrentUserDep) -> TiersRepo:
    """Depends on ``get_current_user`` (via ``_user``) so auth resolves first and
    populates ``request.state.access_token`` before this factory reads it -
    independent of the sibling-dependency order in a route's signature.
    """
    token: str = getattr(request.state, "access_token", "")
    return TiersRepo(token)


TiersRepoDep = Annotated[TiersRepo, Depends(get_tiers_repo)]
