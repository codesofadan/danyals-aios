"""Data access for the ``audits`` job ledger via the RLS-scoped ``rls_connection``
seam. Reads + the queued-row insert are tenant-scoped by Postgres RLS; the
worker's status updates use the service_role path instead (see
``workers/tasks/audit.py``). Methods are synchronous - the router offloads them
with ``asyncio.to_thread`` - and the single ``get_audits_repo`` dependency makes
the layer trivially replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class AuditsRepo:
    """Thin repository over the ``audits`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.audits order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.audits where id = %s limit 1", (audit_id,))
            return cur.fetchone()

    def insert_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL("insert into public.audits ({cols}) values ({vals}) returning *").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())


def get_audits_repo(user: CurrentUserDep) -> AuditsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped).

    Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return AuditsRepo(user.id)


AuditsRepoDep = Annotated[AuditsRepo, Depends(get_audits_repo)]
