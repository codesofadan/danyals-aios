"""Data access for the ``tasks`` ledger via the RLS-scoped ``rls_connection`` seam.

Every read + mutation is tenant/actor-scoped by Postgres RLS AND the
``tasks_guard_*`` triggers (the lifecycle boundary lives at the DB, not here).
Writes MUST stay on this authenticated path: the triggers read
``current_app_role()`` off ``auth.uid()``, which is NULL on the privileged pool.
Methods are synchronous - the router offloads them with ``asyncio.to_thread`` -
and the single ``get_tasks_repo`` dependency makes the layer trivially
replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class TasksRepo:
    """Thin repository over the ``tasks`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_tasks(
        self, assignee_id: str | None = None, *, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.tasks"
        params: list[Any] = []
        if assignee_id is not None:
            query += " where assignee_id = %s"
            params.append(assignee_id)
        query += " order by created_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_board_tasks(
        self, *, assignee: str | None = None, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        """The board newest-first, each row carrying its assignee's DISPLAY NAME.

        Additive read for the ``task_board`` tool workspace (Part 8 Phase 2.5). Every
        other read here exposes ``assignee_id`` only (``TaskResponse.assignee`` IS the
        uuid - the frontend resolves names off its own roster), so a server-rendered
        board had no way to NAME an assignee without one ``get_user`` round-trip per
        row. This left-joins the roster instead: one query, no N+1.

        LEFT join, not inner: an unassigned task (``assignee_id is null``) must still
        appear on the board - an inner join would silently drop it. ``assignee_name``
        is '' for that case, which the caller renders as "Unassigned". Both tables are
        RLS-scoped on this path (staff read the whole board + the whole roster), so the
        join can never widen what the caller may see.
        """
        query = (
            "select t.*, coalesce(u.name, '') as assignee_name "
            "from public.tasks t "
            "left join public.users u on u.id = t.assignee_id "
        )
        params: list[Any] = []
        # `assignee` scopes the board to one person. RLS lets any staff member read
        # every task, so without this the tool workspace hands a team member the
        # whole board - the same leak the /tasks route carries, through a second door.
        if assignee is not None:
            query += "where t.assignee_id = %s "
            params.append(assignee)
        query += "order by t.created_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_task_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.tasks where code = %s limit 1", (code,))
            return cur.fetchone()

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Read a full user row - used to validate an assignee is staff (role)
        and to load the caller's own member record for GET /me.

        Uses the same RLS-scoped path; staff may read the whole roster (users_select).
        """
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.users where id = %s limit 1", (user_id,))
            return cur.fetchone()

    def insert_task(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL("insert into public.tasks ({cols}) values ({vals}) returning *").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def update_task_by_code(
        self, code: str, patch: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        """Update a task by code, returning the updated row or ``None``.

        When ``expect_status`` is given the update is additionally gated on the
        current status (optimistic concurrency): a racing transition that already
        moved the row matches 0 rows, so the caller can raise 409 instead of
        silently double-advancing.
        """
        cols = list(patch.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        where = sql.SQL("code = %s")
        params: list[Any] = [*patch.values(), code]
        if expect_status is not None:
            where = sql.SQL("code = %s and status = %s")
            params.append(expect_status)
        stmt = sql.SQL("update public.tasks set {sets} where {where} returning *").format(
            sets=assignments, where=where
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchone()

    # --- deadline-change requests (0074) --------------------------------------

    def insert_deadline_request(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.task_deadline_requests ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def list_deadline_requests(self, task_id: str) -> _Rows:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.task_deadline_requests "
                "where task_id = %s order by created_at desc",
                (task_id,),
            )
            return cur.fetchall()

    def get_pending_deadline_request(self, task_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.task_deadline_requests "
                "where task_id = %s and status = 'pending' limit 1",
                (task_id,),
            )
            return cur.fetchone()

    def get_deadline_request(self, request_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.task_deadline_requests where id = %s limit 1",
                (request_id,),
            )
            return cur.fetchone()

    def decide_deadline_request(
        self, request_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a request's decision, gated on it still being pending (optimistic)."""
        cols = list(patch.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        params: list[Any] = [*patch.values(), request_id]
        stmt = sql.SQL(
            "update public.task_deadline_requests set {sets} "
            "where id = %s and status = 'pending' returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchone()


def get_tasks_repo(user: CurrentUserDep) -> TasksRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped).

    Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return TasksRepo(user.id)


TasksRepoDep = Annotated[TasksRepo, Depends(get_tasks_repo)]
