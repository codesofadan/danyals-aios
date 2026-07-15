"""Integration: the service_role DATA writes re-expressed on
``privileged_connection`` are behaviorally correct (P6A-5 acceptance).

Unit tests exercise these services through in-memory fakes / protocol stores, so
they never touch real SQL. This suite is the SQL-correctness proof for the writes
that moved off the Supabase admin client onto the privileged (service_role,
BYPASSRLS) psycopg connection:

  * ``activity.log_activity`` appends one snapshotted row, and
    ``activity.record_activity`` is best-effort (a bad actor FK never raises),
  * ``cost_store.SupabaseCostStore.record_cost`` writes a cost_log row AND
    atomically increments the client's month-to-date spend via
    ``add_budget_spend``,
  * ``client_audits.insert_audit_row`` lands a queued audit with client_id pinned,
  * ``workers...SupabaseAuditStore`` drives an audit row queued -> running -> done
    (including the jsonb ``scores`` column),
  * the portal artifact-path loader resolves ``pdf_path``/``json_path`` server-side
    while the RLS ``portal_audits`` view only lets the OWNER reach it.

It runs against the local Postgres named by DATABASE_URL (authenticated) +
DATABASE_ADMIN_URL (service_role) and auto-skips when either is unset, mirroring
the sibling integration suites. Everything seeded is torn down in a finally.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.core.auth import CurrentUser
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.db.portal_repo import PortalRepo
from app.routers.portal import get_portal_audit_loader
from app.services.activity import log_activity, record_activity
from app.services.client_audits import insert_audit_row
from app.services.cost_gate import GateContext
from app.services.cost_store import SupabaseCostStore
from workers.tasks.audit import SupabaseAuditStore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def seed() -> Iterator[dict[str, Any]]:
    rls_dsn = os.environ.get("DATABASE_URL")
    admin_dsn = os.environ.get("DATABASE_ADMIN_URL")
    if not rls_dsn or not admin_dsn:
        pytest.skip("DATABASE_URL and DATABASE_ADMIN_URL required")

    rls_pool = build_rls_pool(rls_dsn)
    admin_pool = build_admin_pool(admin_dsn)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    # Register as the process-wide pools so the services (which call
    # privileged_connection() / rls_connection(user_id) with NO pool arg) use them.
    set_pools(rls_pool, admin_pool)

    tag = uuid.uuid4().hex[:8]
    staff_uid = str(uuid.uuid4())
    client_uid = str(uuid.uuid4())
    client_ids: list[str] = []
    auth_ids: list[str] = []

    try:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "insert into public.clients (name, industry, delivery_tier) "
                "values (%s, 'SvcWrites', 'fully') returning id",
                (f"SvcWrites A {tag}",),
            )
            tenant_a = str(cur.fetchone()["id"])
            client_ids.append(tenant_a)
            cur.execute(
                "insert into public.clients (name, industry, delivery_tier) "
                "values (%s, 'SvcWrites', 'free') returning id",
                (f"SvcWrites B {tag}",),
            )
            tenant_b = str(cur.fetchone()["id"])
            client_ids.append(tenant_b)

            # staff (admin) + a portal client pinned to tenant A.
            cur.execute(
                "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                (staff_uid, f"svc-staff-{tag}@example.com"),
            )
            cur.execute(
                "insert into public.users (id, email, name, role) values (%s, %s, %s, 'admin')",
                (staff_uid, f"svc-staff-{tag}@example.com", f"Svc Staff {tag}"),
            )
            auth_ids.append(staff_uid)
            cur.execute(
                "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                (client_uid, f"svc-client-{tag}@example.com"),
            )
            cur.execute(
                "insert into public.users (id, email, name, role, client_id) "
                "values (%s, %s, %s, 'client', %s)",
                (client_uid, f"svc-client-{tag}@example.com", f"Svc Client {tag}", tenant_a),
            )
            auth_ids.append(client_uid)

            # a budget for tenant A: cap high, spent 0 -> record_cost increments it.
            cur.execute(
                "insert into public.client_budgets (client_id, cap, spent) values (%s, 1000, 0)",
                (tenant_a,),
            )

        yield {
            "tag": tag,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "staff_uid": staff_uid,
            "client_uid": client_uid,
            "admin_pool": admin_pool,
        }
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            # audits/cost_log/activity_log rows FK to clients/users; clearing them
            # by tag keeps the teardown independent of what each test created.
            cur.execute("delete from public.audits where client_name like %s", (f"SvcWrites%{tag}",))
            cur.execute("delete from public.cost_log where client_name like %s", (f"SvcWrites%{tag}",))
            cur.execute("delete from public.activity_log where actor_name like %s", (f"Svc%{tag}",))
            for uid in auth_ids:  # cascades public.users
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in client_ids:  # cascades client_budgets
                cur.execute("delete from public.clients where id = %s", (cid,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()


# --- activity.log_activity / record_activity ----------------------------------
def test_log_activity_appends_snapshot_row(seed: dict[str, Any]) -> None:
    target = f"Verde {seed['tag']}"
    log_activity(
        actor_id=seed["staff_uid"], actor_name=f"Svc Staff {seed['tag']}",
        actor_color="#123456", kind="client", action="created client", target=target,
    )
    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute(
            "select actor_id, actor_init, kind, action, target "
            "from public.activity_log where target = %s limit 1",
            (target,),
        )
        row = cur.fetchone()
    assert row is not None
    assert str(row["actor_id"]) == seed["staff_uid"]
    assert row["actor_init"] == "SS"  # initials("Svc Staff ...")
    assert row["kind"] == "client" and row["action"] == "created client"


async def test_record_activity_never_raises_on_bad_actor(seed: dict[str, Any]) -> None:
    # An actor_id that is not a real user violates the activity_log FK; the write
    # raises inside the privileged txn and record_activity must swallow it.
    ghost = CurrentUser(
        id=str(uuid.uuid4()), email="ghost@x.com", role="admin", status="active",
        name=f"Svc Ghost {seed['tag']}", title="", avatar_color="#000", phone="", two_fa=False,
    )
    await record_activity(ghost, kind="client", action="created client", target="X")  # no raise
    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute(
            "select count(*) as n from public.activity_log where actor_name = %s",
            (f"Svc Ghost {seed['tag']}",),
        )
        assert cur.fetchone()["n"] == 0  # the bad-FK insert never landed


# --- cost_store.SupabaseCostStore.record_cost ---------------------------------
def test_record_cost_logs_and_increments_budget(seed: dict[str, Any]) -> None:
    store = SupabaseCostStore()
    ctx = GateContext(
        feature_key="tech_audit", client_id=seed["tenant_a"], provider="audit_engine",
        estimated_cost=4.0, job_id="job-1", job_type="audit",
        client_name=f"SvcWrites A {seed['tag']}",
    )
    store.record_cost(ctx, 4.0, cached=False)

    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute(
            "select cost, cached, provider, job_id from public.cost_log "
            "where client_id = %s order by created_at desc limit 1",
            (seed["tenant_a"],),
        )
        log = cur.fetchone()
        cur.execute(
            "select spent from public.client_budgets where client_id = %s", (seed["tenant_a"],)
        )
        budget = cur.fetchone()
    assert log is not None
    assert float(log["cost"]) == 4.0 and log["cached"] is False
    assert log["provider"] == "audit_engine" and log["job_id"] == "job-1"
    assert budget is not None and float(budget["spent"]) == 4.0  # add_budget_spend applied


def test_record_cost_cached_does_not_touch_budget(seed: dict[str, Any]) -> None:
    store = SupabaseCostStore()
    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute("select spent from public.client_budgets where client_id = %s", (seed["tenant_a"],))
        before = float(cur.fetchone()["spent"])
    ctx = GateContext(
        feature_key="tech_audit", client_id=seed["tenant_a"], provider="audit_engine",
        estimated_cost=0.0, client_name=f"SvcWrites A {seed['tag']}",
    )
    store.record_cost(ctx, 0.0, cached=True)  # cached -> log at $0, no budget move
    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute("select spent from public.client_budgets where client_id = %s", (seed["tenant_a"],))
        after = float(cur.fetchone()["spent"])
    assert after == before


# --- client_audits.insert_audit_row -------------------------------------------
def test_insert_audit_row_pins_client_and_queues(seed: dict[str, Any]) -> None:
    row = insert_audit_row(
        {
            "client_id": seed["tenant_a"],
            "client_name": f"SvcWrites A {seed['tag']}",
            "url": "http://svc-insert.example",
            "types": ["technical"],
            "tier": "free",
            "status": "queued",
        }
    )
    assert row["id"] and row["status"] == "queued"
    assert str(row["client_id"]) == seed["tenant_a"]
    assert row["url"] == "http://svc-insert.example"
    # Round-trips: the row is really persisted.
    with privileged_connection(pool=seed["admin_pool"]) as cur:
        cur.execute("select status from public.audits where id = %s", (row["id"],))
        assert cur.fetchone()["status"] == "queued"


# --- workers...SupabaseAuditStore lifecycle -----------------------------------
def test_audit_store_lifecycle_queued_to_done(seed: dict[str, Any]) -> None:
    store = SupabaseAuditStore()
    seeded = insert_audit_row(
        {
            "client_id": seed["tenant_a"],
            "client_name": f"SvcWrites A {seed['tag']}",
            "url": "http://svc-lifecycle.example",
            "types": ["technical"],
            "tier": "paid",
            "status": "queued",
        }
    )
    audit_id = str(seeded["id"])

    loaded = store.load(audit_id)
    assert loaded is not None and loaded["status"] == "queued"

    store.update(audit_id, {"status": "running", "started_at": "2026-07-15T10:00:00Z"})
    store.update(
        audit_id,
        {
            "status": "done",
            "run_uuid": "run-xyz",
            "score": 88,
            "scores": {"technical": 90, "overall": 88},  # jsonb column
            "pdf_path": "stored/svc.pdf",
            "runtime_seconds": 120,
            "finished_at": "2026-07-15T10:02:00Z",
        },
    )

    final = store.load(audit_id)
    assert final is not None
    assert final["status"] == "done" and final["score"] == 88
    assert final["run_uuid"] == "run-xyz"
    assert final["scores"] == {"technical": 90, "overall": 88}
    assert final["pdf_path"] == "stored/svc.pdf"
    assert final["started_at"] is not None and final["finished_at"] is not None


def test_audit_store_update_noop_on_empty_fields(seed: dict[str, Any]) -> None:
    SupabaseAuditStore().update(str(uuid.uuid4()), {})  # empty fields -> no SQL, no raise


# --- portal artifact-path loader (owner-only via the RLS view) ----------------
def test_portal_loader_resolves_paths_for_owner_only(seed: dict[str, Any]) -> None:
    # Tenant A's audit (the client's OWN) + tenant B's audit (a foreign one).
    own = insert_audit_row(
        {
            "client_id": seed["tenant_a"], "client_name": f"SvcWrites A {seed['tag']}",
            "url": "http://svc-own.example", "types": ["technical"], "tier": "free",
            "status": "done", "pdf_path": "stored/own.pdf", "json_path": "stored/own.json",
        }
    )
    foreign = insert_audit_row(
        {
            "client_id": seed["tenant_b"], "client_name": f"SvcWrites B {seed['tag']}",
            "url": "http://svc-foreign.example", "types": ["technical"], "tier": "free",
            "status": "done", "pdf_path": "stored/foreign.pdf",
        }
    )
    own_id, foreign_id = str(own["id"]), str(foreign["id"])

    loader = get_portal_audit_loader()
    paths = loader(own_id)
    assert paths is not None
    assert paths["pdf_path"] == "stored/own.pdf" and paths["json_path"] == "stored/own.json"

    # The client (pinned to tenant A) OWNS own_id via the RLS portal_audits view,
    # but tenant B's audit is invisible -> a caller can never reach its path.
    repo = PortalRepo(seed["client_uid"])
    assert repo.get_audit(own_id) is not None
    assert repo.get_audit(foreign_id) is None
