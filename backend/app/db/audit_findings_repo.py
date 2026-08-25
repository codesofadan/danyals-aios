"""Read the three altitude tables through the RLS-scoped seam.

Reads only. The altitude tables are written by the worker's ingest on the
service_role connection; nothing writes them through a user JWT, and their RLS
policies are staff-select. Methods are synchronous - routers offload them with
``asyncio.to_thread`` - matching ``AuditsRepo``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]

#: Instances are the nano grain and a single audit can hold tens of thousands, so
#: every instance read is paginated. A caller that wants them all takes the CSV.
_MAX_PAGE = 500


class AuditFindingsRepo:
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # ------------------------------------------------------------- MACRO
    def rollups(self, audit_id: str, *, level: str | None = None) -> _Rows:
        sql = "select * from public.audit_rollups where audit_id = %s"
        params: list[Any] = [audit_id]
        if level:
            sql += " and level = %s"
            params.append(level)
        sql += " order by level, key"
        with rls_connection(self._user_id) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # ------------------------------------------------------------- MICRO
    def findings(
        self,
        audit_id: str,
        *,
        dimension: str | None = None,
        pillar: str | None = None,
        subcategory: str | None = None,
        severity: str | None = None,
        check_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> _Rows:
        sql = "select * from public.audit_findings where audit_id = %s"
        params: list[Any] = [audit_id]
        for column, value in (
            ("dimension", dimension), ("pillar", pillar),
            ("subcategory", subcategory), ("severity", severity),
            ("check_id", check_id),
        ):
            if value:
                sql += f" and {column} = %s"
                params.append(value)
        # Worst first, then widest blast radius. Deterministic tail-break on
        # check_id so two calls never disagree about ordering.
        sql += (
            " order by case severity when 'critical' then 0 when 'major' then 1"
            "                        when 'minor' then 2 else 3 end,"
            " instance_count desc, check_id limit %s offset %s"
        )
        params += [min(max(limit, 1), _MAX_PAGE), max(offset, 0)]
        with rls_connection(self._user_id) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def finding_count(self, audit_id: str) -> int:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select count(*) as c from public.audit_findings where audit_id = %s",
                (audit_id,),
            )
            row = cur.fetchone()
            return int(row["c"]) if row else 0

    # -------------------------------------------------------------- NANO
    def instances(
        self,
        audit_id: str,
        *,
        finding_id: str | None = None,
        url: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> _Rows:
        sql = (
            "select i.*, f.check_id, f.check_name, f.severity as finding_severity,"
            "       f.pillar, f.subcategory, f.dimension, f.fingerprint"
            " from public.audit_finding_instances i"
            " join public.audit_findings f on f.id = i.finding_id"
            " where i.audit_id = %s"
        )
        params: list[Any] = [audit_id]
        if finding_id:
            sql += " and i.finding_id = %s"
            params.append(finding_id)
        if url:
            sql += " and i.url = %s"
            params.append(url)
        sql += " order by f.check_id, i.url, i.instance_key limit %s offset %s"
        params += [min(max(limit, 1), _MAX_PAGE), max(offset, 0)]
        with rls_connection(self._user_id) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def instance_count(self, audit_id: str, *, finding_id: str | None = None) -> int:
        sql = "select count(*) as c from public.audit_finding_instances where audit_id = %s"
        params: list[Any] = [audit_id]
        if finding_id:
            sql += " and finding_id = %s"
            params.append(finding_id)
        with rls_connection(self._user_id) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return int(row["c"]) if row else 0

    # ------------------------------------------------------------ ROADMAP
    def roadmap(self, audit_id: str) -> tuple[dict[str, Any] | None, _Rows]:
        """The ACTIVE roadmap and its items. Superseded plans stay readable by id
        but are never returned here - a client should see one current plan."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.audit_roadmaps"
                " where audit_id = %s and status = 'active'"
                " order by generated_at desc limit 1",
                (audit_id,),
            )
            roadmap = cur.fetchone()
            if roadmap is None:
                return None, []
            cur.execute(
                "select * from public.audit_roadmap_items where roadmap_id = %s"
                " order by case phase when 'p0_30d' then 0 when 'p1_90d' then 1"
                "                     when 'p2_180d' then 2 when 'p3_365d' then 3"
                "                     else 4 end, sequence",
                (roadmap["id"],),
            )
            return roadmap, cur.fetchall()

    # -------------------------------------------------------------- PAGES
    def pages(self, audit_id: str, *, limit: int = 200, offset: int = 0) -> _Rows:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.audit_pages where audit_id = %s"
                " order by issues_critical desc, issues_major desc, url"
                " limit %s offset %s",
                (audit_id, min(max(limit, 1), _MAX_PAGE), max(offset, 0)),
            )
            return cur.fetchall()


def get_audit_findings_repo(user: CurrentUserDep) -> AuditFindingsRepo:
    return AuditFindingsRepo(user.id)


AuditFindingsRepoDep = Annotated[AuditFindingsRepo, Depends(get_audit_findings_repo)]
