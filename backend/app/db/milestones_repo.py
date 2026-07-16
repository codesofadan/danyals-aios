"""Data access for the Milestones module (``client_projects`` + ``project_stages``)
via the RLS-scoped ``rls_connection`` seam.

Every read is tenant/actor-scoped by Postgres RLS: staff see the whole board,
clients are excluded (no base-table select policy - mirrors 0010/0011). Methods are
synchronous (psycopg is sync) - the router offloads them with ``asyncio.to_thread`` -
and the single ``get_milestones_repo`` dependency makes the layer trivially
replaceable with an in-memory fake in tests.

``advance_stage`` is the AUTO-ADVANCE write path the future event wiring calls: a
delivery event (audit done / content published / payment) advances one lifecycle
stage. On the authenticated pool RLS gates it to leads (owner/admin/manager); the
system/worker path runs on ``privileged_connection`` (BYPASSRLS) so an event can
advance a stage regardless. There is NO client-driven stage edit.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class MilestonesRepo:
    """Thin repository over the ``client_projects`` and ``project_stages`` tables."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_projects(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        query = "select * from public.client_projects order by created_at desc, id"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def list_stages(self, project_ids: list[str]) -> _Rows:
        """The stages for a set of projects, ordered by project then the lifecycle
        (stage_key enum) order. Returns ``[]`` for an empty id list (no query)."""
        if not project_ids:
            return []
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.project_stages "
                "where project_id::text = any(%s) order by project_id, stage_key",
                (project_ids,),
            )
            return cur.fetchall()

    def recent_advances(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        """The auto-advance feed: recently-touched stages (a stage that has left
        ``upcoming`` has been advanced or flagged) joined to their project's display
        snapshot, newest-touched first."""
        query = (
            "select s.id, s.stage_key, s.status, s.auto_source, s.updated_at, "
            "p.client_name, p.init, p.accent "
            "from public.project_stages s "
            "join public.client_projects p on p.id = s.project_id "
            "where s.status <> 'upcoming' "
            "order by s.updated_at desc, s.id"
        )
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def project_id_for_client(self, client_id: str) -> str | None:
        """The project timeline id for a client (RLS-scoped), or ``None`` when the
        client has no project yet / is invisible to the caller.

        The lookup an EVENT source needs: a delivery event knows which CLIENT it
        happened to, while ``advance_stage`` addresses a PROJECT. Newest project wins
        if a client was ever re-engaged, so an event advances the live timeline rather
        than a historical one.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id from public.client_projects where client_id = %s "
                "order by created_at desc, id limit 1",
                (client_id,),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else None

    def advance_stage(
        self,
        project_id: str,
        stage_key: str,
        *,
        status: str,
        auto_source: str | None = None,
    ) -> dict[str, Any] | None:
        """Auto-advance ONE lifecycle stage (the event-wiring write path): set the
        stage's ``status`` (+ an optional ``auto_source`` note); the set_updated_at
        trigger bumps ``updated_at`` so the feed surfaces it. Returns the updated row
        or ``None`` (unknown project/stage)."""
        changes: dict[str, Any] = {"status": status}
        if auto_source is not None:
            changes["auto_source"] = auto_source
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
        )
        stmt = sql.SQL(
            "update public.project_stages set {sets} "
            "where project_id = %s and stage_key = %s returning *"
        ).format(sets=assignments)
        params: list[Any] = [*changes.values(), project_id, stage_key]
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchone()


def get_milestones_repo(user: CurrentUserDep) -> MilestonesRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return MilestonesRepo(user.id)


MilestonesRepoDep = Annotated[MilestonesRepo, Depends(get_milestones_repo)]
