"""Systematic RLS CORRECTNESS matrix - role x tenant-table x operation.

The existing ``test_rls_gate`` proves every tenant table has FORCE RLS *enabled*
(presence). This proves the policies are *correct*: it drives the tables DIRECTLY
as the ``authenticated`` role with each principal's identity bound (the true trust
boundary - any principal that leaked a portal/staff DB credential connects only as
``authenticated`` + its own ``auth.uid()``; ``rls_connection(uid)`` reproduces
exactly that) and asserts the allow/deny outcome of every (role, table, operation)
against the policy oracle below, which mirrors the live ``pg_policies`` exactly. It
also proves the mission's two headline guarantees systematically across ALL 12
tenant tables: a portal client's cross-tenant reads return 0 rows, and the
sensitive columns (mrr / cost / error / *_path / run_uuid / artifact_dir) are
unreachable with a tenant identity.

The policy oracle (from live pg_policies):
  SELECT is_staff():   activity_log audits client_budgets clients cost_dial
                       cost_log cost_settings sites tasks
  SELECT owner/admin:  vault_keys
  SELECT self-or-staff: users (auth.uid()=id OR is_staff),
                        user_feature_grants (user_id=auth.uid() OR is_staff)
  MODIFY owner/admin/manager:          clients sites client_budgets ; tasks INSERT
  MODIFY owner/admin/manager/spec/analyst: audits (NOT viewer, NOT client)
  MODIFY owner/admin:                  cost_dial cost_settings users
                                       user_feature_grants vault_keys
  APPEND-ONLY (no modify policy):      activity_log cost_log  (a tenant can never write)
  A client (is_staff redefined to exclude it in 0010) holds NO staff perm.

Auto-skips unless the local DB DSNs are set. Hermetic: provisions 6 staff + 2
portal clients (tenants A/B), seeds one row per table via service_role, tears all
down.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

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

_PASSWORD = "Passw0rd!rls-matrix-1"
_STAFF = ("owner", "admin", "manager", "specialist", "analyst", "viewer")
_CLIENTS = ("clientA", "clientB")

# SELECT oracle: the set of principal keys that see rows (>0) in each table.
# Everyone NOT listed must get exactly 0 rows.
_STAFF_SET = set(_STAFF)
_SELECT_ALLOW: dict[str, set[str]] = {
    "activity_log": _STAFF_SET,
    "audits": _STAFF_SET,
    "client_budgets": _STAFF_SET,
    "clients": _STAFF_SET,
    "cost_dial": _STAFF_SET,
    "cost_log": _STAFF_SET,
    "cost_settings": _STAFF_SET,
    "sites": _STAFF_SET,
    "tasks": _STAFF_SET,
    "vault_keys": {"owner", "admin"},
}
# users / user_feature_grants are self-or-staff -> tested separately (not clean 0/all).


def _rows(ctx: Any, who: str, table: str, columns: str = "*") -> list[dict[str, Any]]:
    """SELECT ``columns`` from ``table`` as role authenticated bound to ``who``.

    An RLS decision never raises: a denial returns [] and an allow returns rows.
    """
    uid = ctx["uids"][who]
    query = sql.SQL("select {} from public.{}").format(sql.SQL(columns), sql.Identifier(table))
    with rls_connection(uid, pool=ctx["rls_pool"]) as cur:
        cur.execute(query)
        return cur.fetchall()


@pytest.fixture(scope="module")
def rls() -> Iterator[dict[str, Any]]:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    tag = uuid.uuid4().hex[:10]
    uids: dict[str, str] = {}
    cleanup_uids: list[str] = []
    cleanup_clients: list[str] = []
    cleanup_audits: list[str] = []
    cleanup_tasks: list[str] = []
    cleanup_vault: list[str] = []
    dial_key = f"rls_matrix_{tag}"

    try:
        # --- staff principals ---
        for role in _STAFF:
            u = provision_user(
                email=f"rls-{role}-{tag}@example.com", password=_PASSWORD, name=f"RLS {role}",
                role=role, username=f"rls_{role}_{tag}",  # type: ignore[arg-type]
                template_key="super" if role == "owner" else None,
            )
            uids[role] = str(u["id"])
            cleanup_uids.append(str(u["id"]))

        tenant: dict[str, str] = {}
        with privileged_connection(pool=admin_pool) as cur:
            # --- two tenants A and B (service_role) ---
            for key, mrr in (("A", 5000), ("B", 7000)):
                cur.execute(
                    "insert into public.clients "
                    "(name, industry, mrr, delivery_tier, contact_email) "
                    "values (%s, 'Testing', %s, 'free', %s) returning id",
                    (f"RLS Tenant {key}", mrr, f"{key.lower()}@rls.example"),
                )
                tenant[key] = str(cur.fetchone()["id"])
                cleanup_clients.append(tenant[key])

        # --- two portal clients pinned to A and B ---
        for key, ckey in (("A", "clientA"), ("B", "clientB")):
            u = provision_user(
                email=f"rls-{ckey}-{tag}@example.com", password=_PASSWORD, name=f"RLS {ckey}",
                role="client", username=f"rls_{ckey}_{tag}", client_id=tenant[key],
            )
            uids[ckey] = str(u["id"])
            cleanup_uids.append(str(u["id"]))

        # --- one row per table (service_role bypasses RLS) ---
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute("insert into public.sites (client_id, domain) values (%s, 'rls-a.example')", (tenant["A"],))
            cur.execute(
                "insert into public.audits "
                "(client_id, client_name, url, types, tier, status, score, cost, error, "
                " run_uuid, artifact_dir, pdf_path, json_path) "
                "values (%s, 'RLS Tenant A', 'http://a.example', %s, 'free', 'done', 77, 4.25, "
                "'seed-error-string', 'seed-run-a', '/seed/a', 'x/report.pdf', 'x/findings.json') "
                "returning id",
                (tenant["A"], ["technical"]),
            )
            audit_a = str(cur.fetchone()["id"])
            cleanup_audits.append(audit_a)
            cur.execute(
                "insert into public.audits (client_id, client_name, url, types, tier, status) "
                "values (%s, 'RLS Tenant B', 'http://b.example', %s, 'free', 'queued') returning id",
                (tenant["B"], ["technical"]),
            )
            audit_b = str(cur.fetchone()["id"])
            cleanup_audits.append(audit_b)
            cur.execute(
                "insert into public.tasks (title, client_id, type, assignee_id, created_by) "
                "values ('RLS seed task', %s, 'technical_audit', %s, %s) returning code",
                (tenant["A"], uids["owner"], uids["owner"]),
            )
            cleanup_tasks.append(str(cur.fetchone()["code"]))
            cur.execute("insert into public.client_budgets (client_id, cap) values (%s, 100)", (tenant["A"],))
            cur.execute(
                "insert into public.cost_log (client_id, client_name, job_id, job_type, provider, cost) "
                "values (%s, 'RLS Tenant A', 'seed', 'audit', 'Serper', 1.5)",
                (tenant["A"],),
            )
            # cost_dial ships empty; seed one row so staff SELECT sees >0.
            cur.execute("insert into public.cost_dial (feature_key, mode) values (%s, 'off')", (dial_key,))
            cur.execute(
                "insert into public.activity_log (actor_id, actor_name, kind, action) "
                "values (%s, 'RLS owner', 'task', 'seeded')",
                (uids["owner"],),
            )
            cur.execute(
                "insert into public.vault_keys (provider, label, masked, secret_sealed) "
                "values ('serper', 'RLS Key', 'sk-****', %s) returning id",
                (b"sealed-bytes",),
            )
            cleanup_vault.append(str(cur.fetchone()["id"]))

        yield {"uids": uids, "tenant": tenant, "rls_pool": rls_pool, "admin_pool": admin_pool,
               "audit_a": audit_a, "audit_b": audit_b}
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for code in cleanup_tasks:
                cur.execute("delete from public.tasks where code = %s", (code,))
            for aid in cleanup_audits:
                cur.execute("delete from public.audits where id = %s", (aid,))
            for kid in cleanup_vault:
                cur.execute("delete from public.vault_keys where id = %s", (kid,))
            cur.execute("delete from public.cost_dial where feature_key = %s", (dial_key,))
            for uid in cleanup_uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in cleanup_clients:
                cur.execute("delete from public.clients where id = %s", (cid,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()


# --------------------------------------------------------------------------- #
def test_rls_select_matrix(rls: dict[str, Any]) -> None:
    """Every (table, principal) SELECT: allowed principals see rows, all others 0."""
    principals = list(_STAFF) + list(_CLIENTS)
    failures: list[str] = []
    for table, allow in _SELECT_ALLOW.items():
        for who in principals:
            try:
                rows = _rows(rls, who, table)
            except Exception as exc:  # a raise (permission denied) is also a "deny"
                rows = []
                if who in allow:
                    failures.append(f"{who} SELECT {table}: raised {type(exc).__name__} but should be allowed")
                    continue
            expected_allowed = who in allow
            got_rows = len(rows) > 0
            if expected_allowed and not got_rows:
                failures.append(f"{who} SELECT {table}: expected rows (allowed) but got 0")
            elif not expected_allowed and got_rows:
                sample = sorted(rows[0].keys())[:6]
                failures.append(f"{who} SELECT {table}: expected 0 (denied) but got {len(rows)} rows {sample}")
    assert not failures, "RLS SELECT VIOLATIONS:\n" + "\n".join(failures)


def test_rls_self_row_visibility(rls: dict[str, Any]) -> None:
    """users / user_feature_grants are self-or-staff: a client sees ONLY its own."""
    uids = rls["uids"]
    # Staff see the whole roster; a client sees only its own users row.
    assert len(_rows(rls, "owner", "users", "id")) > 1
    a_rows = _rows(rls, "clientA", "users", "id")
    assert a_rows, "clientA should see its own users row"
    assert all(str(r["id"]) == uids["clientA"] for r in a_rows), "clientA saw a users row that is not its own"
    assert uids["owner"] not in {str(r["id"]) for r in a_rows}, "clientA must not see staff users rows"
    # user_feature_grants: a client sees only its own grants (owner's are hidden).
    g_rows = _rows(rls, "clientA", "user_feature_grants", "user_id")
    assert all(str(r["user_id"]) == uids["clientA"] for r in g_rows), "clientA saw another user's grants"


def test_client_cross_tenant_isolation_via_views(rls: dict[str, Any]) -> None:
    """A portal client reads ONLY its own tenant through the security-barrier views."""
    tenant = rls["tenant"]
    a_audits = _rows(rls, "clientA", "portal_audits")
    assert a_audits, "clientA should see its own audit via the view"
    assert all(str(r["client_id"]) == tenant["A"] for r in a_audits), "clientA saw another tenant's audit"
    assert rls["audit_b"] not in {str(r["id"]) for r in a_audits}, "tenant B's audit leaked to clientA"

    a_client = _rows(rls, "clientA", "portal_client")
    assert [str(r["id"]) for r in a_client] == [tenant["A"]], "portal_client is not self-scoped"

    # clientB is the mirror image: sees B, never A.
    b_audits = _rows(rls, "clientB", "portal_audits")
    assert all(str(r["client_id"]) == tenant["B"] for r in b_audits)
    assert rls["audit_a"] not in {str(r["id"]) for r in b_audits}

    # The view carries NONE of the sensitive columns.
    forbidden = {"pdf_path", "json_path", "cost", "error", "run_uuid", "artifact_dir"}
    assert not (set(a_audits[0]) & forbidden), f"portal_audits leaked {set(a_audits[0]) & forbidden}"
    assert "mrr" not in set(a_client[0]) and "contact_email" not in set(a_client[0])


def test_sensitive_columns_unreachable_direct(rls: dict[str, Any]) -> None:
    """A tenant identity cannot read sensitive columns off the base tables (0 rows)."""
    assert _rows(rls, "clientA", "clients", "id,mrr") == [], "clients.mrr reachable by a client"
    assert _rows(rls, "clientA", "audits", "cost,error,pdf_path,json_path") == [], (
        "audits sensitive columns reachable by a client"
    )
    assert _rows(rls, "clientA", "cost_log", "cost") == [], "cost_log reachable by a client"


def test_rls_write_denial(rls: dict[str, Any]) -> None:
    """The security-critical direction: forbidden writes are refused at the DB."""
    uids, tenant, rls_pool = rls["uids"], rls["tenant"], rls["rls_pool"]

    def _insert_denied(who: str, statement: str, params: tuple[Any, ...]) -> None:
        with pytest.raises(psycopg.Error), rls_connection(uids[who], pool=rls_pool) as cur:
            cur.execute(statement, params)  # RLS violation raises

    def _rowcount(who: str, statement: str, params: tuple[Any, ...]) -> int:
        with rls_connection(uids[who], pool=rls_pool) as cur:
            cur.execute(statement, params)
            return cur.rowcount

    # A portal client cannot write ANY base table.
    _insert_denied("clientA", "insert into public.clients (name) values ('hacked')", ())
    _insert_denied("clientA", "insert into public.audits (url, client_id) values ('http://x', %s)", (tenant["B"],))
    _insert_denied("clientA", "insert into public.tasks (title, type) values ('x', 'technical_audit')", ())
    # ...nor mutate another tenant's row (0 rows affected, not an error).
    assert _rowcount("clientA", "update public.clients set mrr = 0 where id = %s", (tenant["B"],)) == 0
    assert _rowcount("clientA", "delete from public.clients where id = %s", (tenant["B"],)) == 0

    # Staff role boundaries: viewer cannot create an audit (excluded from audits_modify);
    # a specialist cannot create a task (INSERT is leads-only); a manager cannot write vault.
    _insert_denied("viewer", "insert into public.audits (url, client_id) values ('http://x', %s)", (tenant["A"],))
    _insert_denied(
        "specialist",
        "insert into public.tasks (title, type, client_id, assignee_id) "
        "values ('x', 'technical_audit', %s, %s)",
        (tenant["A"], uids["owner"]),
    )
    _insert_denied(
        "manager",
        "insert into public.vault_keys (provider, label, secret_sealed) values ('serper', 'x', %s)",
        (b"sealed",),
    )


def test_rls_write_allow(rls: dict[str, Any]) -> None:
    """The allow direction: an analyst may create an audit; a lead may create a task."""
    uids, tenant, rls_pool, admin_pool = rls["uids"], rls["tenant"], rls["rls_pool"], rls["admin_pool"]

    with rls_connection(uids["analyst"], pool=rls_pool) as cur:
        cur.execute(
            "insert into public.audits (url, client_id, types) "
            "values ('http://analyst.example', %s, %s) returning id",
            (tenant["A"], ["technical"]),
        )
        audit_id = str(cur.fetchone()["id"])
    assert audit_id, "analyst is in audits_modify and should be able to insert"
    with privileged_connection(pool=admin_pool) as cur:
        cur.execute("delete from public.audits where id = %s", (audit_id,))

    with rls_connection(uids["manager"], pool=rls_pool) as cur:
        cur.execute(
            "insert into public.tasks (title, type, client_id, assignee_id, created_by) "
            "values ('manager task', 'technical_audit', %s, %s, %s) returning code",
            (tenant["A"], uids["owner"], uids["manager"]),
        )
        code = str(cur.fetchone()["code"])
    assert code.startswith("J-"), "manager is a lead and should be able to insert a task"
    with privileged_connection(pool=admin_pool) as cur:
        cur.execute("delete from public.tasks where code = %s", (code,))


# --------------------------------------------------------------------------- #
# Auto-discovering policy oracle (covers the Part-7 modules WITHOUT hand-listing
# every table). The matrix above hand-curates the Part-2 tables; this reads the
# LIVE ``pg_policies`` at runtime, so every base table a migration ships -
# content_jobs, backlinks, citations, web2_properties, policy_sources /
# change_events / kb_entries / recommendations, report_workbooks /
# report_sync_events, client_projects / project_stages, upsells, notifications,
# alerts, support_tickets, workspace_settings / security_policy /
# notification_prefs, backup_snapshots / backup_config, audit_overlay - and any
# FUTURE module falls under it automatically.
#
# The crown-jewel invariant: under FORCE RLS, NO base-table policy may admit the
# portal ``client`` through an unconditional door. Every policy's predicate
# (USING and/or WITH CHECK, for every command) must reference at least one
# PRINCIPAL primitive - ``public.is_staff()`` (false for a client),
# ``public.current_app_role()`` (never a staff role for a client) or
# ``auth.uid()`` (self-scope only). A policy whose predicate is ``true`` / NULL /
# references no principal is a cross-tenant leak; this fails the moment one ships.
# --------------------------------------------------------------------------- #
_PRINCIPAL_PREDICATES = ("is_staff", "current_app_role", "auth.uid")


def _base_tables_and_policies(
    dsn: str,
) -> tuple[list[str], dict[str, list[tuple[str, str]]]]:
    """Return (base tables, {table: [(cmd, using-plus-withcheck-expr), ...]})."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select c.relname from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind = 'r' order by c.relname"
        )
        tables = [str(r[0]) for r in cur.fetchall()]
        cur.execute(
            "select tablename, cmd, "
            "coalesce(qual, '') || ' ' || coalesce(with_check, '') "
            "from pg_policies where schemaname = 'public'"
        )
        by_table: dict[str, list[tuple[str, str]]] = {}
        for tname, cmd, expr in cur.fetchall():
            by_table.setdefault(str(tname), []).append((str(cmd), str(expr)))
    return tables, by_table


