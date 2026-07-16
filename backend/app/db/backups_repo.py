"""Data access for the backups ledger + config singleton via the RLS-scoped
``rls_connection`` seam.

Two surfaces (see 0026):

* ``backup_snapshots`` - the append-mostly snapshot ledger. Any staff READ;
  owner/admin INSERT/UPDATE (RLS enforces both). The service writes one row per run
  on this authenticated path.
* ``backup_config`` - the agency-global SINGLETON pinned to ``id = 1``. Staff read;
  owner/admin manage. ``update_config`` upserts so a row always exists.

Methods are synchronous - the router/service offload them with ``asyncio.to_thread`` -
and the single ``get_backups_repo`` dependency makes the layer trivially replaceable
with an in-memory fake in tests.

SQL rules (impersonation-review mandate): every VALUE is a bound param; dynamic
column lists come from server-built dicts and are quoted via ``psycopg.sql.Identifier``;
the only table names are fixed literals chosen in-method (never request input).
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class BackupsRepo:
    """Thin repository over ``backup_snapshots`` + the ``backup_config`` singleton."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- Snapshot ledger -----------------------------------------------------
    def list_snapshots(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.backup_snapshots order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.backup_snapshots where id = %s limit 1",
                (snapshot_id,),
            )
            return cur.fetchone()

    def insert_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.backup_snapshots ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def count_snapshots(self) -> int:
        """Count the caller-visible snapshots (drives the config ``retained`` counter)."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select count(*) as n from public.backup_snapshots")
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    # --- Config singleton ----------------------------------------------------
    def get_config(self) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.backup_config where id = 1 limit 1")
            return cur.fetchone()

    def update_config(self, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Upsert the ``id = 1`` config row (guarantees a row exists so a GET after a
        PUT always returns the saved values). ``changes`` is non-empty."""
        cols = list(changes.keys())
        insert_cols = [sql.Identifier("id"), *(sql.Identifier(c) for c in cols)]
        placeholders = [sql.Literal(1), *([sql.Placeholder()] * len(cols))]
        assignments = sql.SQL(", ").join(
            sql.SQL("{col} = excluded.{col}").format(col=sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "insert into public.backup_config ({cols}) values ({vals}) "
            "on conflict (id) do update set {sets} returning *"
        ).format(
            cols=sql.SQL(", ").join(insert_cols),
            vals=sql.SQL(", ").join(placeholders),
            sets=assignments,
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(changes.values()))
            return cur.fetchone()


def get_backups_repo(user: CurrentUserDep) -> BackupsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return BackupsRepo(user.id)


BackupsRepoDep = Annotated[BackupsRepo, Depends(get_backups_repo)]
