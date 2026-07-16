"""Integration: prove the Part-5 task lifecycle + the DB-enforced review gate
against LOCAL Postgres (RLS + the tasks_guard_update trigger are the boundary,
not FastAPI).

Skips unless DATABASE_URL + DATABASE_ADMIN_URL are set (migration 0011 applied).
Provisions a lead (manager), a non-lead assignee (specialist), and a portal
client, then asserts - via each principal's OWN identity on the ``authenticated``
role hitting the tables DIRECTLY (a leaked portal/staff DB credential; RLS +
triggers are the only boundary), reproduced by ``rls_connection(uid)``:

  (A) THE BLOCKER PROOF: a non-lead status -> done directly is REJECTED by the
      trigger (both the skip-review jump on a content_sprint and the review ->
      done self-sign-off), the row is unchanged, and a non-status column edit is
      likewise REJECTED - while a lead CAN sign off review -> done;
  (B) a non-lead may make only the LEGAL moves (todo->in_progress,
      in_progress->review for content_sprint, in_progress->done otherwise);
  (C) a lead may reject review -> in_progress;
  (D) an assignee must be staff (reassigning to a client uid is REJECTED);
  (E) my-queue scoping works and a portal client is fully excluded (0 rows on
      read; insert/update blocked).

Everything created is cleaned up in a finally block.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    rls_connection,
    set_pools,
)
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration

_PASSWORD = "Passw0rd!tasks-flow-123"


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


async def test_task_lifecycle_and_db_review_gate() -> None:
    _require_local_stack()
    settings = get_settings()

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    codes: list[str] = []
    client_id: str | None = None
    uids: list[str] = []

    def _seed(**over: Any) -> str:
        row = {
            "client_id": client_id, "client_name": "Flow Co", "title": "Flow task",
            "type": "content_sprint", "assignee_id": None, "status": "todo", "priority": "med",
        }
        row.update(over)
        cols = list(row)
        stmt = sql.SQL("insert into public.tasks ({}) values ({}) returning code").format(
            sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        )
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(stmt, [row[c] for c in cols])
            code = str(cur.fetchone()["code"])
        codes.append(code)
        return code

    def _row(code: str) -> dict[str, Any]:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute("select * from public.tasks where code = %s", (code,))
            return cur.fetchone()

    def _update(uid: str, code: str, changes: dict[str, Any]) -> int:
        """UPDATE as role ``authenticated`` with ``uid`` bound. Returns rowcount."""
        cols = list(changes)
        sets = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder()) for c in cols
        )
        stmt = sql.SQL("update public.tasks set {} where code = {}").format(sets, sql.Placeholder())
        with rls_connection(uid, pool=rls_pool) as cur:
            cur.execute(stmt, [*(changes[c] for c in cols), code])
            return cur.rowcount

    try:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "insert into public.clients (name, delivery_tier) values ('Flow Co', 'free') returning id"
            )
            client_id = str(cur.fetchone()["id"])

        tag = uuid4().hex[:8]
        lead_uid = str(provision_user(
            email=f"flow-lead-{tag}@example.com", password=_PASSWORD, name="Flow Lead",
            role="manager", username=f"flow_lead_{tag}",
        )["id"])
        spec_uid = str(provision_user(
            email=f"flow-spec-{tag}@example.com", password=_PASSWORD, name="Flow Spec",
            role="specialist", username=f"flow_spec_{tag}",
        )["id"])
        cli_uid = str(provision_user(
            email=f"flow-cli-{tag}@example.com", password=_PASSWORD, name="Flow Client",
            role="client", username=f"flow_cli_{tag}", client_id=client_id,
        )["id"])
        uids += [lead_uid, spec_uid, cli_uid]

        # ============================================================= (A) BLOCKER
        # A content_sprint assigned to the specialist, sitting in_progress.
        t1 = _seed(type="content_sprint", status="in_progress", assignee_id=spec_uid)

        # (A1) the specialist tries to SKIP REVIEW by jumping straight to done.
        with pytest.raises(psycopg.Error):
            _update(spec_uid, t1, {"status": "done"})
        assert _row(t1)["status"] == "in_progress"  # the row never moved.

        # (A2) the specialist tries to edit a NON-status column on their own task.
        with pytest.raises(psycopg.Error):
            _update(spec_uid, t1, {"title": "hijacked"})
        assert _row(t1)["title"] != "hijacked"

        # (A2b) ...nor the normally-immutable created_at, even alongside a no-op
        # status (0012 hardened the column-lock to include id + created_at).
        original_created = _row(t1)["created_at"]
        with pytest.raises(psycopg.Error):
            _update(spec_uid, t1, {"status": "in_progress", "created_at": "2000-01-01T00:00:00+00:00"})
        assert _row(t1)["created_at"] == original_created

        # (A3) the LEGAL submit-for-review move (in_progress -> review) is allowed.
        assert _update(spec_uid, t1, {"status": "review"}) == 1
        assert _row(t1)["status"] == "review"

        # (A4) now in review, the specialist tries to self-sign-off review -> done.
        with pytest.raises(psycopg.Error):
            _update(spec_uid, t1, {"status": "done"})
        assert _row(t1)["status"] == "review"

        # (A5) ...and tries to self-reject review -> in_progress. Also lead-only.
        with pytest.raises(psycopg.Error):
            _update(spec_uid, t1, {"status": "in_progress"})
        assert _row(t1)["status"] == "review"

        # (A6) the LEAD signs off: review -> done succeeds (the gate is lead-only).
        assert _update(lead_uid, t1, {"status": "done"}) == 1
        assert _row(t1)["status"] == "done"

        # ================================================= (B) legal non-lead path
        t2 = _seed(type="technical_audit", status="todo", assignee_id=spec_uid)
        assert _update(spec_uid, t2, {"status": "in_progress"}) == 1
        assert _row(t2)["status"] == "in_progress"
        # non-content delivers straight to done (no review gate)
        assert _update(spec_uid, t2, {"status": "done"}) == 1
        assert _row(t2)["status"] == "done"

        # ===================================================== (C) lead may reject
        t3 = _seed(type="content_sprint", status="review", assignee_id=spec_uid)
        assert _update(lead_uid, t3, {"status": "in_progress"}) == 1
        assert _row(t3)["status"] == "in_progress"

        # ============================================ (D) assignee must be staff
        t4 = _seed(type="local_seo", status="todo", assignee_id=spec_uid)
        with pytest.raises(psycopg.Error):
            _update(lead_uid, t4, {"assignee_id": cli_uid})
        assert str(_row(t4)["assignee_id"]) == spec_uid

        # ================================= (E) my-queue scoping + client exclusion
        # Staff see the board; the specialist can scope to their own queue.
        with rls_connection(spec_uid, pool=rls_pool) as cur:
            cur.execute("select code from public.tasks where assignee_id = %s", (spec_uid,))
            my_queue = {str(r["code"]) for r in cur.fetchall()}
        assert {t1, t2, t3, t4}.issubset(my_queue)

        # A portal client is fully excluded: no reads, no insert, no update.
        with rls_connection(cli_uid, pool=rls_pool) as cur:
            cur.execute("select * from public.tasks")
            assert cur.fetchall() == []
        # insert refused by RLS (leads-only)
        with pytest.raises(psycopg.Error), rls_connection(cli_uid, pool=rls_pool) as cur:
            cur.execute(
                "insert into public.tasks (client_id, title, type) values (%s, 'x', 'publishing')",
                (client_id,),
            )
        # update matches 0 rows under RLS (no error, just nothing changed)
        assert _update(cli_uid, t2, {"status": "done"}) == 0
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for code in codes:
                cur.execute("delete from public.tasks where code = %s", (code,))
            for uid in uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
            if client_id:
                cur.execute("delete from public.clients where id = %s", (client_id,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
