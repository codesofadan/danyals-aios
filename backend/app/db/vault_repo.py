"""Read access to vault key METADATA via the RLS-scoped user-JWT client.

Only the masked list is read here (RLS restricts it to owner/admin). The raw
secret is never touched on this path - reveal goes through the service layer.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.core.auth import CurrentUserDep
from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class VaultRepo:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def list_keys(self) -> _Rows:
        client = client_for_user(self._token)
        resp = client.table("vault_keys").select("*").order("created_at").execute()
        return cast("_Rows", resp.data or [])


def get_vault_repo(request: Request, _user: CurrentUserDep) -> VaultRepo:
    """Depends on ``get_current_user`` (via ``_user``) so auth resolves first and
    populates ``request.state.access_token`` before this factory reads it -
    independent of the sibling-dependency order in a route's signature.
    """
    token: str = getattr(request.state, "access_token", "")
    return VaultRepo(token)


VaultRepoDep = Annotated[VaultRepo, Depends(get_vault_repo)]