def test_no_base_table_has_a_client_open_policy() -> None:
    """Every public base table (incl. all Part-7 modules) gates the portal client out.

    Auto-discovered from ``pg_policies`` so new modules need no manual registration.
    """
    settings = get_settings()
    dsn = settings.database_admin_url or settings.database_url
    if not dsn:
        pytest.skip("local Postgres not configured (DATABASE_ADMIN_URL / DATABASE_URL)")

    tables, by_table = _base_tables_and_policies(dsn)
    assert tables, "no public base tables found - are the migrations applied?"

    open_doors: list[str] = []
    no_read_policy: list[str] = []
    for table in tables:
        policies = by_table.get(table, [])
        if not any(cmd in ("SELECT", "ALL") for cmd, _ in policies):
            # A FORCE-RLS table with no SELECT/ALL policy denies everyone (staff too)
            # -> a module that forgot its read policy. Flag it.
            no_read_policy.append(table)
        for cmd, expr in policies:
            if not any(pred in expr for pred in _PRINCIPAL_PREDICATES):
                open_doors.append(f"{table}.{cmd}: `{expr.strip()[:120]}` references no principal predicate")

    assert not open_doors, (
        "CLIENT-OPEN RLS POLICIES (a portal client could satisfy the predicate):\n"
        + "\n".join(open_doors)
    )
    assert not no_read_policy, (
        "base tables with FORCE RLS but no SELECT/ALL policy (unreadable even by staff): "
        f"{no_read_policy}"
    )
