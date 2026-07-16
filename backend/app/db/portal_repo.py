"""Data access for the CLIENT PORTAL over the ``portal_*`` security-barrier views.

Every read opens ``rls_connection(self._user_id)`` for the client's verified user
id, so PostgreSQL RLS - via the views' ``current_client_id()`` self-filter - is
the boundary: a client can only ever see its OWN client, sites, and audits, and
only the safe column subset the views expose (no cost/error/paths/mrr/contacts).
The repo holds only the caller's user id; methods are synchronous (psycopg is
sync) and the router offloads them with ``asyncio.to_thread``. A single
``get_portal_repo`` dependency makes the layer trivially replaceable with an
in-memory fake in tests.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class PortalRepo:
    """Thin repository over the ``portal_audits`` / ``portal_client`` /
    ``portal_sites`` views (RLS-scoped to the calling client)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.portal_audits order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.portal_audits where id = %s limit 1", (audit_id,))
            return cur.fetchone()

    def get_client(self) -> dict[str, Any] | None:
        """The caller's own client row (the view returns exactly one row)."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.portal_client limit 1")
            return cur.fetchone()

    def list_sites(self) -> _Rows:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.portal_sites order by domain")
            return cur.fetchall()

    # --- Part 8: milestones / deliverables / requests / report grants --------
    # All read through the additional portal_* security-barrier views (0031-0034),
    # so RLS self-filters each to the caller's OWN tenant.

    def get_project(self) -> dict[str, Any] | None:
        """The caller's own project row (the view returns its single project)."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.portal_project limit 1")
            return cur.fetchone()

    def list_project_stages(self) -> _Rows:
        """The lifecycle stages of the caller's own project(s), in lifecycle order."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.portal_project_stages order by project_id, stage_key"
            )
            return cur.fetchall()

    def list_deliverables(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """The caller's granted, visible deliverables (newest issued first)."""
        query = (
            "select * from public.portal_deliverables "
            "order by issued_at desc nulls last, title"
        )
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_deliverable(self, deliverable_id: str) -> dict[str, Any] | None:
        """One deliverable by id IF it is the caller's own AND granted+visible.

        The view already gates visibility to a granted `requires` key, so a hit
        here proves the caller owns it and may download it (subject to status)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.portal_deliverables where id = %s limit 1",
                (deliverable_id,),
            )
            return cur.fetchone()

    def list_requests(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """The caller's own requests (newest first)."""
        query = "select * from public.portal_requests order by opened_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def granted_report_keys(self) -> list[str]:
        """The report keys the caller is granted (drives which vizzes are built)."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select report_key from public.portal_report_grants")
            return [str(r["report_key"]) for r in cur.fetchall()]


def get_portal_repo(user: CurrentUserDep) -> PortalRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped).

    Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return PortalRepo(user.id)


PortalRepoDep = Annotated[PortalRepo, Depends(get_portal_repo)]
