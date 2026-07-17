"""Data access for the ``content_jobs`` ledger via the RLS-scoped ``rls_connection``.

Every read + mutation is tenant/actor-scoped by Postgres RLS AND the
``content_jobs_guard_*`` triggers (the lifecycle boundary lives at the DB, not
here). Human writes MUST stay on this authenticated path: the triggers read
``current_app_role()`` off ``auth.uid()``, which is NULL on the privileged pool -
the WORKER path (queued->drafting->... advances) runs on ``privileged_connection``
in a later chunk, where the same trigger recognises it by ``auth.uid() IS NULL``.
Methods are synchronous - the router offloads them with ``asyncio.to_thread`` -
and the single ``get_content_repo`` dependency makes the layer trivially
replaceable with an in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class ContentRepo:
    """Thin repository over the ``content_jobs`` table (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_jobs(
        self,
        *,
        assignee_id: str | None = None,
        client_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.content_jobs"
        clauses: list[str] = []
        params: list[Any] = []
        if assignee_id is not None:
            clauses.append("assignee_id = %s")
            params.append(assignee_id)
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

    def get_job_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.content_jobs where code = %s limit 1", (code,))
            return cur.fetchone()

    def insert_job(self, row: dict[str, Any]) -> dict[str, Any]:
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.content_jobs ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(row.values()))
            return cast("dict[str, Any]", cur.fetchone())

    def update_job_by_code(
        self, code: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        """Update a content job by code, returning the updated row or ``None``.

        When ``expect_status`` is given the update is additionally gated on the
        current status (optimistic concurrency): a racing transition that already
        moved the row matches 0 rows, so the caller can raise 409 instead of
        silently double-advancing. The DB trigger remains the real transition gate.
        """
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        where = sql.SQL("code = %s")
        params: list[Any] = [*changes.values(), code]
        if expect_status is not None:
            where = sql.SQL("code = %s and status = %s")
            params.append(expect_status)
        stmt = sql.SQL(
            "update public.content_jobs set {sets} where {where} returning *"
        ).format(sets=assignments, where=where)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchone()

    def stats(self) -> dict[str, int]:
        """Return a ``{status: count}`` breakdown over the caller-visible jobs.

        RLS-scoped like every other read; an empty ledger yields ``{}``. The router
        can total these for the board's column counts without pulling every row.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select status, count(*) as n from public.content_jobs group by status"
            )
            return {str(r["status"]): int(r["n"]) for r in cur.fetchall()}


    def publish_stats(self, *, days: int) -> dict[str, int]:
        """The publish tiles in ONE pass: scheduled / failed / published(window).

        Additive read for the ``publishing`` tool workspace (Part 8 Phase 2.5), which
        needs a WINDOWED published count: ``stats()`` is an all-time ``{status: count}``
        and cannot answer "published (30d)" without inventing the window. The
        ``filter (where ...)`` form computes every tile in a single scan (mirrors
        ``team_metrics._TASK_AGG_SQL``). ``published`` is windowed on ``updated_at`` -
        the moment the job last moved, which for a ``done`` job is when it went live.
        RLS-scoped; an empty ledger yields all zeros.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "count(*) filter (where status = 'publishing')::int as scheduled, "
                "count(*) filter (where status = 'failed')::int as failed, "
                "count(*) filter (where status = 'done' "
                "  and updated_at >= now() - (%s::int * interval '1 day'))::int as published "
                "from public.content_jobs",
                (days,),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - an aggregate always yields one row
                return {"scheduled": 0, "failed": 0, "published": 0}
            return {k: int(v or 0) for k, v in row.items()}


def get_content_repo(user: CurrentUserDep) -> ContentRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return ContentRepo(user.id)


ContentRepoDep = Annotated[ContentRepo, Depends(get_content_repo)]
