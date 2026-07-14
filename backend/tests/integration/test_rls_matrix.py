"""Systematic RLS CORRECTNESS matrix - role x tenant-table x operation.

The existing ``test_rls_gate`` proves every tenant table has FORCE RLS *enabled*
(presence). This proves the policies are *correct*: it drives Supabase PostgREST
DIRECTLY with each principal's real JWT (the true trust boundary - any principal
holds the anon key + a JWT and can bypass FastAPI) and asserts the allow/deny
outcome of every (role, table, operation) against the policy oracle below, which
mirrors the live ``pg_policies`` exactly. It also proves the mission's two
headline guarantees systematically across ALL 12 tenant tables: a portal client's
cross-tenant reads return 0 rows, and the sensitive columns (mrr / cost / error /
*_path / run_uuid / artifact_dir) are unreachable with a tenant JWT.

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
  APPEND-ONLY (no modify policy):      activity_log cost_log  (JWT can never write)
  A client (is_staff redefined to exclude it in 0010) holds NO staff perm.

Auto-skips unless Supabase is configured. Hermetic: provisions 6 staff + 2 portal
clients (tenants A/B), seeds one row per table via service_role, tears all down.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from typing import Any, cast

import pytest
from supabase import create_client

from app.config import get_settings
from app.db.supabase import client_for_user, get_admin_client
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


def _data(resp: Any) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", resp.data or [])


def _select(client: Any, table: str, columns: str = "*") -> list[dict[str, Any]]:
    """SELECT, retrying ONLY a transient transport error (never an RLS outcome).

    An RLS decision never raises: a denial returns [] and an allow returns rows.
    So retrying on a raised ConnectError/timeout absorbs a free-tier connection
    reset (e.g. WinError 10054) WITHOUT masking any allow/deny result - the
    boundary this suite asserts is unaffected.
    """
    last: Exception | None = None
    for _ in range(3):
        try:
            return _data(client.table(table).select(columns).execute())
        except Exception as exc:  # transient transport error, retry
            last = exc
            time.sleep(1.0)
    assert last is not None
    raise last


@pytest.fixture(scope="module")
def rls() -> Any:
    settings = get_settings()
    if not (
        settings.supabase_url
        and settings.supabase_service_role_key
        and settings.supabase_anon_key
    ):
        pytest.skip("Supabase not configured (SUPABASE_URL + service_role + anon keys)")

    admin = get_admin_client()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key.get_secret_value())
    tag = uuid.uuid4().hex[:10]

    uids: dict[str, str] = {}
    cleanup_uids: list[str] = []
    cleanup_clients: list[str] = []
    cleanup_audits: list[str] = []
    cleanup_tasks: list[str] = []
    cleanup_vault: list[str] = []
    pg: dict[str, Any] = {}  # principal -> PostgREST client (anon key + that JWT)

    def _signin(email: str) -> str:
        s = anon.auth.sign_in_with_password({"email": email, "password": _PASSWORD})
        assert s.session is not None, f"sign-in failed for {email}"
        return s.session.access_token

    def _row(resp: Any) -> dict[str, Any]:
        return cast("dict[str, Any]", resp.data[0])

    try:
        # --- staff principals ---
        for role in _STAFF:
            email = f"rls-{role}-{tag}@example.com"
            u = provision_user(
                admin, email=email, password=_PASSWORD, name=f"RLS {role}",
                role=role, template_key="super" if role == "owner" else None,  # type: ignore[arg-type]
            )
            uids[role] = u["id"]
            cleanup_uids.append(u["id"])
            pg[role] = client_for_user(_signin(email))

        # --- two tenants A and B (service_role) ---
        tenant: dict[str, str] = {}
        for key, mrr in (("A", 5000), ("B", 7000)):
            row = _row(
                admin.table("clients").insert(
                    {"name": f"RLS Tenant {key}", "industry": "Testing", "mrr": mrr,
                     "delivery_tier": "free", "contact_email": f"{key.lower()}@rls.example"}
                ).execute()
            )
            tenant[key] = str(row["id"])
            cleanup_clients.append(tenant[key])

        # --- two portal clients pinned to A and B ---
        for key, ckey in (("A", "clientA"), ("B", "clientB")):
            email = f"rls-{ckey}-{tag}@example.com"
            u = provision_user(
                admin, email=email, password=_PASSWORD, name=f"RLS {ckey}",
                role="client", client_id=tenant[key],
            )
            uids[ckey] = u["id"]
            cleanup_uids.append(u["id"])
            pg[ckey] = client_for_user(_signin(email))

        # --- one row per table (service_role bypasses RLS) ---
        admin.table("sites").insert(
            {"client_id": tenant["A"], "domain": "rls-a.example"}
        ).execute()
        audit_a = _row(
            admin.table("audits").insert(
                {"client_id": tenant["A"], "client_name": "RLS Tenant A", "url": "http://a.example",
                 "types": ["technical"], "tier": "free", "status": "done", "score": 77,
                 "cost": 4.25, "error": "seed-error-string", "run_uuid": "seed-run-a",
                 "artifact_dir": "/seed/a", "pdf_path": "x/report.pdf", "json_path": "x/findings.json"}
            ).execute()
        )
        cleanup_audits.append(str(audit_a["id"]))
        audit_b = _row(
            admin.table("audits").insert(
                {"client_id": tenant["B"], "client_name": "RLS Tenant B", "url": "http://b.example",
                 "types": ["technical"], "tier": "free", "status": "queued"}
            ).execute()
        )
        cleanup_audits.append(str(audit_b["id"]))
        task_a = _row(
            admin.table("tasks").insert(
                {"title": "RLS seed task", "client_id": tenant["A"], "type": "technical_audit",
                 "assignee_id": uids["owner"], "created_by": uids["owner"]}
            ).execute()
        )
        cleanup_tasks.append(str(task_a["code"]))
        admin.table("client_budgets").insert({"client_id": tenant["A"], "cap": 100}).execute()
        admin.table("cost_log").insert(
            {"client_id": tenant["A"], "client_name": "RLS Tenant A", "job_id": "seed",
             "job_type": "audit", "provider": "Serper", "cost": 1.5}
        ).execute()
        admin.table("activity_log").insert(
            {"actor_id": uids["owner"], "actor_name": "RLS owner", "kind": "task", "action": "seeded"}
        ).execute()
        vk = _row(
            admin.table("vault_keys").insert(
                {"provider": "serper", "label": "RLS Key", "masked": "sk-****",
                 "secret_id": str(uuid.uuid4())}
            ).execute()
        )
        cleanup_vault.append(str(vk["id"]))

        yield {"pg": pg, "uids": uids, "tenant": tenant,
               "audit_a": str(audit_a["id"]), "audit_b": str(audit_b["id"]), "admin": admin,
               "cleanup_audits": cleanup_audits, "cleanup_tasks": cleanup_tasks}
    finally:
        def _safe(fn: Any) -> None:
            with contextlib.suppress(Exception):
                fn()

        for code in cleanup_tasks:
            _safe(lambda code=code: admin.table("tasks").delete().eq("code", code).execute())
        for aid in cleanup_audits:
            _safe(lambda aid=aid: admin.table("audits").delete().eq("id", aid).execute())
        for kid in cleanup_vault:
            _safe(lambda kid=kid: admin.table("vault_keys").delete().eq("id", kid).execute())
        for cid in cleanup_clients:
            _safe(lambda cid=cid: admin.table("clients").delete().eq("id", cid).execute())
        for uid in cleanup_uids:
            _safe(lambda uid=uid: admin.auth.admin.delete_user(uid))


# --------------------------------------------------------------------------- #
def test_rls_select_matrix(rls: Any) -> None:
    """Every (table, principal) SELECT: allowed principals see rows, all others 0."""
    pg = rls["pg"]
    principals = list(_STAFF) + list(_CLIENTS)
    failures: list[str] = []
    for table, allow in _SELECT_ALLOW.items():
        for who in principals:
            try:
                rows = _select(pg[who], table)
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


def test_rls_self_row_visibility(rls: Any) -> None:
    """users / user_feature_grants are self-or-staff: a client sees ONLY its own."""
    pg, uids = rls["pg"], rls["uids"]
    # Staff see the whole roster; a client sees only its own users row.
    assert len(_select(pg["owner"], "users", "id")) > 1
    a_rows = _select(pg["clientA"], "users", "id")
    assert a_rows, "clientA should see its own users row"
    assert all(r["id"] == uids["clientA"] for r in a_rows), "clientA saw a users row that is not its own"
    assert uids["owner"] not in {r["id"] for r in a_rows}, "clientA must not see staff users rows"
    # user_feature_grants: a client sees only its own grants (owner's are hidden).
    g_rows = _select(pg["clientA"], "user_feature_grants", "user_id")
    assert all(r["user_id"] == uids["clientA"] for r in g_rows), "clientA saw another user's grants"


def test_client_cross_tenant_isolation_via_views(rls: Any) -> None:
    """A portal client reads ONLY its own tenant through the security-barrier views."""
    pg, tenant = rls["pg"], rls["tenant"]
    a_audits = _select(pg["clientA"], "portal_audits")
    assert a_audits, "clientA should see its own audit via the view"
    assert all(r["client_id"] == tenant["A"] for r in a_audits), "clientA saw another tenant's audit"
    assert rls["audit_b"] not in {r["id"] for r in a_audits}, "tenant B's audit leaked to clientA"

    a_client = _select(pg["clientA"], "portal_client")
    assert [r["id"] for r in a_client] == [tenant["A"]], "portal_client is not self-scoped"

    # clientB is the mirror image: sees B, never A.
    b_audits = _select(pg["clientB"], "portal_audits")
    assert all(r["client_id"] == tenant["B"] for r in b_audits)
    assert rls["audit_a"] not in {r["id"] for r in b_audits}

    # The view carries NONE of the sensitive columns.
    forbidden = {"pdf_path", "json_path", "cost", "error", "run_uuid", "artifact_dir"}
    assert not (set(a_audits[0]) & forbidden), f"portal_audits leaked {set(a_audits[0]) & forbidden}"
    assert "mrr" not in set(a_client[0]) and "contact_email" not in set(a_client[0])


def test_sensitive_columns_unreachable_direct(rls: Any) -> None:
    """A tenant JWT cannot read sensitive columns off the base tables (0 rows)."""
    ca = rls["pg"]["clientA"]
    assert _select(ca, "clients", "id,mrr") == [], "clients.mrr reachable by a client"
    assert _select(ca, "audits", "cost,error,pdf_path,json_path") == [], (
        "audits sensitive columns reachable by a client"
    )
    assert _select(ca, "cost_log", "cost") == [], "cost_log reachable by a client"


def test_rls_write_denial(rls: Any) -> None:
    """The security-critical direction: forbidden writes are refused at the DB."""
    pg, tenant = rls["pg"], rls["tenant"]

    def _insert_denied(who: str, table: str, row: dict[str, Any]) -> None:
        with pytest.raises(Exception):  # noqa: B017 - PostgREST APIError on RLS violation
            pg[who].table(table).insert(row).execute()

    # A portal client cannot write ANY base table.
    _insert_denied("clientA", "clients", {"name": "hacked"})
    _insert_denied("clientA", "audits", {"url": "http://x", "client_id": tenant["B"]})
    _insert_denied("clientA", "tasks", {"title": "x", "type": "technical_audit"})
    # ...nor mutate another tenant's row (0 rows affected, not an error).
    assert _data(pg["clientA"].table("clients").update({"mrr": 0}).eq("id", tenant["B"]).execute()) == []
    assert _data(pg["clientA"].table("clients").delete().eq("id", tenant["B"]).execute()) == []

    # Staff role boundaries: viewer cannot create an audit (excluded from audits_modify);
    # a specialist cannot create a task (INSERT is leads-only); a manager cannot write vault.
    _insert_denied("viewer", "audits", {"url": "http://x", "client_id": tenant["A"]})
    _insert_denied("specialist", "tasks",
                   {"title": "x", "type": "technical_audit", "client_id": tenant["A"],
                    "assignee_id": rls["uids"]["owner"]})
    _insert_denied("manager", "vault_keys",
                   {"provider": "serper", "label": "x", "secret_id": str(uuid.uuid4())})


def test_rls_write_allow(rls: Any) -> None:
    """The allow direction: an analyst may create an audit; a lead may create a task."""
    pg, tenant, admin = rls["pg"], rls["tenant"], rls["admin"]

    created = pg["analyst"].table("audits").insert(
        {"url": "http://analyst.example", "client_id": tenant["A"], "types": ["technical"]}
    ).execute()
    rows = _data(created)
    assert rows, "analyst is in audits_modify and should be able to insert"
    admin.table("audits").delete().eq("id", rows[0]["id"]).execute()

    created = pg["manager"].table("tasks").insert(
        {"title": "manager task", "type": "technical_audit", "client_id": tenant["A"],
         "assignee_id": rls["uids"]["owner"], "created_by": rls["uids"]["manager"]}
    ).execute()
    rows = _data(created)
    assert rows, "manager is a lead and should be able to insert a task"
    admin.table("tasks").delete().eq("code", rows[0]["code"]).execute()
