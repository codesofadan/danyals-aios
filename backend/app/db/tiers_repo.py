"""Per-client delivery-tier data access via the RLS-scoped ``rls_connection`` seam."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]
_COLS = "id, name, industry, contact_color, delivery_tier"


class TiersRepo:
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_tier_clients(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = f"select {_COLS} from public.clients order by name"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def set_delivery_tier(self, client_id: str, tier: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.clients set delivery_tier = %s where id = %s returning *",
                (tier, client_id),
            )
            return cur.fetchone()


def get_tiers_repo(user: CurrentUserDep) -> TiersRepo:
    """Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return TiersRepo(user.id)


TiersRepoDep = Annotated[TiersRepo, Depends(get_tiers_repo)]
