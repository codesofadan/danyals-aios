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
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

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


    # --- autonomous cron: last-run heartbeats + produced reports ---------------
    def latest_job_runs(self) -> _Rows:
        """The most recent run per scheduled job (``distinct on job_name``).

        Powers the "Scheduled jobs" panel's last-run / last-status columns: the beat
        schedule carries only a cadence, so WHEN each job last ran and HOW it went comes
        from the ``scheduled_job_runs`` ledger the workers append to. RLS-scoped (staff
        read; a portal client has no select policy)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select distinct on (job_name) job_name, task, status, detail, created_at "
                "from public.scheduled_job_runs order by job_name, created_at desc"
            )
            return cur.fetchall()

    def list_generated_reports(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """The autonomously-produced, downloadable reports (newest first).

        Only rows that carry a ``report`` payload (the monthly per-client SEO summary);
        a pure heartbeat run is excluded. RLS-scoped (staff read)."""
        query = (
            "select id, job_name, client_name, title, period, report, created_at "
            "from public.scheduled_job_runs where report is not null "
            "order by created_at desc, id"
        )
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_generated_report(self, report_id: str) -> dict[str, Any] | None:
        """One produced report by id (for the download), or ``None`` if unknown / not a
        report row. RLS-scoped (staff read)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, client_name, title, period, report, created_at "
                "from public.scheduled_job_runs where id = %s and report is not null limit 1",
                (report_id,),
            )
            return cur.fetchone()

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


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the autonomous REPORTS WORKERS.
# --------------------------------------------------------------------------- #
# The beat-driven report jobs (audit refresh, monthly SEO report, off-page sweep) have
# no user JWT, so - exactly like the audit / rank / off-page workers - they read the
# tenant tables and append the run/report ledger on the privileged connection
# (service_role bypasses the RLS policies by design). Each method opens its own
# privileged connection, so the store is stateless and safe to instantiate per call.
class ServiceReportsStore:
    """Concrete report-jobs store over ``privileged_connection`` (BYPASSRLS)."""

    # --- active clients (the fan-out set for every report job) ----------------
    def list_active_clients(self, *, limit: int) -> _Rows:
        """Active clients + their PRIMARY site domain (oldest site), newest-name order.

        ``domain`` is NULL for a client with no site (the audit refresh / off-page sweep
        skip it; the monthly report still runs). One correlated subquery keeps it to a
        single round trip."""
        with privileged_connection() as cur:
            cur.execute(
                "select c.id as client_id, c.name as client_name, "
                "(select s.domain from public.sites s where s.client_id = c.id "
                " order by s.created_at asc, s.id limit 1) as domain "
                "from public.clients c where c.status = 'active' "
                "order by c.name limit %s",
                (limit,),
            )
            return cur.fetchall()

    # --- weekly audit refresh -------------------------------------------------
    def recent_audit_exists(self, client_id: str, *, since: datetime) -> bool:
        """True if the client already has an audit created at/after ``since`` - the
        idempotency guard that stops a re-delivered weekly tick double-creating audits."""
        with privileged_connection() as cur:
            cur.execute(
                "select 1 from public.audits where client_id = %s and created_at >= %s limit 1",
                (client_id, since),
            )
            return cur.fetchone() is not None

    def insert_audit(
        self, *, client_id: str, client_name: str, url: str, tier: str
    ) -> str:
        """Insert a queued audit row (the worker then runs it) and return its id.

        Mirrors the /audits enqueue insert but on the privileged path (no actor JWT):
        ``types`` is left to its ``'{}'`` column default = a FULL run (avoids psycopg's
        empty-array type-inference); status starts ``queued``."""
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.audits (client_id, client_name, url, tier, status) "
                "values (%s, %s, %s, %s, 'queued') returning id",
                (client_id, client_name, url, tier),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else ""

    # --- monthly SEO report ---------------------------------------------------
    def report_exists(self, *, client_id: str, period: str, title: str) -> bool:
        """True if a report with this ``title`` already exists for the client + period -
        the idempotency guard for the monthly job (one report per client per month)."""
        with privileged_connection() as cur:
            cur.execute(
                "select 1 from public.scheduled_job_runs "
                "where client_id = %s and period = %s and title = %s and report is not null limit 1",
                (client_id, period, title),
            )
            return cur.fetchone() is not None

    def monthly_metrics(self, client_id: str) -> dict[str, Any]:
        """The real numbers a monthly SEO report summarizes, from the tenant's own rows.

        Audit-score trend, content shipped (30d), tracked-keyword ranks, and the
        backlink / citation profile - all on ONE privileged connection. Degrades to
        honest zeros on any DB hiccup (the caller records a degraded run) rather than
        raising into the beat task."""
        metrics: dict[str, Any] = {
            "audit_first": None, "audit_latest": None, "audit_delta": None,
            "content_30d": 0, "keywords_tracked": 0, "keywords_top10": 0,
            "backlinks_total": 0, "backlinks_new_30d": 0, "citations_total": 0,
        }
        with privileged_connection() as cur:
            cur.execute(
                "select score from public.audits "
                "where client_id = %s and score is not null "
                "order by coalesce(finished_at, created_at)",
                (client_id,),
            )
            scores = [int(r["score"]) for r in cur.fetchall()]
            if scores:
                metrics["audit_first"] = scores[0]
                metrics["audit_latest"] = scores[-1]
                metrics["audit_delta"] = scores[-1] - scores[0]

            cur.execute(
                "select count(*) as n from public.content_jobs "
                "where client_id = %s and status = 'done' "
                "and updated_at >= now() - interval '30 days'",
                (client_id,),
            )
            metrics["content_30d"] = _count(cur.fetchone())

            cur.execute(
                "select "
                "count(*) as tracked, "
                "count(*) filter (where latest_position is not null and latest_position <= 10) "
                "  as top10 "
                "from public.tracked_keywords where client_id = %s and status = 'active'",
                (client_id,),
            )
            krow = cur.fetchone() or {}
            metrics["keywords_tracked"] = int(krow.get("tracked") or 0)
            metrics["keywords_top10"] = int(krow.get("top10") or 0)

            cur.execute(
                "select "
                "count(*) filter (where coalesce(status, '') <> 'lost') as total, "
                "count(*) filter (where created_at >= now() - interval '30 days') as new30 "
                "from public.backlinks where client_id = %s and competitor_id is null",
                (client_id,),
            )
            brow = cur.fetchone() or {}
            metrics["backlinks_total"] = int(brow.get("total") or 0)
            metrics["backlinks_new_30d"] = int(brow.get("new30") or 0)

            cur.execute(
                "select count(*) as n from public.citations where client_id = %s",
                (client_id,),
            )
            metrics["citations_total"] = _count(cur.fetchone())
        return metrics

    # --- the run / report ledger ----------------------------------------------
    def record_run(
        self, *, job_name: str, task: str, status: str, detail: str
    ) -> str:
        """Append a heartbeat run (no report payload). Returns the row id."""
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.scheduled_job_runs (job_name, task, status, detail) "
                "values (%s, %s, %s, %s) returning id",
                (job_name, task, status, detail),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else ""

    def insert_report(
        self,
        *,
        job_name: str,
        task: str,
        client_id: str,
        client_name: str,
        title: str,
        period: str,
        report: dict[str, Any],
        detail: str = "",
    ) -> str:
        """Append a produced-report run (carries the downloadable ``report`` payload).

        Its presence is what surfaces the row in the Reports library. Returns the id."""
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.scheduled_job_runs "
                "(job_name, task, status, detail, client_id, client_name, title, period, report) "
                "values (%s, %s, 'ok', %s, %s, %s, %s, %s, %s) returning id",
                (job_name, task, detail, client_id, client_name, title, period, Jsonb(report)),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else ""


def _count(row: dict[str, Any] | None) -> int:
    """First ``n`` column of a count row as int (0 when absent)."""
    return int(row["n"]) if row and row.get("n") is not None else 0


def service_reports_store() -> ServiceReportsStore:
    """Build the privileged report-jobs store (for the beat workers)."""
    return ServiceReportsStore()
