"""Integration: prove the Part-7 CONTENT lifecycle + the DB-enforced 3-actor guard
against LOCAL Postgres (RLS + the ``content_jobs_guard_update`` trigger are the
boundary, not FastAPI).

Skips unless DATABASE_URL + DATABASE_ADMIN_URL are set (migration 0017 applied).
Provisions a lead (manager), a non-lead assignee (specialist), and a portal client,
then asserts - via each principal's OWN identity on the ``authenticated`` role
hitting ``content_jobs`` DIRECTLY (a leaked staff/portal DB credential; RLS +
triggers are the only boundary), reproduced by ``rls_connection(uid)``, and the
WORKER via ``privileged_connection`` (service_role, ``auth.uid()`` IS NULL):

  (A) THE BLOCKER PROOF: a NON-LEAD's direct ``needs_review -> publishing`` (and
      ``-> done``, and any column edit) is REJECTED by the guard - the content
      lifecycle is owned entirely by the pipeline + the leads;
  (B) a LEAD CAN make the review-exit decisions (needs_review -> publishing /
      rejected / drafting);
  (C) the WORKER path (privileged / service_role) CAN advance the system
      transitions queued -> drafting -> needs_review, and publishing -> done, but
      an ILLEGAL system jump (e.g. queued -> done) is REJECTED;
  (D) a portal client is fully excluded (0 rows on read; insert/update blocked).

Everything created is cleaned up in a finally block.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

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

_PASSWORD = "Passw0rd!content-flow-123"


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


async def test_content_lifecycle_and_db_guard() -> None:
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
        row: dict[str, Any] = {
            "client_id": client_id, "client_name": "Flow Co", "color": "#22C55E",
            "page_type": "blog", "topic": "flow topic", "framework": "PAS",
            "target": "WordPress", "status": "queued", "source_pack": Jsonb({"client_name": "Flow Co"}),
        }
        row.update(over)
        cols = list(row)
        stmt = sql.SQL("insert into public.content_jobs ({}) values ({}) returning code").format(
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
            cur.execute("select * from public.content_jobs where code = %s", (code,))
            return cur.fetchone()

    def _update_rls(uid: str, code: str, changes: dict[str, Any]) -> int:
        """UPDATE as role ``authenticated`` with ``uid`` bound. Returns rowcount."""
        cols = list(changes)
        sets = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder()) for c in cols
        )
        stmt = sql.SQL("update public.content_jobs set {} where code = {}").format(sets, sql.Placeholder())
        with rls_connection(uid, pool=rls_pool) as cur:
            cur.execute(stmt, [*(changes[c] for c in cols), code])
            return cur.rowcount

    def _update_worker(code: str, changes: dict[str, Any]) -> int:
        """UPDATE as service_role (auth.uid() IS NULL) - the WORKER path."""
        cols = list(changes)
        sets = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder()) for c in cols
        )
        stmt = sql.SQL("update public.content_jobs set {} where code = {}").format(sets, sql.Placeholder())
        with privileged_connection(pool=admin_pool) as cur:
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
            email=f"cflow-lead-{tag}@example.com", password=_PASSWORD, name="CFlow Lead",
            role="manager", username=f"cflow_lead_{tag}",
        )["id"])
        spec_uid = str(provision_user(
            email=f"cflow-spec-{tag}@example.com", password=_PASSWORD, name="CFlow Spec",
            role="specialist", username=f"cflow_spec_{tag}",
        )["id"])
        cli_uid = str(provision_user(
            email=f"cflow-cli-{tag}@example.com", password=_PASSWORD, name="CFlow Client",
            role="client", username=f"cflow_cli_{tag}", client_id=client_id,
        )["id"])
        uids += [lead_uid, spec_uid, cli_uid]

        # =============================================== (C) WORKER system path
        # The worker (service_role) advances queued -> drafting -> needs_review.
        j1 = _seed(status="queued", assignee_id=spec_uid)
        assert _update_worker(j1, {"status": "drafting"}) == 1
        assert _row(j1)["status"] == "drafting"
        assert _update_worker(j1, {"status": "needs_review", "draft_md": "# Draft"}) == 1
        assert _row(j1)["status"] == "needs_review"

        # An ILLEGAL system jump is rejected by the guard (queued -> done).
        j_bad = _seed(status="queued")
        with pytest.raises(psycopg.Error):
            _update_worker(j_bad, {"status": "done"})
        assert _row(j_bad)["status"] == "queued"

        # ========================================= (A) BLOCKER: non-lead rejected
        # The specialist assignee tries to APPROVE (needs_review -> publishing).
        with pytest.raises(psycopg.Error):
            _update_rls(spec_uid, j1, {"status": "publishing"})
        assert _row(j1)["status"] == "needs_review"  # never moved

        # ...and to self-publish straight to done. Also rejected (worker-only).
        with pytest.raises(psycopg.Error):
            _update_rls(spec_uid, j1, {"status": "done"})
        assert _row(j1)["status"] == "needs_review"

        # ...and even a NON-status column edit by the non-lead is rejected.
        with pytest.raises(psycopg.Error):
            _update_rls(spec_uid, j1, {"topic": "hijacked"})
        assert _row(j1)["topic"] != "hijacked"

        # ================================================ (B) LEAD review exit
        # A lead CAN approve (needs_review -> publishing).
        assert _update_rls(lead_uid, j1, {"status": "publishing"}) == 1
        assert _row(j1)["status"] == "publishing"
        # ...and the worker then completes publishing -> done.
        assert _update_worker(j1, {"status": "done", "wp_post_id": "1234"}) == 1
        assert _row(j1)["status"] == "done"

        # A lead can REJECT another job (needs_review -> rejected)...
        j2 = _seed(status="needs_review")
        assert _update_rls(lead_uid, j2, {"status": "rejected"}) == 1
        assert _row(j2)["status"] == "rejected"
        # ...and EDIT a third back to drafting (needs_review -> drafting).
        j3 = _seed(status="needs_review")
        assert _update_rls(lead_uid, j3, {"status": "drafting"}) == 1
        assert _row(j3)["status"] == "drafting"

        # ========================================= (D) portal client exclusion
        with rls_connection(cli_uid, pool=rls_pool) as cur:
            cur.execute("select * from public.content_jobs")
            assert cur.fetchall() == []
        # insert refused by RLS (leads-only insert policy)
        with pytest.raises(psycopg.Error), rls_connection(cli_uid, pool=rls_pool) as cur:
            cur.execute(
                "insert into public.content_jobs "
                "(client_id, page_type, topic, framework, target) "
                "values (%s, 'blog', 'x', 'PAS', 'WordPress')",
                (client_id,),
            )
        # update matches 0 rows under RLS (no error, just nothing changed)
        assert _update_rls(cli_uid, j2, {"status": "drafting"}) == 0
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for code in codes:
                cur.execute("delete from public.content_jobs where code = %s", (code,))
            for uid in uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
            if client_id:
                cur.execute("delete from public.clients where id = %s", (client_id,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
