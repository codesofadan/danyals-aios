"""The CLIENT half of a discussion thread (0098).

Kept in its own module, separate from ``app/db/threads_repo.py``, on purpose: the
staff repo has no method a client route could call, and this module has no method
that can read an internal note. The separation is structural, not a convention - it
means the boundary cannot be crossed by reaching for the wrong helper.

READS go through ``portal_thread_messages``, the security-barrier view from 0098. The
view filters ``client_id = current_client_id()``, ``entity_type = 'ticket'`` and
``visibility = 'client_visible'`` BEFORE any user-supplied predicate, so an internal
note is not merely hidden from the response shape - it is never selected.

WRITES run on the privileged pool, exactly as ``create_client_request`` does: a
portal client holds no insert policy on ``thread_messages`` (0098 gives them none by
design, per 0010's doctrine). Everything that decides trust is pinned server-side:

* the thread is looked up BY the caller's own tenant, so a client cannot post into
  another tenant's conversation by passing its code;
* ``author_kind`` is ``'client'`` and ``visibility`` is ``'client_visible'`` - both
  literals here, neither taken from the request body. The database refuses the
  combination that would matter anyway
  (``thread_messages_client_is_visible_ck``), so bypassing this module buys nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.auth import CurrentClient
from app.db.database import privileged_connection, rls_connection
from app.logging_setup import get_logger

logger = get_logger("app.portal_threads")



def list_own_messages(*, user_id: str, code: str) -> list[dict[str, Any]] | None:
    """Messages the client may read on their own request.

    ``None`` when the code is not theirs (or does not exist) - the caller turns that
    into a 404, so the two are indistinguishable from outside.

    Both reads are RLS-scoped and go through the client's own views. Ownership is
    established by ``portal_requests`` before anything else runs; the messages then
    come from ``portal_thread_messages``, which applies the tenant AND visibility
    filters itself. Two independent gates, either of which alone would be enough.
    """
    ticket_id = _own_ticket_id(user_id, code)
    if ticket_id is None:
        return None
    with rls_connection(user_id) as cur:
        cur.execute(
            "select m.* from public.portal_thread_messages m "
            "join public.portal_threads t on t.id = m.thread_id "
            "where t.entity_id = %s order by m.created_at asc",
            (ticket_id,),
        )
        return list(cur.fetchall())


def _ensure_thread(client_id: str, ticket_id: str) -> str:
    """Get-or-create the thread for a ticket, on the privileged pool."""
    with privileged_connection() as cur:
        cur.execute(
            "insert into public.threads (entity_type, entity_id, client_id) "
            "values ('ticket', %s, %s) on conflict (entity_type, entity_id) do nothing "
            "returning id",
            (ticket_id, client_id),
        )
        row = cur.fetchone()
        if row is not None:
            return str(row["id"])
        cur.execute(
            "select id from public.threads where entity_type = 'ticket' and entity_id = %s",
            (ticket_id,),
        )
        existing = cur.fetchone()
        if existing is None:  # pragma: no cover - the insert above just ran
            raise RuntimeError("thread could not be created or read back")
        return str(existing["id"])


async def post_client_message(
    *, scoped: CurrentClient, code: str, body: str, author_name: str
) -> dict[str, Any] | None:
    """Append the client's message to their own request thread.

    Returns the persisted row, or ``None`` when the code is not the caller's.
    """
    ticket = await asyncio.to_thread(_own_ticket_id, scoped.user.id, code)
    if ticket is None:
        return None

    def _write() -> dict[str, Any]:
        thread_id = _ensure_thread(scoped.client_id, ticket)
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.thread_messages "
                "(thread_id, author_id, author_name, author_kind, body, visibility) "
                # author_kind and visibility are LITERALS. A client cannot file an
                # internal note, and cannot be recorded as staff.
                "values (%s, %s, %s, 'client', %s, 'client_visible') returning *",
                (thread_id, scoped.user.id, author_name, body),
            )
            posted = cur.fetchone()
            cur.execute("update public.threads set updated_at = now() where id = %s", (thread_id,))
            if posted is None:  # pragma: no cover - ``returning *`` always yields
                raise RuntimeError("message could not be read back after insert")
            return dict(posted)

    return await asyncio.to_thread(_write)


def _own_ticket_id(user_id: str, code: str) -> str | None:
    """The uuid of a request that belongs to the caller, else None.

    Scoped through ``portal_requests`` (the client's own view) FIRST, so the
    ``support_tickets`` lookup can only ever resolve a code the caller already owns.
    """
    with rls_connection(user_id) as cur:
        cur.execute("select code from public.portal_requests where code = %s limit 1", (code,))
        if cur.fetchone() is None:
            return None
    with privileged_connection() as cur:
        cur.execute("select id from public.support_tickets where code = %s limit 1", (code,))
        row = cur.fetchone()
        return str(row["id"]) if row else None
