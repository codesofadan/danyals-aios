"""Data access for discussion threads via the RLS-scoped ``rls_connection``.

STAFF path only. Every read and write here runs as the caller on the
``authenticated`` role, so ``is_staff()`` in the 0098 policies resolves off the
caller's own ``auth.uid()`` and a portal client reaches nothing - the policies
default-deny them outright.

The CLIENT path is deliberately NOT in this class. It lives in
``app/services/portal_threads.py`` and reads the ``portal_thread_messages``
security-barrier view, which never selects an internal message. Keeping the two
paths in separate modules means a staff query cannot be reused for a client by
accident: there is no method here that a client route could call.

SQL rules (impersonation-review mandate): every VALUE is a bound param; the only
dynamic column list (insert) comes from a server-built dict and is quoted via
``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class ThreadsRepo:
    """Thin repository over ``threads`` + ``thread_messages`` (RLS-scoped, staff)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- threads --------------------------------------------------------------
    def get_thread(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.threads where entity_type = %s and entity_id = %s limit 1",
                (entity_type, entity_id),
            )
            return cur.fetchone()

    def create_thread(
        self, *, entity_type: str, entity_id: str, client_id: str | None
    ) -> dict[str, Any] | None:
        """Create the thread for an entity, or return the existing one.

        ``on conflict do nothing`` rather than a read-then-write: two people opening
        the same task at once would otherwise race on the unique constraint and one
        would see a 500 for pressing a button at the wrong moment.
        """
        row = {"entity_type": entity_type, "entity_id": entity_id, "client_id": client_id}
        cols = list(row)
        stmt = sql.SQL(
            "insert into public.threads ({cols}) values ({vals}) "
            "on conflict (entity_type, entity_id) do nothing returning *"
        ).format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [row[c] for c in cols])
            created = cur.fetchone()
            if created is not None:
                return created
            # Lost the race (or it already existed) - read the winner back.
            cur.execute(
                "select * from public.threads where entity_type = %s and entity_id = %s limit 1",
                (entity_type, entity_id),
            )
            return cur.fetchone()

    # --- messages -------------------------------------------------------------
    def list_messages(
        self, thread_id: str, *, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        """Oldest first - a conversation reads top to bottom."""
        query = (
            "select * from public.thread_messages where thread_id = %s order by created_at asc"
        )
        params: list[Any] = [thread_id]
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def add_message(
        self,
        *,
        thread_id: str,
        author_id: str,
        author_name: str,
        body: str,
        visibility: str,
    ) -> dict[str, Any] | None:
        row = {
            "thread_id": thread_id,
            "author_id": author_id,
            "author_name": author_name,
            "author_kind": "staff",  # this repo is the staff path, by construction
            "body": body,
            "visibility": visibility,
        }
        cols = list(row)
        stmt = sql.SQL(
            "insert into public.thread_messages ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [row[c] for c in cols])
            posted = cur.fetchone()
            # Keep the thread's updated_at meaningful: it orders "recently discussed".
            cur.execute(
                "update public.threads set updated_at = now() where id = %s", (thread_id,)
            )
            return posted

    def unread_counts(self, entity_type: str, entity_ids: list[str]) -> dict[str, int]:
        """Message count per entity, for badging a list without N queries."""
        if not entity_ids:
            return {}
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select t.entity_id, count(m.id) as n "
                "from public.threads t left join public.thread_messages m on m.thread_id = t.id "
                "where t.entity_type = %s and t.entity_id = any(%s) "
                "group by t.entity_id",
                (entity_type, entity_ids),
            )
            return {str(r["entity_id"]): int(r["n"]) for r in cur.fetchall()}


def get_threads_repo(user: CurrentUserDep) -> ThreadsRepo:
    return ThreadsRepo(user.id)


ThreadsRepoDep = Annotated[ThreadsRepo, Depends(get_threads_repo)]
