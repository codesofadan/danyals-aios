"""Data access for the Reports ledgers (``report_workbooks`` /
``report_sync_events``) via the RLS-scoped ``rls_connection`` seam.

Every read + mutation is tenant/actor-scoped by Postgres RLS: any staff read the
whole board, clients are excluded (no base-table select policy), and only leads
(owner/admin/manager) may write (the RLS insert/update policies). Methods are
synchronous (psycopg is sync) - the router offloads them with ``asyncio.to_thread``
- and the single ``get_reports_repo`` dependency makes the layer trivially
replaceable with an in-memory fake in tests.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column list comes from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class ReportsRepo:
    """Thin repository over the two reports tables (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- workbooks ------------------------------------------------------------
    def list_workbooks(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """The per-client workbooks (freshest sync first); the master rollup is
        excluded (it is surfaced separately by the connection endpoint)."""
        query = (
            "select * from public.report_workbooks where is_master = false "
            "order by last_sync desc nulls last, created_at desc, id"
        )
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_workbook(self, workbook_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.report_workbooks where id = %s limit 1", (workbook_id,)
            )
            return cur.fetchone()

    def get_master(self) -> dict[str, Any] | None:
        """The single master-rollup workbook row (or ``None`` if not yet seeded)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.report_workbooks where is_master = true limit 1"
            )
            return cur.fetchone()

    def mark_synced(self, workbook_id: str, *, rows_added: int) -> dict[str, Any] | None:
        """Optimistically transition a workbook to ``synced``: set ``last_sync=now()``
        and add ``rows_added`` to today's row count. Returns the updated row or
        ``None`` (unknown / not visible). The DB is the transition boundary (RLS)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.report_workbooks set status = 'synced', last_sync = now(), "
                "rows_synced_today = rows_synced_today + %s where id = %s returning *",
                (rows_added, workbook_id),
            )
            return cur.fetchone()

    # --- sync events ----------------------------------------------------------
    def insert_sync_event(
        self, *, workbook_id: str, client_name: str, dataset: str, rows: int
    ) -> dict[str, Any]:
        """Append one push event (append-only history). ``synced_at`` defaults to now()."""
        row = {
            "workbook_id": workbook_id,
            "client_name": client_name,
            "dataset": dataset,
            "rows": rows,
        }
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.report_sync_events ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def list_sync_events(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """Recent push events, newest first (the sync-activity feed)."""
        query = "select * from public.report_sync_events order by synced_at desc, id"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()


    def sync_event_count(self, *, days: int) -> int:
        """How many report pushes landed in the last ``days`` (the "reports sent" tile).

        Additive read for the ``reporting`` tool workspace (Part 8 Phase 2.5): the event
        log is append-only and unbounded, so counting a window in Python would mean
        fetching the whole history. One aggregate answers it. RLS-scoped.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select count(*) as n from public.report_sync_events "
                "where synced_at >= now() - (%s::int * interval '1 day')",
                (days,),
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0


def workbook_tabs(row: dict[str, Any]) -> list[str]:
    """The dataset tabs stored on a workbook row, tolerant of a jsonb value that
    psycopg returns as a Python list OR (rarely) a JSON string."""
    tabs = row.get("tabs")
    if isinstance(tabs, str):
        try:
            tabs = json.loads(tabs)
        except ValueError:
            return []
    if not isinstance(tabs, list):
        return []
    return [t for t in tabs if isinstance(t, str)]


def get_reports_repo(user: CurrentUserDep) -> ReportsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return ReportsRepo(user.id)


ReportsRepoDep = Annotated[ReportsRepo, Depends(get_reports_repo)]
