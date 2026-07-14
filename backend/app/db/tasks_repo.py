"""Data access for the ``tasks`` ledger via the RLS-respecting user-JWT client.

Every read + mutation is tenant/actor-scoped by Postgres RLS AND the
``tasks_guard_*`` triggers (the lifecycle boundary lives at the DB, not here).
Methods are synchronous - the router offloads them with ``asyncio.to_thread`` -
and the single ``get_tasks_repo`` dependency makes the layer trivially
replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class TasksRepo:
    """Thin repository over the ``tasks`` table (user-JWT, RLS-scoped)."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    def list_tasks(self, assignee_id: str | None = None) -> _Rows:
        query = self._client().table("tasks").select("*")
        if assignee_id is not None:
            query = query.eq("assignee_id", assignee_id)
        resp = query.order("created_at", desc=True).execute()
        return cast("_Rows", resp.data or [])

    def get_task_by_code(self, code: str) -> dict[str, Any] | None:
        resp = self._client().table("tasks").select("*").eq("code", code).limit(1).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None

    def insert_task(self, row: dict[str, Any]) -> dict[str, Any]:
        resp = self._client().table("tasks").insert(row).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0]

    def update_task_by_code(
        self, code: str, patch: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        """Update a task by code, returning the updated row or ``None``.

        When ``expect_status`` is given the update is additionally gated on the
        current status (optimistic concurrency): a racing transition that already
        moved the row matches 0 rows, so the caller can raise 409 instead of
        silently double-advancing.
        """
        query = self._client().table("tasks").update(patch).eq("code", code)
        if expect_status is not None:
            query = query.eq("status", expect_status)
        resp = query.execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else None


def get_tasks_repo(request: Request) -> TasksRepo:
    """Dependency: a repo bound to the caller's access token (RLS-scoped)."""
    token: str = getattr(request.state, "access_token", "")
    return TasksRepo(token)


TasksRepoDep = Annotated[TasksRepo, Depends(get_tasks_repo)]
