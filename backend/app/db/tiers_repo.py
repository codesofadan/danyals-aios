"""Per-client delivery-tier data access via the RLS-scoped user-JWT client."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]
_COLS = "id,name,industry,contact_color,delivery_tier"


class TiersRepo:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    def list_tier_clients(self) -> _Rows:
        resp = self._client().table("clients").select(_COLS).order("name").execute()
        return cast("_Rows", resp.data or [])

    def set_delivery_tier(self, client_id: str, tier: str) -> dict[str, Any] | None:
        resp = (
            self._client().table("clients").update({"delivery_tier": tier}).eq("id", client_id).execute()
        )
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None


def get_tiers_repo(request: Request) -> TiersRepo:
    token: str = getattr(request.state, "access_token", "")
    return TiersRepo(token)


TiersRepoDep = Annotated[TiersRepo, Depends(get_tiers_repo)]
