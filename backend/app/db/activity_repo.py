"""Read access to the activity feed via the RLS-scoped user-JWT client (staff)."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class ActivityRepo:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def list_activity(self, limit: int = 50) -> _Rows:
        client = client_for_user(self._token)
        resp = (
            client.table("activity_log")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return cast("_Rows", resp.data or [])


def get_activity_repo(request: Request) -> ActivityRepo:
    token: str = getattr(request.state, "access_token", "")
    return ActivityRepo(token)


ActivityRepoDep = Annotated[ActivityRepo, Depends(get_activity_repo)]
