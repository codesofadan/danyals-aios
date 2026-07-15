"""Data access for the ``upsells`` catalogue via the RLS-scoped ``rls_connection``.

The upsells table is AGENCY-GLOBAL (no client_id): staff read the shared catalogue,
owner/admin manage it (RLS enforces both). Methods are synchronous - the router
offloads them with ``asyncio.to_thread`` - and the single ``get_upsells_repo``
dependency makes the layer trivially replaceable with an in-memory fake in tests.

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


class UpsellsRepo:
    """Thin repository over the ``upsells`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_upsells(
        self, *, active_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.upsells"
        params: list[Any] = []
        if active_only:
            query += " where active = true"
        query += " order by sort_order, created_at"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_upsell(self, upsell_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.upsells where id = %s limit 1", (upsell_id,))
            return cur.fetchone()

    def insert_upsell(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL("insert into public.upsells ({cols}) values ({vals}) returning *").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def update_upsell(self, upsell_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update an upsell by id, returning the updated row or ``None`` (unknown
        id). ``changes`` must be non-empty (the router guards that)."""
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
        )
        stmt = sql.SQL("update public.upsells set {sets} where id = %s returning *").format(
            sets=assignments
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), upsell_id])
            return cur.fetchone()


def get_upsells_repo(user: CurrentUserDep) -> UpsellsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return UpsellsRepo(user.id)


UpsellsRepoDep = Annotated[UpsellsRepo, Depends(get_upsells_repo)]
