"""Staff-side reads and the publish decision for ``client_deliverables`` (0032/0116).

The PORTAL side of this table is a security-barrier view (``portal_deliverables``)
and lives in ``portal_repo``. This is the other side: staff see every deliverable
including the ones awaiting review, and a lead decides which of them a client gets.

Both run on ``rls_connection``. The base table's policies are the enforcement - a
viewer can read and only a lead can write - so a route that forgot its permission
check would still be refused by Postgres. An RLS refusal matches zero rows rather
than raising, which is why every mutation here returns the row and makes the caller
check it: a silent no-op reported to an operator as "published" is the failure this
whole effort exists to remove.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_ROW = (
    "id, client_id, title, kind, icon, period, issued_at, size_label, status, "
    "requires, artifact_key, media_type, source_kind, source_id, created_at"
)


class DeliverablesRepo:
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_for_client(self, client_id: str) -> list[dict[str, Any]]:
        """Every deliverable for one client, awaiting-review ones included.

        Ordered so the queue reads top-down: what needs a decision first, then what
        has been released, newest first within each.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                f"select {_ROW} from public.client_deliverables where client_id = %s "
                "order by (status = 'pending_review') desc, "
                "coalesce(issued_at, created_at) desc",
                (client_id,),
            )
            return cur.fetchall()

    def set_status(self, deliverable_id: str, *, status: str) -> dict[str, Any] | None:
        """Release a deliverable to the client, or pull it back for review.

        ``issued_at`` is stamped on release and cleared on withdrawal, so the date a
        client sees is when they were GIVEN the document, not when it was produced -
        and a document pulled back and re-released is not still claiming its first
        date.

        Returns None when RLS matched no row (a non-lead, or another tenant's id).
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.client_deliverables "
                "set status = %s::public.deliverable_status, "
                "    issued_at = case when %s = 'ready' then coalesce(issued_at, now()) "
                "                else null end "
                f"where id = %s returning {_ROW}",
                (status, status, deliverable_id),
            )
            return cur.fetchone()

    def get(self, deliverable_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                f"select {_ROW} from public.client_deliverables where id = %s", (deliverable_id,)
            )
            return cur.fetchone()


def get_deliverables_repo(user: CurrentUserDep) -> DeliverablesRepo:
    return DeliverablesRepo(user.id)


DeliverablesRepoDep = Annotated[DeliverablesRepo, Depends(get_deliverables_repo)]

__all__ = ["DeliverablesRepo", "DeliverablesRepoDep", "get_deliverables_repo"]
