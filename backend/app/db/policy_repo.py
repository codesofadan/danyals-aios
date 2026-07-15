"""Data access for the Policy-Radar tables via the RLS-scoped ``rls_connection``.

Reads are staff-scoped, mutations owner/admin/manager-scoped, all by Postgres RLS
(0019). This chunk exposes the READ surface (sources / changes / KB / recommendations)
plus the recommendation STATUS TRANSITIONS. The change-detection watcher that fills
policy_sources.last_hash + change_events + kb_entries runs on the PRIVILEGED pool in
a later chunk (service_role bypasses RLS), so it is not wired here.

BASELINE recommendations (``app/services/policy_baseline.py``) are surfaced by
``list_recommendations``: the DB rows first, then the evergreen constants not yet
materialized (deduped by ``kb_ref``). The FIRST time a lead transitions a baseline
rec, ``transition_recommendation`` MATERIALIZES it into the DB with the new status;
thereafter it is a real row and the dedup drops the constant.

Methods are synchronous - the router offloads them with ``asyncio.to_thread`` - and
the single ``get_policy_repo`` dependency makes the layer trivially replaceable with
an in-memory fake in tests. SQL rule: every VALUE is a bound param; the only dynamic
column list (the materialize insert) comes from a server-built dict quoted via
``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection
from app.services.policy_baseline import baseline_by_id, merge_baseline

_Rows = list[dict[str, Any]]


class PolicyRepo:
    """Thin repository over the Policy-Radar tables (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- reads --------------------------------------------------------------- #
    def list_sources(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.policy_sources order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_changes(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.change_events order by detected_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_kb(
        self,
        *,
        severity: str | None = None,
        category: str | None = None,
        region: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.kb_entries"
        clauses: list[str] = []
        params: list[Any] = []
        if severity is not None:
            clauses.append("severity = %s")
            params.append(severity)
        if category is not None:
            clauses.append("category = %s")
            params.append(category)
        if region is not None:
            clauses.append("region = %s")
            params.append(region)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by detected_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_recommendations(
        self,
        *,
        status: str | None = None,
        include_baseline: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        """The recommendations (newest DB rows first) MERGED with the evergreen
        baseline recs (deduped by ``kb_ref``). ``status`` filters the DB rows; a
        status filter also excludes baseline (they carry their own 'new' status).
        The baseline set is small and always surfaced in full."""
        query = "select * from public.recommendations"
        params: list[Any] = []
        if status is not None:
            query += " where status = %s"
            params.append(status)
        query += " order by created_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            db_rows = cur.fetchall()
        # A status filter is asking for a specific DB state, so don't fold in the
        # always-'new' baseline constants there.
        surface_baseline = include_baseline and status is None
        return merge_baseline(db_rows, include_baseline=surface_baseline)

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        """A single DB recommendation by id, or ``None`` (unknown / a not-yet-
        materialized baseline id)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.recommendations where id = %s limit 1", (rec_id,)
            )
            return cur.fetchone()

    # --- transitions --------------------------------------------------------- #
    def transition_recommendation(
        self, rec_id: str, new_status: str
    ) -> dict[str, Any] | None:
        """Set a recommendation's status, returning the updated/created row or
        ``None`` (unknown id).

        A DB row updates in place. A baseline rec (its synthetic ``rec-base-*`` id is
        not in the DB) is MATERIALIZED: inserted with the new status so the lead's
        decision persists and future lists dedup the constant away. Only a lead
        (owner/admin/manager) reaches here; RLS enforces that on both the UPDATE and
        the INSERT."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.recommendations set status = %s where id = %s returning *",
                (new_status, rec_id),
            )
            updated = cur.fetchone()
            if updated is not None:
                return updated

        base = baseline_by_id(rec_id)
        if base is None:
            return None
        # Materialize: drop the synthetic id (the DB assigns a uuid) and pin the
        # new status. kb_entry_id is NULL (no live KB entry backs a baseline rec).
        base.pop("id", None)
        base["status"] = new_status
        cols = list(base.keys())
        stmt = sql.SQL(
            "insert into public.recommendations ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(base.values()))
            return cast("dict[str, Any]", cur.fetchone())


def get_policy_repo(user: CurrentUserDep) -> PolicyRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return PolicyRepo(user.id)


PolicyRepoDep = Annotated[PolicyRepo, Depends(get_policy_repo)]
