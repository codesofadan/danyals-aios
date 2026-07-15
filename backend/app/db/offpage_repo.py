"""Data access for the Off-page ledgers (``backlinks`` / ``citations`` /
``web2_properties``) via the RLS-scoped ``rls_connection`` seam.

Every read + mutation is tenant/actor-scoped by Postgres RLS: staff read the whole
board, clients are excluded (no base-table select policy), and only leads (owner/
admin/manager) may write (the RLS insert/update policies + the paid-tier gate at the
service layer). Methods are synchronous (psycopg is sync) - the router offloads them
with ``asyncio.to_thread`` - and the single ``get_offpage_repo`` dependency makes the
layer trivially replaceable with an in-memory fake in tests.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class OffpageRepo:
    """Thin repository over the three off-page monitoring tables (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- backlinks ------------------------------------------------------------
    def list_backlinks(
        self,
        *,
        status: str | None = None,
        client_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.backlinks"
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        # Freshest discoveries first; id keeps the order stable across equal dates.
        query += " order by first_seen desc nulls last, created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def backlink_status_counts(self) -> dict[str, int]:
        """A ``{status: count}`` breakdown over the caller-visible backlinks (feeds
        the new/lost/toxic KPI tiles). RLS-scoped; an empty ledger yields ``{}``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select status, count(*) as n from public.backlinks group by status"
            )
            return {str(r["status"]): int(r["n"]) for r in cur.fetchall()}

    def referring_domain_count(self) -> int:
        """The live profile size: distinct referring domains over non-lost backlinks
        (a lost link is no longer part of the profile)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select count(distinct ref_domain) as n from public.backlinks "
                "where status <> 'lost'"
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    def flag_toxic_backlinks(self, *, spam_threshold: int) -> _Rows:
        """Flag every backlink at/above ``spam_threshold`` spam as ``toxic`` (the
        disavow-review queue). Idempotent: rows already ``toxic`` are skipped, so a
        re-run flags only newly-spammy links. Returns the rows it moved."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.backlinks set status = 'toxic' "
                "where spam >= %s and status <> 'toxic' returning *",
                (spam_threshold,),
            )
            return cur.fetchall()

    # --- citations ------------------------------------------------------------
    def list_citations(
        self,
        *,
        nap_status: str | None = None,
        client_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.citations"
        clauses: list[str] = []
        params: list[Any] = []
        if nap_status is not None:
            clauses.append("nap_status = %s")
            params.append(nap_status)
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_citation(self, citation_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.citations where id = %s limit 1", (citation_id,)
            )
            return cur.fetchone()

    def update_citation(
        self, citation_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update one citation by id, returning the updated row or ``None``."""
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.citations set {sets} where id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), citation_id])
            return cur.fetchone()

    def bulk_update_citations(
        self, ids: list[str], changes: dict[str, Any]
    ) -> _Rows:
        """Apply ``changes`` to every citation in ``ids`` in ONE statement, returning
        the updated rows. Empty ``ids`` is a no-op (no query). Only the rows RLS lets
        the caller see/write are affected."""
        if not ids:
            return []
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.citations set {sets} where id::text = any(%s) returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), ids])
            return cur.fetchall()

    # --- web 2.0 --------------------------------------------------------------
    def list_web2(
        self,
        *,
        client_id: str | None = None,
        platform: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.web2_properties"
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if platform is not None:
            clauses.append("platform = %s")
            params.append(platform)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by published_at desc nulls last, created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def get_offpage_repo(user: CurrentUserDep) -> OffpageRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return OffpageRepo(user.id)


OffpageRepoDep = Annotated[OffpageRepo, Depends(get_offpage_repo)]
