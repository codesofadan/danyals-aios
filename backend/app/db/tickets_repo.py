"""Data access for the ``support_tickets`` ledger via the RLS-scoped ``rls_connection``.

Every read + mutation is tenant/actor-scoped by Postgres RLS (staff read; leads
manage - see 0024). Writes MUST stay on this authenticated path so
``current_app_role()`` resolves off the caller's ``auth.uid()``. Methods are
synchronous - the router offloads them with ``asyncio.to_thread`` - and the single
``get_tickets_repo`` dependency makes the layer trivially replaceable with an
in-memory fake in tests.

SQL rules (impersonation-review mandate): every VALUE is a bound param; the only
dynamic column lists (insert/update) come from server-built dicts and are quoted via
``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class TicketsRepo:
    """Thin repository over the ``support_tickets`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_tickets(
        self, *, status: str | None = None, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.support_tickets"
        params: list[Any] = []
        if status is not None:
            query += " where status = %s"
            params.append(status)
        query += " order by opened_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_ticket_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.support_tickets where code = %s limit 1", (code,)
            )
            return cur.fetchone()

    def insert_ticket(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.support_tickets ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def update_ticket_by_code(
        self, code: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a ticket by code, returning the updated row or ``None`` (unknown
        code). ``changes`` must be non-empty (the router guards that)."""
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
        )
        stmt = sql.SQL(
            "update public.support_tickets set {sets} where code = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), code])
            return cur.fetchone()


def get_tickets_repo(user: CurrentUserDep) -> TicketsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return TicketsRepo(user.id)


TicketsRepoDep = Annotated[TicketsRepo, Depends(get_tickets_repo)]
