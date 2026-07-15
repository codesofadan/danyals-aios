"""Read access to the activity feed via the RLS-scoped ``rls_connection`` seam (staff)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class ActivityRepo:
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_activity(self, limit: int | None = 50, offset: int = 0) -> _Rows:
        query = "select * from public.activity_log order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def get_activity_repo(user: CurrentUserDep) -> ActivityRepo:
    """Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return ActivityRepo(user.id)


ActivityRepoDep = Annotated[ActivityRepo, Depends(get_activity_repo)]
