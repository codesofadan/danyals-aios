"""Admin data access for the per-client report grants (``client_report_grants``,
0031) via the RLS-scoped ``rls_connection`` seam.

Reads are visible to any staff (the table's ``select`` policy is ``is_staff()``);
the replace-set write (``replace_keys``) runs the delete-all-for-client + bulk
insert, which the ``insert``/``delete`` policies gate to the leads (owner/admin/
manager). The whole replace runs inside the single ``rls_connection`` transaction,
so it is atomic - a client never briefly loses all its grants. Methods are
synchronous (psycopg is sync); the router offloads them with ``asyncio.to_thread``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection


class ReportGrantsRepo:
    """Thin repository over ``client_report_grants`` (RLS-scoped to the actor)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_keys(self, client_id: str) -> list[str]:
        """The report keys granted to ``client_id`` (sorted for a stable response)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select report_key from public.client_report_grants "
                "where client_id = %s order by report_key",
                (client_id,),
            )
            return [str(r["report_key"]) for r in cur.fetchall()]

    def replace_keys(self, client_id: str, keys: list[str]) -> list[str]:
        """Replace the whole grant set for ``client_id`` (delete-all + bulk insert),
        atomically in one transaction. ``granted_by`` snapshots the acting user.
        Duplicate keys collapse; returns the persisted set (sorted)."""
        unique = sorted({str(k) for k in keys})
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "delete from public.client_report_grants where client_id = %s",
                (client_id,),
            )
            if unique:
                cur.executemany(
                    "insert into public.client_report_grants "
                    "(client_id, report_key, granted_by) values (%s, %s, %s)",
                    [(client_id, key, self._user_id) for key in unique],
                )
        return unique


def get_report_grants_repo(user: CurrentUserDep) -> ReportGrantsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return ReportGrantsRepo(user.id)


ReportGrantsRepoDep = Annotated[ReportGrantsRepo, Depends(get_report_grants_repo)]
