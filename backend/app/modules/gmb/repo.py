"""Data access for the ``gmb_posts`` ledger via the RLS-scoped ``rls_connection``.

Every read + mutation is tenant/actor-scoped by Postgres RLS (the base-table policies
mirror the router's role gates: staff read, leads write). Methods are synchronous - the
router offloads them with ``asyncio.to_thread`` - and the single ``get_gmb_repo``
dependency makes the layer trivially replaceable with an in-memory fake in tests.
Every VALUE is a bound ``%s`` param; dynamic column lists come only from server-built
dicts quoted via ``psycopg.sql.Identifier`` (impersonation-safe).
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class GmbRepo:
    """Thin repository over the ``gmb_posts`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_posts(
        self,
        *,
        client_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.gmb_posts"
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by created_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_post_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.gmb_posts where code = %s limit 1", (code,))
            return cur.fetchone()

    def insert_post(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.gmb_posts ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def update_post_by_code(
        self, code: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        """Update a post by code, returning the row or ``None``. When ``expect_status``
        is given the update is gated on the current status (optimistic concurrency): a
        racing transition matches 0 rows, so the caller can raise 409."""
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols)
        where = sql.SQL("code = %s")
        params: list[Any] = [*changes.values(), code]
        if expect_status is not None:
            where = sql.SQL("code = %s and status = %s")
            params.append(expect_status)
        stmt = sql.SQL(
            "update public.gmb_posts set {sets} where {where} returning *"
        ).format(sets=assignments, where=where)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchone()


def get_gmb_repo(user: CurrentUserDep) -> GmbRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return GmbRepo(user.id)


GmbRepoDep = Annotated[GmbRepo, Depends(get_gmb_repo)]
