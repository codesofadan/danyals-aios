"""Integration: a client must NEVER read an internal message. Proven at the DB.

Skips unless DATABASE_URL + DATABASE_ADMIN_URL are set (migration 0098 applied).

WHY THIS IS THE DECISIVE TEST FOR THE FEATURE. A discussion thread on a client's
request is read by two audiences at once: the agency talking to itself, and the agency
talking to the client, on the same thread. ``thread_messages.visibility`` is the only
thing separating them. If it fails, the product does not merely lose a feature - it
shows a client the agency's internal discussion OF that client.

So the assertion is made the same way the tenant boundary is: against the
``authenticated`` role with the client's identity bound, i.e. exactly what a LEAKED
PORTAL CREDENTIAL would get. Not through FastAPI, which could be bypassed; not through
the response model, which could be widened. If RLS and the security-barrier views did
not hold, this test would see the internal note.

It also proves the append-only guarantee against ``privileged_connection`` - the
BYPASSRLS principal that policies cannot constrain, and the reason that guarantee is a
TRIGGER rather than an absent policy (the lesson ``activity_log`` taught).
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    rls_connection,
    set_pools,
)

pytestmark = pytest.mark.integration

_INTERNAL = "INTERNAL: account is 60 days overdue - do not start new work"
_TO_CLIENT = "Thanks - we have picked this up and will report on Friday."


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


async def test_a_client_can_never_read_an_internal_message() -> None:
    settings = _require_local_stack()

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    def _probe(uid: str, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """SELECT as role ``authenticated`` with ``uid`` bound - a leaked credential."""
        with rls_connection(uid, pool=rls_pool) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    client_a = client_b = None
    uids: list[str] = []
    try:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute("insert into public.clients (name) values ('Thread A') returning id")
            client_a = str(cur.fetchone()["id"])
            cur.execute("insert into public.clients (name) values ('Thread B') returning id")
            client_b = str(cur.fetchone()["id"])

            def _user(email: str, role: str, cid: str | None) -> str:
                uid = uuid4()
                cur.execute(
                    "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                    (uid, email),
                )
                cur.execute(
                    "insert into public.users (id, email, name, role, client_id) "
                    "values (%s, %s, %s, %s, %s)",
                    (uid, email, email.split("@")[0], role, cid),
                )
                uids.append(str(uid))
                return str(uid)

            ua = _user(f"a-{uuid4().hex[:8]}@x.com", "client", client_a)
            ub = _user(f"b-{uuid4().hex[:8]}@x.com", "client", client_b)
            us = _user(f"s-{uuid4().hex[:8]}@x.com", "admin", None)

            # Tenant A raises a request; the agency leaves one internal note and one
            # reply addressed to the client, on the SAME thread.
            cur.execute(
                "insert into public.support_tickets (client_id, client_name, subject, kind) "
                "values (%s, 'Thread A', 'Please refresh the audit', 'Report') returning id, code",
                (client_a,),
            )
            ticket = cur.fetchone()
            ticket_id, ticket_code = str(ticket["id"]), str(ticket["code"])

            cur.execute(
                "insert into public.threads (entity_type, entity_id, client_id) "
                "values ('ticket', %s, %s) returning id",
                (ticket_id, client_a),
            )
            thread_id = str(cur.fetchone()["id"])
            cur.execute(
                "insert into public.thread_messages "
                "(thread_id, author_name, author_kind, body, visibility) values "
                "(%s, 'Staff', 'staff', %s, 'internal'), "
                "(%s, 'Staff', 'staff', %s, 'client_visible')",
                (thread_id, _INTERNAL, thread_id, _TO_CLIENT),
            )

            # A TASK thread that also carries tenant A - the view must refuse it on
            # entity_type alone, so a mis-set client_id cannot leak internal work chat.
            cur.execute(
                "insert into public.threads (entity_type, entity_id, client_id) "
                "values ('task', %s, %s) returning id",
                (uuid4(), client_a),
            )
            task_thread = str(cur.fetchone()["id"])
            cur.execute(
                "insert into public.thread_messages "
                "(thread_id, author_name, author_kind, body, visibility) "
                "values (%s, 'Staff', 'staff', 'task chatter', 'client_visible')",
                (task_thread,),
            )

        # --- (a) the client's own view shows the reply and NOT the internal note ---
        visible = _probe(ua, "select body from public.portal_thread_messages")
        bodies = [r["body"] for r in visible]
        assert _TO_CLIENT in bodies
        assert _INTERNAL not in bodies, "a client read an INTERNAL message"
        assert not any("INTERNAL" in b for b in bodies)

        # --- (b) the base tables are unreachable for a client entirely --------------
        assert _probe(ua, "select id from public.thread_messages") == []
        assert _probe(ua, "select id from public.threads") == []

        # --- (c) a crafted predicate cannot probe past the barrier ------------------
        # security_barrier=true means the tenant + visibility filters run FIRST, so a
        # user-supplied WHERE cannot be used to test for rows the view excluded.
        probed = _probe(
            ua,
            "select body from public.portal_thread_messages where body like %s",
            ("%INTERNAL%",),
        )
        assert probed == [], "the internal note was reachable through a crafted filter"

        # --- (d) the task thread is not client-readable, despite carrying client_a --
        assert _probe(ua, "select id from public.portal_threads where entity_type = 'task'") == []
        assert "task chatter" not in [r["body"] for r in _probe(
            ua, "select body from public.portal_thread_messages"
        )]

        # --- (e) cross-tenant: B sees nothing of A's conversation -------------------
        assert _probe(ub, "select id from public.portal_thread_messages") == []
        assert _probe(ub, "select id from public.portal_threads") == []

        # --- (f) staff read the WHOLE conversation, internal note included ----------
        staff_bodies = [
            r["body"]
            for r in _probe(us, "select body from public.thread_messages where thread_id = %s", (thread_id,))
        ]
        assert _INTERNAL in staff_bodies and _TO_CLIENT in staff_bodies

        # --- (g) append-only binds the BYPASSRLS principal too ----------------------
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "select id from public.thread_messages where thread_id = %s and visibility = 'internal'",
                (thread_id,),
            )
            internal_id = str(cur.fetchone()["id"])

        for label, stmt, args in (
            ("edit a body", "update public.thread_messages set body = 'rewritten' where id = %s", (internal_id,)),
            (
                "flip internal -> client_visible",
                "update public.thread_messages set visibility = 'client_visible' where id = %s",
                (internal_id,),
            ),
            ("delete a message", "delete from public.thread_messages where id = %s", (internal_id,)),
        ):
            with (
                pytest.raises(Exception, match="append-only"),
                privileged_connection(pool=admin_pool) as cur,
            ):
                cur.execute(stmt, args)
            assert True, label

        # --- (h) a client-authored message can never be internal --------------------
        with (
            pytest.raises(Exception, match="thread_messages_client_is_visible_ck"),
            privileged_connection(pool=admin_pool) as cur,
        ):
            cur.execute(
                "insert into public.thread_messages "
                "(thread_id, author_name, author_kind, body, visibility) "
                "values (%s, 'A', 'client', 'sneaky', 'internal')",
                (thread_id,),
            )

        # --- (i) the client's own append still works and stays visible --------------
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "insert into public.thread_messages "
                "(thread_id, author_name, author_kind, body, visibility) "
                "values (%s, 'Thread A', 'client', 'Any update?', 'client_visible')",
                (thread_id,),
            )
        assert "Any update?" in [
            r["body"] for r in _probe(ua, "select body from public.portal_thread_messages")
        ]
        assert ticket_code  # the public code the API addresses this by

    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            # thread_messages cascades from threads; the guard blocks a direct
            # DELETE on a message but not on its parent thread.
            for cid in (client_a, client_b):
                if cid:
                    cur.execute("delete from public.threads where client_id = %s", (cid,))
                    cur.execute("delete from public.support_tickets where client_id = %s", (cid,))
            for uid in uids:
                cur.execute("delete from public.users where id = %s", (uid,))
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in (client_a, client_b):
                if cid:
                    cur.execute("delete from public.clients where id = %s", (cid,))
        clear_pools()
        with contextlib.suppress(Exception):
            rls_pool.close()
            admin_pool.close()
