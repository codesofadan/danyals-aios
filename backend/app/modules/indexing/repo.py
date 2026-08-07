"""Data access for the ``index_submissions`` ledger (``0061``).

Two seams, mirroring ``site_analytics``:

* ``IndexingRepo`` (RLS-scoped ``rls_connection``) - the staff READ surface the
  ``GET /indexing/submissions`` endpoint uses; the ``0061`` select policy is
  ``is_staff()`` so staff read the whole surface + clients are excluded.
* ``ServiceIndexingStore`` (privileged ``privileged_connection``, BYPASSRLS) - the
  APPEND surface the publish worker + the on-demand endpoint write through. Rows are
  server-written only (no authenticated INSERT policy), exactly like
  ``scheduled_job_runs`` / ``public_audits``.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``), never
string-formatted; table/column names are static literals.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]


def _is_uuid(value: str) -> bool:
    """Whether ``value`` is a syntactically valid UUID (``client_id`` is a uuid column,
    so a malformed filter must resolve to empty, not an InvalidTextRepresentation 500)."""
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


class IndexingRepo:
    """RLS-scoped read over ``index_submissions`` (staff-only, per the 0061 policy)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_submissions(self, *, client_id: str | None = None, limit: int = 100) -> _Rows:
        if client_id is not None and not _is_uuid(client_id):
            return []
        query = "select * from public.index_submissions"
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        query += " order by created_at desc limit %s"
        params.append(limit)
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def get_indexing_repo(user: CurrentUserDep) -> IndexingRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return IndexingRepo(user.id)


IndexingRepoDep = Annotated[IndexingRepo, Depends(get_indexing_repo)]


class ServiceIndexingStore:
    """Privileged (service_role, BYPASSRLS) APPEND store the endpoint + worker write
    through - rows are server-written only, like ``ServiceSiteAnalyticsStore``."""

    def record(
        self, *, client_id: str | None, url: str, engine: str, status: str, detail: str
    ) -> dict[str, Any]:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.index_submissions "
                "(client_id, url, engine, status, detail) values (%s, %s, %s, %s, %s) "
                "returning *",
                (client_id, url, engine, status, detail),
            )
            row = cur.fetchone()
        assert row is not None  # an insert always returns its own row
        return row


def service_indexing_store() -> ServiceIndexingStore:
    """The privileged store the endpoint + publish worker use (service_role)."""
    return ServiceIndexingStore()
