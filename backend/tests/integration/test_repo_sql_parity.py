"""Integration: the repo layer's hand-SQL is behaviorally identical to the old
PostgREST chains (P6A-4 acceptance).

Unit tests exercise the repos through in-memory FAKES, so they never touch real
SQL. This suite is the SQL-correctness proof: it seeds rows directly through
``privileged_connection()`` (service_role bypasses RLS) for two tenants + a staff
user + a portal client, then drives the ACTUAL repo methods (which open
``rls_connection`` off the module pools registered via ``set_pools``) and asserts:

  * correct rows + exact ORDER (``order by ... [desc]``),
  * PAGINATION (``limit``/``offset`` returns the right slice),
  * RLS scoping - staff (is_staff) sees every tenant; a portal client sees ONLY
    its own via the ``portal_*`` views; an unknown identity sees zero,
  * the ``role <> 'client'`` roster exclusion,
  * insert-returns-the-inserted-row (``returning *``),
  * upsert (insert-or-update) + join-merge shapes.

It runs against the local Postgres named by DATABASE_URL (authenticated) +
DATABASE_ADMIN_URL (service_role) and auto-skips when either is unset, mirroring
the sibling integration suites. Everything seeded is torn down in a finally.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.db.activity_repo import ActivityRepo
from app.db.audits_repo import AuditsRepo
from app.db.clients_repo import ClientsRepo
from app.db.cost_repo import CostRepo
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.db.portal_repo import PortalRepo
from app.db.tasks_repo import TasksRepo
from app.db.tiers_repo import TiersRepo
from app.routers import admin_users

pytestmark = pytest.mark.integration


def _relative_order(full_ids: list[str], expected: list[str]) -> bool:
    """True iff every id in ``expected`` appears in ``full_ids`` in that exact
    relative order (used for staff-wide tables where other rows may coexist)."""
    wanted = set(expected)
    present = [i for i in full_ids if i in wanted]
    return present == expected


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
    # Register as the process-wide pools so repo methods (which call
    # rls_connection(user_id) / privileged_connection() with NO pool arg) use them.
    set_pools(rls_pool, admin_pool)

    tag = uuid.uuid4().hex[:8]
    t0 = datetime(2020, 1, 1, tzinfo=UTC)  # far-past base -> deterministic ordering
    now = datetime.now(UTC)

    staff_uid = str(uuid.uuid4())
    client_uid = str(uuid.uuid4())
    dial_key = f"parity_feat_{tag}"

    audit_ids: list[str] = []
    task_codes: list[str] = []
    activity_ids: list[str] = []
    cost_log_ids: list[str] = []

    try:
        with privileged_connection(pool=admin_pool) as cur:
            # --- two tenants. Names chosen so B sorts BEFORE A (order-by-name proof).
            cur.execute(
                "insert into public.clients "
                "(name, industry, mrr, tier, contact_color, delivery_tier) "
                "values (%s, 'ParityInd', 5000, 'Growth', '#111111', 'free') returning id",
                (f"ZParity A {tag}",),
            )
            tenant_a = str(cur.fetchone()["id"])
            cur.execute(
                "insert into public.clients "
                "(name, industry, mrr, tier, contact_color, delivery_tier) "
                "values (%s, 'ParityInd', 7000, 'Scale', '#222222', 'semi') returning id",
                (f"AParity B {tag}",),
            )
            tenant_b = str(cur.fetchone()["id"])

            # --- staff (admin = a lead: passes clients/tasks/audits modify + is_staff).
            cur.execute(
                "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                (staff_uid, f"parity-staff-{tag}@example.com"),
            )
            cur.execute(
                "insert into public.users (id, email, name, role) "
                "values (%s, %s, %s, 'admin')",
                (staff_uid, f"parity-staff-{tag}@example.com", f"Parity Staff {tag}"),
            )
            # --- portal client pinned to tenant A.
            cur.execute(
                "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                (client_uid, f"parity-client-{tag}@example.com"),
            )
            cur.execute(
                "insert into public.users (id, email, name, role, client_id) "
                "values (%s, %s, %s, 'client', %s)",
                (client_uid, f"parity-client-{tag}@example.com", f"Parity Client {tag}", tenant_a),
            )

            # --- sites for A (order-by-domain proof: 'a.' before 'b.').
            cur.executemany(
                "insert into public.sites (client_id, domain) values (%s, %s)",
                [(tenant_a, "b.paritysite"), (tenant_a, "a.paritysite")],
            )

            # --- 3 audits for A (created_at t0<t1<t2) + 1 for B (isolation proof).
            for i in range(3):
                cur.execute(
                    "insert into public.audits "
                    "(client_id, client_name, url, types, tier, status, created_at) "
                    "values (%s, %s, %s, %s, 'free', 'done', %s) returning id",
                    (tenant_a, f"ZParity A {tag}", f"http://a{i}.example",
                     ["technical"], t0 + timedelta(minutes=i)),
                )
                audit_ids.append(str(cur.fetchone()["id"]))
            cur.execute(
                "insert into public.audits "
                "(client_id, client_name, url, types, tier, status, created_at) "
                "values (%s, %s, 'http://b.example', %s, 'free', 'queued', %s) returning id",
                (tenant_b, f"AParity B {tag}", ["technical"], t0 + timedelta(minutes=5)),
            )
            audit_b_id = str(cur.fetchone()["id"])
            audit_ids.append(audit_b_id)

            # --- 3 tasks for the staff user (assignee filter -> fully controlled set).
            for i in range(3):
                cur.execute(
                    "insert into public.tasks "
                    "(title, client_id, client_name, type, assignee_id, created_by, "
                    " status, created_at) "
                    "values (%s, %s, %s, 'technical_audit', %s, %s, 'todo', %s) returning code",
                    (f"Parity task {i} {tag}", tenant_a, f"ZParity A {tag}",
                     staff_uid, staff_uid, t0 + timedelta(minutes=i)),
                )
                task_codes.append(str(cur.fetchone()["code"]))

            # --- budgets for A + B.
            cur.executemany(
                "insert into public.client_budgets (client_id, cap) values (%s, %s)",
                [(tenant_a, 100), (tenant_b, 200)],
            )

            # --- cost log: one TODAY (counts toward today_spent) + one far-past.
            cur.execute(
                "insert into public.cost_log (client_id, client_name, cost, created_at) "
                "values (%s, %s, %s, %s) returning id",
                (tenant_a, f"ZParity A {tag}", 2.5, now),
            )
            cost_log_ids.append(str(cur.fetchone()["id"]))
            cur.execute(
                "insert into public.cost_log (client_id, client_name, cost, created_at) "
                "values (%s, %s, %s, %s) returning id",
                (tenant_a, f"ZParity A {tag}", 9.0, t0),
            )
            cost_log_ids.append(str(cur.fetchone()["id"]))

            # --- activity log: two rows (created_at t0<t1).
            for i in range(2):
                cur.execute(
                    "insert into public.activity_log "
                    "(actor_id, actor_name, kind, action, created_at) "
                    "values (%s, %s, 'task', 'seeded', %s) returning id",
                    (staff_uid, f"Parity Staff {tag}", t0 + timedelta(minutes=i)),
                )
                activity_ids.append(str(cur.fetchone()["id"]))

        yield {
            "tenant_a": tenant_a, "tenant_b": tenant_b,
            "staff_uid": staff_uid, "client_uid": client_uid,
            "audit_ids": audit_ids[:3], "audit_b_id": audit_b_id,
            "task_codes": task_codes, "activity_ids": activity_ids,
            "cost_log_ids": cost_log_ids, "today_cost": 2.5, "dial_key": dial_key,
            "admin_pool": admin_pool,
        }
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for code in task_codes:
                cur.execute("delete from public.tasks where code = %s", (code,))
            for aid in audit_ids:
                cur.execute("delete from public.audits where id = %s", (aid,))
            for lid in cost_log_ids:
                cur.execute("delete from public.cost_log where id = %s", (lid,))
            for act in activity_ids:
                cur.execute("delete from public.activity_log where id = %s", (act,))
            cur.execute("delete from public.cost_dial where feature_key = %s", (dial_key,))
            for uid in (staff_uid, client_uid):
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in (tenant_a, tenant_b):
                cur.execute("delete from public.clients where id = %s", (cid,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()


# --- clients_repo -------------------------------------------------------------
def test_clients_repo_read_order_and_staff_scope(seed: dict[str, Any]) -> None:
    repo = ClientsRepo(seed["staff_uid"])
    rows = repo.list_clients()
    ids = [str(r["id"]) for r in rows]
    # is_staff sees BOTH tenants; order by name -> B ("AParity") before A ("ZParity").
    assert _relative_order(ids, [seed["tenant_b"], seed["tenant_a"]])

    got = repo.get_client(seed["tenant_a"])
    assert got is not None
    assert got["mrr"] == 5000 and got["delivery_tier"] == "free" and got["tier"] == "Growth"

    # site_counts includes tenant A's two seeded sites.
    assert repo.site_counts().get(seed["tenant_a"]) == 2

    # list_sites for A: order by domain -> 'a.' before 'b.'.
    domains = [r["domain"] for r in repo.list_sites(seed["tenant_a"])]
    assert domains == ["a.paritysite", "b.paritysite"]


def test_clients_repo_rls_denies_non_staff(seed: dict[str, Any]) -> None:
    # A portal client is NOT staff -> zero rows on the base clients table.
    assert ClientsRepo(seed["client_uid"]).list_clients() == []
    # An unknown (unprovisioned) identity -> zero rows too.
    assert ClientsRepo(str(uuid.uuid4())).list_clients() == []


def test_clients_repo_insert_returns_row(seed: dict[str, Any]) -> None:
    repo = ClientsRepo(seed["staff_uid"])
    inserted = repo.insert_client({"name": f"Ins Parity {uuid.uuid4().hex[:6]}", "industry": "X"})
    try:
        assert inserted["id"] and inserted["name"].startswith("Ins Parity")
        assert inserted["industry"] == "X"
        # Round-trips through RLS: the staff repo can read it back.
        assert repo.get_client(str(inserted["id"])) is not None
    finally:
        with privileged_connection(pool=seed["admin_pool"]) as cur:
            cur.execute("delete from public.clients where id = %s", (inserted["id"],))


# --- tasks_repo (assignee filter -> deterministic slice for pagination) -------
def test_tasks_repo_order_and_pagination(seed: dict[str, Any]) -> None:
    repo = TasksRepo(seed["staff_uid"])
    codes = seed["task_codes"]  # seeded created_at t0<t1<t2
    got = [r["code"] for r in repo.list_tasks(seed["staff_uid"])]
    assert got == [codes[2], codes[1], codes[0]]  # order by created_at desc

    # PAGINATION: limit=1, offset=1 -> the middle element of the desc list.
    page = [r["code"] for r in repo.list_tasks(seed["staff_uid"], limit=1, offset=1)]
    assert page == [codes[1]]

    assert repo.get_task_by_code(codes[0]) is not None
    # Staff may read the whole roster (users_select self-or-staff).
    assert repo.get_user(seed["client_uid"]) is not None


def test_tasks_repo_rls_denies_client(seed: dict[str, Any]) -> None:
    assert TasksRepo(seed["client_uid"]).list_tasks() == []


def test_tasks_repo_insert_returns_row(seed: dict[str, Any]) -> None:
    repo = TasksRepo(seed["staff_uid"])
    inserted = repo.insert_task({
        "title": f"Ins Task {uuid.uuid4().hex[:6]}", "client_id": seed["tenant_a"],
        "client_name": "ZParity A", "type": "technical_audit",
        "assignee_id": seed["staff_uid"], "created_by": seed["staff_uid"], "status": "todo",
    })
    try:
        assert inserted["code"].startswith("J-")  # DB-minted public code returned
        assert inserted["status"] == "todo" and inserted["title"].startswith("Ins Task")
    finally:
        with privileged_connection(pool=seed["admin_pool"]) as cur:
            cur.execute("delete from public.tasks where code = %s", (inserted["code"],))


# --- audits_repo --------------------------------------------------------------
def test_audits_repo_order_and_insert(seed: dict[str, Any]) -> None:
    repo = AuditsRepo(seed["staff_uid"])
    ids = [str(r["id"]) for r in repo.list_audits()]
    # created_at desc: t2, t1, t0 for tenant A (relative order among all audits).
    assert _relative_order(ids, list(reversed(seed["audit_ids"])))

    assert repo.get_audit(seed["audit_ids"][0]) is not None

    inserted = repo.insert_audit({
        "client_id": seed["tenant_a"], "client_name": "ZParity A",
        "url": "http://ins.example", "types": ["technical"], "tier": "free", "status": "queued",
    })
    try:
        assert inserted["id"] and inserted["status"] == "queued"
        assert inserted["url"] == "http://ins.example"
    finally:
        with privileged_connection(pool=seed["admin_pool"]) as cur:
            cur.execute("delete from public.audits where id = %s", (inserted["id"],))


# --- activity_repo ------------------------------------------------------------
def test_activity_repo_order_and_pagination(seed: dict[str, Any]) -> None:
    repo = ActivityRepo(seed["staff_uid"])
    ids = [str(r["id"]) for r in repo.list_activity()]
    assert _relative_order(ids, list(reversed(seed["activity_ids"])))  # created_at desc
    assert len(repo.list_activity(limit=1)) <= 1  # limit cap honored


# --- cost_repo ----------------------------------------------------------------
def test_cost_repo_budgets_and_merge(seed: dict[str, Any]) -> None:
    repo = CostRepo(seed["staff_uid"])
    budgets = {b["id"]: b for b in repo.list_budgets()}
    a = budgets.get(seed["tenant_a"])
    assert a is not None
    # Merge joins the client for cn/tier/color; cap comes from client_budgets.
    assert a["cap"] == 100 and a["cn"].startswith("ZParity A") and a["tier"] == "Growth"


def test_cost_repo_upsert_budget(seed: dict[str, Any]) -> None:
    repo = CostRepo(seed["staff_uid"])
    first = repo.upsert_budget(seed["tenant_b"], 250)  # UPDATE path (B seeded at 200)
    assert first is not None and first["cap"] == 250
    second = repo.upsert_budget(seed["tenant_b"], 275)
    assert second is not None and second["cap"] == 275
    # Unknown client id is rejected (not in the client map) -> None.
    assert repo.upsert_budget(str(uuid.uuid4()), 5) is None


def test_cost_repo_dial_roundtrip(seed: dict[str, Any]) -> None:
    repo = CostRepo(seed["staff_uid"])
    repo.set_dial(seed["dial_key"], "api")          # INSERT
    assert repo.dial_modes().get(seed["dial_key"]) == "api"
    repo.set_dial(seed["dial_key"], "off")          # conflict -> UPDATE
    assert repo.dial_modes().get(seed["dial_key"]) == "off"


def test_cost_repo_log_and_today_spent(seed: dict[str, Any]) -> None:
    repo = CostRepo(seed["staff_uid"])
    log_ids = [str(r["id"]) for r in repo.list_cost_log()]
    # Newest first: the TODAY row precedes the far-past row.
    assert _relative_order(log_ids, [seed["cost_log_ids"][0], seed["cost_log_ids"][1]])
    # today_spent sums only rows created today (>= my seeded today cost).
    assert repo.today_spent() >= seed["today_cost"]


def test_cost_repo_settings_update(seed: dict[str, Any]) -> None:
    repo = CostRepo(seed["staff_uid"])
    original = repo.get_settings()
    try:
        updated = repo.update_settings({"daily_stop": 42})
        assert float(updated["daily_stop"]) == 42.0
    finally:  # restore the singleton to its prior value
        repo.update_settings({"daily_stop": original.get("daily_stop", 75)})


# --- tiers_repo ---------------------------------------------------------------
def test_tiers_repo_read_and_set(seed: dict[str, Any]) -> None:
    repo = TiersRepo(seed["staff_uid"])
    rows = {str(r["id"]): r for r in repo.list_tier_clients()}
    a = rows.get(seed["tenant_a"])
    assert a is not None and a["delivery_tier"] == "free"
    assert "mrr" not in a  # the tier column subset excludes mrr

    updated = repo.set_delivery_tier(seed["tenant_a"], "semi")
    try:
        assert updated is not None and updated["delivery_tier"] == "semi"
    finally:
        repo.set_delivery_tier(seed["tenant_a"], "free")  # restore


# --- portal_repo (client-scoped views -> deterministic order + pagination) ----
def test_portal_repo_client_scoped_reads(seed: dict[str, Any]) -> None:
    repo = PortalRepo(seed["client_uid"])

    client = repo.get_client()
    assert client is not None and str(client["id"]) == seed["tenant_a"]
    assert "mrr" not in client and "contact_email" not in client  # safe column subset

    sites = [r["domain"] for r in repo.list_sites()]
    assert sites == ["a.paritysite", "b.paritysite"]  # order by domain

    audits = [str(r["id"]) for r in repo.list_audits()]
    assert audits == list(reversed(seed["audit_ids"]))  # created_at desc, A-only

    # PAGINATION: exact middle slice of the desc list.
    page = [str(r["id"]) for r in repo.list_audits(limit=1, offset=1)]
    assert page == [seed["audit_ids"][1]]


def test_portal_repo_cross_tenant_isolation(seed: dict[str, Any]) -> None:
    repo = PortalRepo(seed["client_uid"])  # pinned to tenant A
    ids = {str(r["id"]) for r in repo.list_audits()}
    assert seed["audit_b_id"] not in ids  # tenant B's audit never leaks
    assert repo.get_audit(seed["audit_b_id"]) is None  # self-filter hides it


# --- admin roster (.neq('role','client')) -------------------------------------
def test_roster_excludes_clients_live(seed: dict[str, Any]) -> None:
    rows = admin_users._fetch_all_users(seed["staff_uid"])
    ids = {str(r["id"]) for r in rows}
    assert seed["staff_uid"] in ids       # staff member present
    assert seed["client_uid"] not in ids  # role='client' excluded in SQL
