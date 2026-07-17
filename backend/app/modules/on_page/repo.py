"""Data access for the on-page optimizer (``onpage_analyses`` /
``page_recommendations``) via the RLS-scoped ``rls_connection`` seam + the privileged
``ServiceOnPageStore`` the analysis worker ingests through.

Every read + mutation on ``OnPageRepo`` is tenant/actor-scoped by Postgres RLS: staff
read, and only leads (owner/admin/manager) may write a recommendation. Methods are
synchronous (psycopg is sync) - the router offloads them with ``asyncio.to_thread``.

WHY THE APPLY PATH USES THE **RLS** REPO, NOT THE PRIVILEGED STORE. Applying a fix
REWRITES A LIVE CLIENT PAGE. The ``onpage_guard_update`` trigger (migration 0038)
forbids the worker (``service_role``, ``auth.uid() IS NULL``) from driving a
recommendation's lifecycle at all: a live-site write must be attributable to a human
lead. So ``apply``/``revert``/``dismiss`` run through :class:`OnPageRepo` carrying the
acting lead's identity, and the database itself enforces that. The privileged store
below is for the ANALYSIS worker only (which the trigger does recognise, for the
analysis lifecycle + the recommendation INSERTs).

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``), never
string-formatted; table/column names are static literals and the only dynamic column
lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# jsonb columns on these tables (values are wrapped for their jsonb column).
_JSONB_COLS: frozenset[str] = frozenset({"fix_payload", "detail", "score"})

# The recommendation read projection: the base row + the parent analysis's PUBLIC
# code / status / target keyword (so a response can name its analysis without a
# second round-trip, and WITHOUT ever surfacing the analysis UUID). A static set.
_REC_SELECT = (
    "select r.*, a.code as analysis_code, a.status as analysis_status, "
    "a.target_keyword, a.wp_post_id, a.client_name "
    "from public.page_recommendations r "
    "join public.onpage_analyses a on a.id = r.analysis_id"
)

# The analysis read projection + its live recommendation tallies (the board's
# per-page counters). Correlated subqueries keep it one round-trip and RLS-safe.
_ANALYSIS_SELECT = (
    "select a.*, "
    "(select count(*) from public.page_recommendations r "
    " where r.analysis_id = a.id and r.status = 'open') as open_count, "
    "(select count(*) from public.page_recommendations r "
    " where r.analysis_id = a.id and r.status = 'applied') as applied_count "
    "from public.onpage_analyses a"
)


def _bind(col: str, value: Any) -> Any:
    """Wrap a jsonb-column value (or any dict/list) for psycopg; pass scalars."""
    if col in _JSONB_COLS or isinstance(value, (dict, list)):
        return Jsonb(value)
    return value


class OnPageRepo:
    """Thin RLS-scoped repository over the analyses + their recommendations."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- reads ----------------------------------------------------------------
    def list_recommendations(
        self,
        *,
        client_id: str | None = None,
        analysis_code: str | None = None,
        status: str | None = None,
        impact: str | None = None,
        issue_code: str | None = None,
        quick_win: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = _REC_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("r.client_id = %s")
            params.append(client_id)
        if analysis_code is not None:
            clauses.append("a.code = %s")
            params.append(analysis_code)
        if status is not None:
            clauses.append("r.status = %s")
            params.append(status)
        if impact is not None:
            clauses.append("r.impact = %s")
            params.append(impact)
        if issue_code is not None:
            clauses.append("r.issue_code = %s")
            params.append(issue_code)
        if quick_win is not None:
            clauses.append("r.quick_win = %s")
            params.append(quick_win)
        if clauses:
            query += " where " + " and ".join(clauses)
        # Best wins first; created_at + id keep the order stable across ties.
        query += " order by r.priority_score desc, r.created_at desc, r.id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_REC_SELECT + " where r.id = %s limit 1", (rec_id,))
            return cur.fetchone()

    def list_analyses(
        self,
        *,
        client_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = _ANALYSIS_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("a.client_id = %s")
            params.append(client_id)
        if status is not None:
            clauses.append("a.status = %s")
            params.append(status)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by a.created_at desc, a.code"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_analysis_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_ANALYSIS_SELECT + " where a.code = %s limit 1", (code,))
            return cur.fetchone()

    def stats(self) -> dict[str, Any]:
        """Board summary: pages analysed, open suggestions, applied. RLS-scoped; an
        empty board yields zeros."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select count(*) as analyzed from public.onpage_analyses")
            analyzed = cur.fetchone() or {"analyzed": 0}
            cur.execute(
                "select "
                "count(*) filter (where status = 'open') as open, "
                "count(*) filter (where status = 'applied') as applied "
                "from public.page_recommendations"
            )
            recs = cur.fetchone() or {"open": 0, "applied": 0}
        return {
            "analyzed": analyzed.get("analyzed", 0),
            "open": recs.get("open", 0),
            "applied": recs.get("applied", 0),
        }

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None``
        - used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def site_url_for(self, site_id: str) -> str | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select domain from public.sites where id = %s limit 1", (site_id,))
            row = cur.fetchone()
            return str(row["domain"]) if row else None

    # --- mutations ------------------------------------------------------------
    def create_analysis(
        self,
        *,
        client_id: str,
        client_name: str,
        site_id: str | None,
        page_url: str,
        target_keyword: str,
        source_audit_id: str | None,
        created_by: str,
    ) -> dict[str, Any] | None:
        """Insert a queued analysis; returns the row (with its minted OP-#### code)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.onpage_analyses "
                "(client_id, client_name, site_id, page_url, target_keyword, "
                "source_audit_id, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s) returning *",
                (client_id, client_name, site_id, page_url, target_keyword,
                 source_audit_id, created_by),
            )
            return cur.fetchone()

    def update_analysis(
        self, code: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        """Update one analysis by code, returning the row (or ``None``).

        When ``expect_status`` is given the update is additionally gated on the
        current status (optimistic concurrency): a racing transition that already
        moved the row matches 0 rows, so the caller can raise 409 instead of silently
        double-advancing. The DB trigger remains the real transition gate.
        """
        if not changes:
            return self.get_analysis_by_code(code)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
        )
        where = sql.SQL("code = %s")
        params: list[Any] = [*(_bind(c, v) for c, v in changes.items()), code]
        if expect_status is not None:
            where = sql.SQL("code = %s and status = %s")
            params.append(expect_status)
        stmt = sql.SQL(
            "update public.onpage_analyses set {sets} where {where} returning id"
        ).format(sets=assignments, where=where)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            if cur.fetchone() is None:
                return None
        return self.get_analysis_by_code(code)

    def update_recommendation(
        self, rec_id: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        """Update one recommendation by id, returning the JOINED row (or ``None``).

        Runs on the RLS connection carrying the acting LEAD's identity - which is what
        lets the 0038 guard trigger allow the transition at all (see the module
        docstring). ``expect_status`` is the same optimistic-concurrency gate as
        above: it is what makes a double-apply a 409 rather than a second live write.
        """
        if not changes:
            return self.get_recommendation(rec_id)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
        )
        where = sql.SQL("id = %s")
        params: list[Any] = [*(_bind(c, v) for c, v in changes.items()), rec_id]
        if expect_status is not None:
            where = sql.SQL("id = %s and status = %s")
            params.append(expect_status)
        stmt = sql.SQL(
            "update public.page_recommendations set {sets} where {where} returning id"
        ).format(sets=assignments, where=where)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            if cur.fetchone() is None:
                return None
        return self.get_recommendation(rec_id)


def get_on_page_repo(user: CurrentUserDep) -> OnPageRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return OnPageRepo(user.id)


OnPageRepoDep = Annotated[OnPageRepo, Depends(get_on_page_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the ANALYSIS worker.
# --------------------------------------------------------------------------- #
# The analysis worker has no user JWT, so - exactly like the audit / context /
# keyword-research workers - it reads/writes on the privileged connection
# (service_role bypasses the RLS policies by design, but NOT the 0038 guard trigger,
# which still holds it to queued -> analyzing -> done|held|failed and forbids it from
# ever driving a recommendation's lifecycle). Each method opens its own privileged
# connection, so the store is stateless and safe to instantiate per call.
class ServiceOnPageStore:
    """Concrete on-page store over ``privileged_connection`` (BYPASSRLS)."""

    def load_analysis(self, code: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.onpage_analyses where code = %s limit 1", (code,))
            return cur.fetchone()

    def update_analysis(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        if not fields:
            return self.load_analysis(code)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in fields
        )
        stmt = sql.SQL(
            "update public.onpage_analyses set {sets} where code = %s returning *"
        ).format(sets=assignments)
        params = [_bind(c, v) for c, v in fields.items()]
        with privileged_connection() as cur:
            cur.execute(stmt, [*params, code])
            return cur.fetchone()

    def clear_open_recommendations(self, analysis_id: str) -> int:
        """Drop this analysis's still-OPEN recommendations before a re-analysis.

        Only ``open`` rows: applied / dismissed / reverted ones are the RECORD of
        what a human decided about this page, and a re-run must never erase that.
        """
        with privileged_connection() as cur:
            cur.execute(
                "delete from public.page_recommendations "
                "where analysis_id = %s and status = 'open'",
                (analysis_id,),
            )
            return cur.rowcount

    def insert_recommendations(
        self, analysis_id: str, rows: list[dict[str, Any]]
    ) -> int:
        """Bulk-insert this analysis's recommendations. Returns the row count."""
        if not rows:
            return 0
        inserted = 0
        with privileged_connection() as cur:
            for row in rows:
                cur.execute(
                    "insert into public.page_recommendations "
                    "(analysis_id, client_id, site_id, page_url, issue, issue_code, "
                    "impact, fix_kind, fix_payload, current_value, priority_score, "
                    "quick_win, detail) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        analysis_id, row["client_id"], row.get("site_id"), row["page_url"],
                        row["issue"], row["issue_code"], row["impact"], row["fix_kind"],
                        Jsonb(row.get("fix_payload") or {}), row.get("current_value"),
                        row["priority_score"], row["quick_win"],
                        Jsonb(row.get("detail") or {}),
                    ),
                )
                inserted += 1
        return inserted

    def audit_json_path(self, audit_id: str) -> str | None:
        """The stored ``findings.json`` key of an audit run (or ``None``)."""
        with privileged_connection() as cur:
            cur.execute(
                "select json_path from public.audits where id = %s limit 1", (audit_id,)
            )
            row = cur.fetchone()
            return str(row["json_path"]) if row and row.get("json_path") else None


def service_on_page_store() -> ServiceOnPageStore:
    """The privileged store the analysis worker uses (service_role, BYPASSRLS)."""
    return ServiceOnPageStore()
