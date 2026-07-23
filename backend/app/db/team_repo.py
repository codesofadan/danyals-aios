"""Data access for the STAFF roster - the eligible-assignee source (RLS-scoped).

Backs ``GET /team/members``: the full agency staff roster a lead picks a task
assignee from. It is deliberately SEPARATE from the ``admin_users`` roster read
(which requires ``manage_team``, owner/admin only): the ASSIGN flow is governed by
``assign_tasks`` (owner/admin/manager), so a manager who may assign work but not
manage the team must still be able to load the picker. Portal clients (role =
'client') are excluded in SQL - they are tenant logins, never assignable team
members - which also mirrors the ``_require_staff_assignee`` guard the /tasks
routes enforce (a task is never pointed at a client uid).

Every read flows through the RLS-scoped ``rls_connection`` seam (staff may read the
whole roster). Methods are synchronous - the router offloads them with
``asyncio.to_thread`` - and the single ``get_team_repo`` dependency makes the layer
trivially replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class TeamRepo:
    """Thin repository over the STAFF rows of ``public.users`` (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_staff(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """Every staff member (role <> 'client'), oldest first.

        No status filter: an INVITED member who has not yet logged in is still a
        valid assignee (the /tasks guard accepts any non-client), so the picker
        must show them - hiding invited members is exactly the bug this endpoint
        exists to fix.
        """
        query = "select * from public.users where role <> 'client' order by created_at"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def get_team_repo(user: CurrentUserDep) -> TeamRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return TeamRepo(user.id)


TeamRepoDep = Annotated[TeamRepo, Depends(get_team_repo)]
