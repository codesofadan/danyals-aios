"""Data access for ``design_irs`` / ``site_generation_jobs`` (migration 0069) via
the RLS-scoped ``rls_connection`` seam (the dashboard: create a job, list/poll jobs,
read a design) + the privileged ``ServiceSiteBuilderStore`` the analyze/generate/
render/publish worker tasks write through (no user JWT on the Celery process, so it
runs on ``service_role`` - BYPASSRLS - exactly like every other module's worker path).

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]
_JOB_COLS = (
    "client_id", "client_name", "status", "source_type", "source_url",
    "page_type", "industry", "editor_mode", "fidelity_mode", "created_by",
)
_DESIGN_IR_JSONB_COLS = frozenset(
    {"palette", "typography", "layout", "components", "responsive", "assets", "sections"}
)


def _bind_design_ir(field: str, value: Any) -> Any:
    return Jsonb(value) if field in _DESIGN_IR_JSONB_COLS else value


class SiteBuilderRepo:
    """Thin RLS-scoped repository over jobs + designs - the dashboard's read/create path."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def create_job(
        self,
        *,
        client_id: str | None,
        client_name: str,
        source_type: str,
        source_url: str,
        page_type: str,
        industry: str,
        editor_mode: str,
        fidelity_mode: str,
        created_by: str,
    ) -> dict[str, Any]:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.site_generation_jobs "
                "(client_id, client_name, status, source_type, source_url, "
                "page_type, industry, editor_mode, fidelity_mode, created_by) "
                "values (%s, %s, 'queued', %s, %s, %s, %s, %s, %s, %s) returning *",
                (
                    client_id, client_name, source_type, source_url,
                    page_type, industry, editor_mode, fidelity_mode, created_by,
                ),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - insert...returning always yields a row
                raise RuntimeError("site_generation_jobs insert returned no row")
            return row

    def list_jobs(
        self, *, client_id: str | None = None, status: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> _Rows:
        query = "select * from public.site_generation_jobs"
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
        query += " order by created_at desc, code"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_job_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.site_generation_jobs where code = %s limit 1", (code,))
            return cur.fetchone()

    def get_design_ir(self, design_ir_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.design_irs where id = %s limit 1", (design_ir_id,))
            return cur.fetchone()

    def list_templates(
        self, *, category: str | None = None, industry: str | None = None,
        page_type: str | None = None, active_only: bool = True,
    ) -> _Rows:
        query = "select * from public.site_templates"
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("is_active = true")
        if category is not None:
            clauses.append("category = %s")
            params.append(category)
        if industry is not None:
            clauses.append("industry in (%s, '')")
            params.append(industry)
        if page_type is not None:
            clauses.append("page_type = %s")
            params.append(page_type)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by name"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_template_by_key(self, key: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.site_templates where key = %s limit 1", (key,))
            return cur.fetchone()

    def list_visual_validations(self, job_id: str) -> _Rows:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.visual_validations where job_id = %s order by created_at desc",
                (job_id,),
            )
            return cur.fetchall()


def get_site_builder_repo(user: CurrentUserDep) -> SiteBuilderRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return SiteBuilderRepo(user.id)


SiteBuilderRepoDep = Annotated[SiteBuilderRepo, Depends(get_site_builder_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the pipeline worker tasks.
# --------------------------------------------------------------------------- #
class ServiceSiteBuilderStore:
    """Concrete store over ``privileged_connection`` for the analyze/generate/
    render/validate/publish worker tasks (no user JWT on the Celery process)."""

    def get_template_by_key(self, key: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.site_templates where key = %s limit 1", (key,))
            return cur.fetchone()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.site_generation_jobs where id = %s limit 1", (job_id,))
            return cur.fetchone()

    def get_design_ir(self, design_ir_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.design_irs where id = %s limit 1", (design_ir_id,))
            return cur.fetchone()

    def insert_visual_validation(
        self, *, job_id: str, rendered_url: str, status: str, diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.visual_validations (job_id, rendered_url, status, diagnostics) "
                "values (%s, %s, %s, %s) returning *",
                (job_id, rendered_url, status, Jsonb(diagnostics)),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - insert...returning always yields a row
                raise RuntimeError("visual_validations insert returned no row")
            return row

    def update_job(self, job_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Update arbitrary job columns (status/stage_detail/error/design_ir_id).
        Returns the updated row, or ``None`` if the job no longer exists (a
        redelivered task on an already-cleaned-up job is a safe no-op)."""
        if not fields:
            with privileged_connection() as cur:
                cur.execute("select * from public.site_generation_jobs where id = %s limit 1", (job_id,))
                return cur.fetchone()
        cols = list(fields.keys())
        set_clause = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in cols
        )
        query = sql.SQL("update public.site_generation_jobs set {} where id = %s returning *").format(set_clause)
        params = [*fields.values(), job_id]
        with privileged_connection() as cur:
            cur.execute(query, params)
            return cur.fetchone()

    def insert_design_ir(
        self, body: dict[str, Any], *, client_id: str | None, client_name: str, created_by: str | None,
    ) -> dict[str, Any]:
        fields = {
            "client_id": client_id,
            "client_name": client_name,
            "source_type": body.get("source_type", "manual"),
            "source_url": body.get("source_url", ""),
            "industry": body.get("industry", ""),
            "page_type": body.get("page_type", ""),
            "design_style": body.get("design_style", ""),
            "palette": body.get("palette", {}),
            "typography": body.get("typography", {}),
            "layout": body.get("layout", {}),
            "components": body.get("components", {}),
            "responsive": body.get("responsive", []),
            "assets": body.get("assets", []),
            "sections": body.get("sections", []),
            "supported_editors": body.get("supported_editors", ["elementor"]),
            "notes": body.get("notes", ""),
            "wireframe_html": body.get("wireframe_html", ""),
            "created_by": created_by,
        }
        cols = list(fields.keys())
        col_list = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in cols)
        query = sql.SQL("insert into public.design_irs ({}) values ({}) returning *").format(col_list, placeholders)
        values = [_bind_design_ir(c, fields[c]) for c in cols]
        with privileged_connection() as cur:
            cur.execute(query, values)
            row = cur.fetchone()
            if row is None:  # pragma: no cover - insert...returning always yields a row
                raise RuntimeError("design_irs insert returned no row")
            return row


def service_site_builder_store() -> ServiceSiteBuilderStore:
    return ServiceSiteBuilderStore()
