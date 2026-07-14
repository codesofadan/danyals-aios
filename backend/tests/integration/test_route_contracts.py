"""End-to-end HTTP CONTRACT suite - the test class that would have caught the
empty-JWT critical bug (commit e53fc05).

Every case drives the REAL app (``create_app()`` under ``LifespanManager``, so the
JWKS cache + shared clients exist) over ``httpx.ASGITransport`` with a REAL
Supabase access token minted by the password grant - i.e. through the ACTUAL
route dependency graph, not a faked repo and not PostgREST-direct. It asserts
BOTH the HTTP status AND the response SHAPE (keys + structural types, derived from
each route's declared Pydantic ``response_model``, recursing into nested models)
for all 51 endpoints, including the negatives (specialist->POST /clients = 403,
client->GET /audits = 403, unauthenticated = 401).

Why this exists: units inject fake repos (never exercise the real token wiring)
and the other integration tests drive PostgREST directly (bypass the route graph),
so NO test ever hit HTTP -> route -> repo -> DB with a real token. On pre-e53fc05
code the RLS repo factories resolved before ``get_current_user`` set the token, so
``client_for_user("")`` -> PGRST301 -> 500 on 34 routes. The ``test_contract_matrix``
below re-hits every RLS-backed route as a real owner and asserts 200; it fails hard
on that regression class.

Hermetic: provisions its own principals + seed rows (service_role), overrides the
Celery enqueuer (no broker dependency) and the artifact store (a temp dir, so the
download 200-path is exercised without touching ``AUDIT_ARTIFACT_DIR``), restores
the org-wide cost singletons it writes, and tears everything down. Auto-skips
unless SUPABASE_URL + service_role + anon keys are configured and migrations
applied.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
import types as _types
import uuid
from pathlib import Path
from typing import Any, Literal, Union, cast, get_args, get_origin

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import BaseModel
from supabase import create_client

from app.config import get_settings
from app.db.supabase import get_admin_client
from app.main import create_app
from app.rbac.matrix import FeatureDef, PermissionDef
from app.routers.audits import get_artifact_store, get_audit_enqueuer
from app.schemas.activity import ActivityResponse
from app.schemas.audits import AuditResponse, AuditStatsResponse, PortalAuditResponse
from app.schemas.clients import ClientResponse, SiteResponse
from app.schemas.cost import (
    ClientBudgetResponse,
    CostEntryResponse,
    DialFeatureResponse,
    SpendStopResponse,
)
from app.schemas.health import HealthResponse, ReadyResponse
from app.schemas.identity import MemberResponse
from app.schemas.portal import ClientDashboard
from app.schemas.rbac import RoleView, TemplateView
from app.schemas.tasks import TaskResponse
from app.schemas.tiers import FeatureAreaResponse, TierClientResponse, TierResponse
from app.schemas.vault import VaultKeyResponse
from app.services.audit_artifacts import LocalArtifactStore
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration

# A public IP literal: the POST /audits SSRF guard resolves the host off-loop; an
# IP avoids DNS and never reaches a private range (reused from the portal test).
_PUBLIC_URL = "http://93.184.216.34"
_PASSWORD = "Passw0rd!contract-123"
_STAFF_ROLES = ("owner", "admin", "manager", "specialist", "viewer")


# --------------------------------------------------------------------------- #
# Shape lock: derive expected JSON keys + structural types from the response
# model and recurse into nested models. Catches a route that drifts from (or
# drops) its declared response_model.
# --------------------------------------------------------------------------- #
def _strip_optional(ann: Any) -> tuple[Any, bool]:
    origin = get_origin(ann)
    if origin is Union or origin is getattr(_types, "UnionType", None):
        args = get_args(ann)
        non_none = [a for a in args if a is not type(None)]
        allow_none = type(None) in args
        if len(non_none) == 1:
            return non_none[0], allow_none
        return ann, allow_none
    return ann, False


def _nested_model(ann: Any) -> tuple[type[BaseModel] | None, bool]:
    """(model, is_list) if ann is a BaseModel or list[BaseModel], else (None, False)."""
    ann, _ = _strip_optional(ann)
    origin = get_origin(ann)
    if origin in (list, tuple):
        for a in get_args(ann):
            a2, _ = _strip_optional(a)
            if isinstance(a2, type) and issubclass(a2, BaseModel):
                return a2, True
        return None, False
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann, False
    return None, False


def _expected_keys(model: type[BaseModel]) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        key = field.serialization_alias or field.alias or name
        keys[key] = field
    return keys


def _scalar_ok(val: Any, ann: Any) -> bool:
    """Whether a JSON scalar matches a simple annotation (gives the type check teeth).

    Catches enum drift (Literal) and int/bool/str/float confusion; lenient for Any.
    """
    if get_origin(ann) is Literal:
        return val in get_args(ann)
    if ann is bool:
        return isinstance(val, bool)
    if ann is int:
        return isinstance(val, int) and not isinstance(val, bool)
    if ann is float:
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if ann is str:
        return isinstance(val, str)
    return True  # Any / unknown annotation - stay lenient


def shape_errors(payload: Any, model: type[BaseModel], path: str = "") -> list[str]:
    """Return shape-mismatch messages (empty list = the payload matches ``model``)."""
    label = path or model.__name__
    if not isinstance(payload, dict):
        return [f"{label}: expected object, got {type(payload).__name__}"]
    errs: list[str] = []
    expected = _expected_keys(model)
    got, exp = set(payload), set(expected)
    if exp - got:
        errs.append(f"{label}: missing keys {sorted(exp - got)}")
    if got - exp:
        errs.append(f"{label}: unexpected keys {sorted(got - exp)}")
    for key, field in expected.items():
        if key not in payload:
            continue
        val = payload[key]
        cur = f"{label}.{key}"
        base_ann, allow_none = _strip_optional(field.annotation)
        if val is None:
            # A null is a violation UNLESS the field is genuinely Optional.
            if not allow_none:
                errs.append(f"{cur}: null for a required (non-Optional) field")
            continue
        sub, is_list = _nested_model(field.annotation)
        if sub is not None:
            if is_list:
                if not isinstance(val, list):
                    errs.append(f"{cur}: expected list, got {type(val).__name__}")
                else:
                    for i, item in enumerate(val):
                        errs.extend(shape_errors(item, sub, f"{cur}[{i}]"))
            else:
                errs.extend(shape_errors(val, sub, cur))
            continue
        origin = get_origin(base_ann)
        if origin in (list, tuple):
            if not isinstance(val, list):
                errs.append(f"{cur}: expected list, got {type(val).__name__}")
        elif origin is dict:
            if not isinstance(val, dict):
                errs.append(f"{cur}: expected object, got {type(val).__name__}")
        elif isinstance(val, (list, dict)):
            errs.append(f"{cur}: expected scalar, got {type(val).__name__}")
        elif not _scalar_ok(val, base_ann):
            errs.append(f"{cur}: value {val!r} does not match {base_ann}")
    return errs


# --------------------------------------------------------------------------- #
# HTTP helper: one request through the (already lifespan-started) app.
# --------------------------------------------------------------------------- #
async def _req(
    app: Any, method: str, path: str, token: str | None = None, json: Any | None = None
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as ac:
        return await ac.request(method, path, json=json)


def _body(resp: httpx.Response) -> Any:
    """``resp.json()`` typed as ``Any`` (httpx types it as a JSON union)."""
    return resp.json()


# --------------------------------------------------------------------------- #
# Session data: principals + seed rows. All setup uses the SYNC supabase client
# (service_role for seeds, anon for sign-in) so there is no async-fixture event-
# loop coupling; the async tests each open their own LifespanManager.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def env() -> Any:
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

    tokens: dict[str, str] = {}
    staff_uids: dict[str, str] = {}
    cleanup_uids: list[str] = []  # every auth user id to delete (principals + API-created)
    cleanup_clients: list[str] = []
    cleanup_audits: list[str] = []
    cleanup_tasks: list[str] = []  # task CODES (J-####)
    cleanup_vault: list[str] = []
    artifact_root = tempfile.mkdtemp(prefix="aios-contract-artifacts-")

    def _signin(email: str) -> str:
        session = anon.auth.sign_in_with_password({"email": email, "password": _PASSWORD})
        assert session.session is not None, f"sign-in failed for {email}"
        return session.session.access_token

    def _inserted(resp: Any) -> dict[str, Any]:
        """The first inserted row from a supabase insert (loosely typed .data)."""
        return cast("dict[str, Any]", resp.data[0])

    try:
        # --- staff principals (all 6 governance roles minus client) ---------
        for role in _STAFF_ROLES:
            email = f"contract-{role}-{tag}@example.com"
            row = provision_user(
                admin,
                email=email,
                password=_PASSWORD,
                name=f"Contract {role.title()}",
                role=role,  # type: ignore[arg-type]
                template_key="super" if role == "owner" else None,
            )
            staff_uids[role] = row["id"]
            cleanup_uids.append(row["id"])
            tokens[role] = _signin(email)

        # --- seed tenant T (service_role bypasses RLS) ----------------------
        client_row = (
            admin.table("clients")
            .insert(
                {
                    "name": "Contract Test Co",
                    "industry": "Testing",
                    "since_year": 2020,
                    "tier": "Starter",
                    "status": "trial",
                    "delivery_tier": "free",
                    "mrr": 1200,
                    "contact_name": "Jane Contact",
                    "contact_role": "CMO",
                    "contact_email": "jane@contract-test.example",
                    "contact_color": "#7B69EE",
                    "portal_admin": "jane@contract-test.example",
                    "portal_seats": 3,
                    "portal_two_fa": False,
                }
            )
            .execute()
        )
        tenant_id = str(_inserted(client_row)["id"])
        cleanup_clients.append(tenant_id)

        # --- seed site S ----------------------------------------------------
        site_row = (
            admin.table("sites")
            .insert({"client_id": tenant_id, "domain": "contract-test.example", "cms_type": "wordpress"})
            .execute()
        )
        site_id = str(_inserted(site_row)["id"])

        # --- portal client principal (tenant pinned) ------------------------
        client_email = f"contract-client-{tag}@example.com"
        client_user = provision_user(
            admin,
            email=client_email,
            password=_PASSWORD,
            name="Contract Client",
            role="client",
            client_id=tenant_id,
        )
        cleanup_uids.append(client_user["id"])
        tokens["client"] = _signin(client_email)

        # --- seed audit A (queued; no artifacts -> exercises the 404 branch) -
        audit_a = (
            admin.table("audits")
            .insert(
                {
                    "client_id": tenant_id,
                    "client_name": "Contract Test Co",
                    "url": _PUBLIC_URL,
                    "types": ["technical", "actionable"],
                    "tier": "free",
                    "status": "queued",
                }
            )
            .execute()
        )
        audit_a_id = str(_inserted(audit_a)["id"])
        cleanup_audits.append(audit_a_id)

        # --- seed audit A2 (done + artifacts on disk -> the 200 download path)
        audit_a2_id = str(uuid.uuid4())  # precomputed so pdf/json keys embed it
        (artifact_dir := Path(artifact_root) / audit_a2_id).mkdir(parents=True, exist_ok=True)
        (artifact_dir / "report.pdf").write_bytes(b"%PDF-1.4 contract-test\n%%EOF\n")
        (artifact_dir / "findings.json").write_text('{"findings": []}', encoding="utf-8")
        admin.table("audits").insert(
            {
                "id": audit_a2_id,
                "client_id": tenant_id,
                "client_name": "Contract Test Co",
                "url": _PUBLIC_URL,
                "types": ["technical"],
                "tier": "free",
                "status": "done",
                "score": 88,
                "scores": {"overall": 88, "technical": 90},
                "runtime_seconds": 372,
                "pdf_path": f"{audit_a2_id}/report.pdf",
                "json_path": f"{audit_a2_id}/findings.json",
            }
        ).execute()
        cleanup_audits.append(audit_a2_id)

        # --- seed task J (content_sprint, assigned to the specialist) -------
        task_row = (
            admin.table("tasks")
            .insert(
                {
                    "title": "Contract seed task",
                    "client_id": tenant_id,
                    "client_name": "Contract Test Co",
                    "type": "content_sprint",
                    "assignee_id": staff_uids["specialist"],
                    "created_by": staff_uids["owner"],
                    "priority": "med",
                    "status": "todo",
                }
            )
            .execute()
        )
        task_code = str(_inserted(task_row)["code"])
        cleanup_tasks.append(task_code)

        # --- seed one cost_log + one activity_log row so GET /cost/log and
        #     GET /activity validate CostEntryResponse / ActivityResponse against
        #     a REAL item (both tables are otherwise empty in this suite). --------
        cost_log_id = str(
            _inserted(
                admin.table("cost_log").insert(
                    {"client_id": tenant_id, "client_name": "Contract Test Co", "job_id": "seed",
                     "job_type": "audit", "provider": "Serper", "cost": 1.5, "cached": False}
                ).execute()
            )["id"]
        )
        admin.table("activity_log").insert(
            {"actor_id": staff_uids["owner"], "actor_name": "Contract Owner", "actor_init": "CO",
             "kind": "audit", "action": "seeded the contract suite", "target": "contract"}
        ).execute()

        # --- the app under test: real settings (NO conftest override), Celery
        #     enqueuer stubbed, artifact store pointed at the temp dir. --------
        app = create_app()
        app.dependency_overrides[get_audit_enqueuer] = lambda: (lambda _audit_id: None)
        app.dependency_overrides[get_artifact_store] = lambda: LocalArtifactStore(artifact_root)

        ctx = {
            "app": app,
            "admin": admin,
            "tokens": tokens,
            "staff_uids": staff_uids,
            "ids": {
                "tenant": tenant_id,
                "site": site_id,
                "audit_queued": audit_a_id,
                "audit_done": audit_a2_id,
                "task": task_code,
                "missing": str(uuid.uuid4()),
            },
            "tag": tag,
            "cost_log_id": cost_log_id,
            "cleanup_uids": cleanup_uids,
            "cleanup_clients": cleanup_clients,
            "cleanup_audits": cleanup_audits,
            "cleanup_tasks": cleanup_tasks,
            "cleanup_vault": cleanup_vault,
        }
        yield ctx
    finally:
        # Teardown in FK-safe order. audits/tasks SET NULL on client delete (they
        # orphan, not cascade) so remove them explicitly; clients delete cascades
        # sites/budgets/portal-user public.users rows; deleting an auth user
        # cascades its public.users row (+ grants).
        def _safe(fn: Any) -> None:
            with contextlib.suppress(Exception):  # best-effort cleanup
                fn()

        for code in cleanup_tasks:
            _safe(lambda code=code: admin.table("tasks").delete().eq("code", code).execute())
        for aid in cleanup_audits:
            _safe(lambda aid=aid: admin.table("audits").delete().eq("id", aid).execute())
        for kid in cleanup_vault:
            _safe(lambda kid=kid: admin.table("vault_keys").delete().eq("id", kid).execute())
        # activity_log is append-only; every Group B mutation appends a row via
        # record_activity. Remove the seed row + everything the test actors wrote
        # so reruns do not accumulate orphan feed entries.
        _safe(lambda: admin.table("cost_log").delete().eq("id", cost_log_id).execute())
        _safe(lambda: admin.table("activity_log").delete().in_("actor_id", cleanup_uids).execute())
        for cid in cleanup_clients:
            _safe(lambda cid=cid: admin.table("clients").delete().eq("id", cid).execute())
        for uid in cleanup_uids:
            _safe(lambda uid=uid: admin.auth.admin.delete_user(uid))
        shutil.rmtree(artifact_root, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Group A: the guard + shape matrix. Every endpoint x a 2xx principal, a denied
# principal (-> 403), and unauth (-> 401); reads also assert the response shape.
# One lifespan, all cases, accumulate every violation so a single run reports
# the full contract state.
# --------------------------------------------------------------------------- #
def _matrix_cases(env: Any) -> list[dict[str, Any]]:
    i = env["ids"]
    t, missing = i["tenant"], i["missing"]
    v = "/api/v1"

    def c(
        cid: str,
        principal: str | None,
        method: str,
        path: str,
        status: Any,
        *,
        shape: type[BaseModel] | None = None,
        is_list: bool = False,
        body: Any | None = None,
    ) -> dict[str, Any]:
        return {
            "id": cid,
            "principal": principal,
            "method": method,
            "path": path,
            "status": status,
            "shape": shape,
            "is_list": is_list,
            "body": body,
        }

    valid_client_body = {"cn": "Neg Co"}
    valid_site_body = {"domain": "neg.example"}
    valid_portal_user = {"email": f"neg-{env['tag']}@example.com", "name": "Neg", "password": _PASSWORD}
    valid_audit_body = {"client_id": t, "url": _PUBLIC_URL, "tier": "Free", "types": ["technical"]}
    valid_task_body = {
        "title": "Neg",
        "client_id": t,
        "type": "Technical Audit",
        "assignee_id": env["staff_uids"]["owner"],
    }

    cases: list[dict[str, Any]] = [
        # --- health (public) ---
        c("health.get.owner", "owner", "GET", "/health", 200, shape=HealthResponse),
        c("health.get.unauth", None, "GET", "/health", 200, shape=HealthResponse),
        c("ready.get.owner", "owner", "GET", "/health/ready", (200, 503), shape=ReadyResponse),
        c("ready.get.unauth", None, "GET", "/health/ready", (200, 503), shape=ReadyResponse),
        # --- rbac reference (CurrentUserDep) ---
        c("rbac.features.owner", "owner", "GET", f"{v}/rbac/features", 200, shape=FeatureDef, is_list=True),
        c("rbac.features.unauth", None, "GET", f"{v}/rbac/features", 401),
        c("rbac.features.client", "client", "GET", f"{v}/rbac/features", 200, shape=FeatureDef, is_list=True),
        c("rbac.permissions.owner", "owner", "GET", f"{v}/rbac/permissions", 200, shape=PermissionDef, is_list=True),
        c("rbac.roles.owner", "owner", "GET", f"{v}/rbac/roles", 200, shape=RoleView, is_list=True),
        c("rbac.templates.owner", "owner", "GET", f"{v}/rbac/templates", 200, shape=TemplateView, is_list=True),
        # --- admin users (manage_team) ---
        c("admin.users.owner", "owner", "GET", f"{v}/admin/users", 200, shape=MemberResponse, is_list=True),
        c("admin.users.specialist", "specialist", "GET", f"{v}/admin/users", 403),
        c("admin.users.unauth", None, "GET", f"{v}/admin/users", 401),
        c("admin.users.post.specialist", "specialist", "POST", f"{v}/admin/users", 403,
          body={"email": "x@y.z", "name": "X", "password": _PASSWORD, "role": "viewer"}),
        # --- clients ---
        c("clients.list.owner", "owner", "GET", f"{v}/clients", 200, shape=ClientResponse, is_list=True),
        c("clients.list.unauth", None, "GET", f"{v}/clients", 401),
        c("clients.list.client", "client", "GET", f"{v}/clients", 200, shape=ClientResponse, is_list=True),
        c("clients.post.specialist", "specialist", "POST", f"{v}/clients", 403, body=valid_client_body),
        c("clients.get.owner", "owner", "GET", f"{v}/clients/{t}", 200, shape=ClientResponse),
        c("clients.get.missing", "owner", "GET", f"{v}/clients/{missing}", 404),
        c("clients.patch.specialist", "specialist", "PATCH", f"{v}/clients/{t}", 403, body={"mrr": 1}),
        c("clients.delete.specialist", "specialist", "DELETE", f"{v}/clients/{missing}", 403),
        c("clients.sites.owner", "owner", "GET", f"{v}/clients/{t}/sites", 200, shape=SiteResponse, is_list=True),
        c("clients.sites.post.specialist", "specialist", "POST", f"{v}/clients/{t}/sites", 403, body=valid_site_body),
        c("clients.portalusers.admin", "admin", "POST", f"{v}/clients/{t}/portal-users", 403, body=valid_portal_user),
        c("sites.delete.specialist", "specialist", "DELETE", f"{v}/sites/{missing}", 403),
        # --- vault ---
        c("vault.list.owner", "owner", "GET", f"{v}/vault/keys", 200, shape=VaultKeyResponse, is_list=True),
        c("vault.list.manager", "manager", "GET", f"{v}/vault/keys", 403),
        c("vault.list.unauth", None, "GET", f"{v}/vault/keys", 401),
        c("vault.post.manager", "manager", "POST", f"{v}/vault/keys", 403,
          body={"provider": "serper", "label": "x", "secret": "s"}),
        c("vault.rotate.manager", "manager", "POST", f"{v}/vault/keys/{missing}/rotate", 403, body={"secret": "s"}),
        c("vault.reveal.admin", "admin", "GET", f"{v}/vault/keys/{missing}/reveal", 403),
        # --- activity ---
        c("activity.owner", "owner", "GET", f"{v}/activity", 200, shape=ActivityResponse, is_list=True),
        c("activity.unauth", None, "GET", f"{v}/activity", 401),
        c("activity.client", "client", "GET", f"{v}/activity", 200, shape=ActivityResponse, is_list=True),
        # --- cost ---
        c("cost.budgets.owner", "owner", "GET", f"{v}/cost/budgets", 200, shape=ClientBudgetResponse, is_list=True),
        c("cost.budgets.put.specialist", "specialist", "PUT", f"{v}/cost/budgets/{t}", 403, body={"cap": 100}),
        c("cost.dial.owner", "owner", "GET", f"{v}/cost/dial", 200, shape=DialFeatureResponse, is_list=True),
        c("cost.dial.put.manager", "manager", "PUT", f"{v}/cost/dial/keywords", 403, body={"mode": "off"}),
        c("cost.log.owner", "owner", "GET", f"{v}/cost/log", 200, shape=CostEntryResponse, is_list=True),
        c("cost.spendstop.owner", "owner", "GET", f"{v}/cost/spend-stop", 200, shape=SpendStopResponse),
        c("cost.spendstop.put.manager", "manager", "PUT", f"{v}/cost/spend-stop", 403, body={"halted": True}),
        # --- tiers ---
        c("tiers.owner", "owner", "GET", f"{v}/tiers", 200, shape=TierResponse, is_list=True),
        c("tiers.client", "client", "GET", f"{v}/tiers", 200, shape=TierResponse, is_list=True),
        c("tiers.areas.owner", "owner", "GET", f"{v}/tiers/feature-areas", 200, shape=FeatureAreaResponse, is_list=True),
        c("tiers.clients.owner", "owner", "GET", f"{v}/tiers/clients", 200, shape=TierClientResponse, is_list=True),
        c("tiers.clients.put.specialist", "specialist", "PUT", f"{v}/tiers/clients/{t}", 403, body={"tier": "free"}),
        # --- audits (staff, view_reports; client is 403'd out) ---
        c("audits.list.owner", "owner", "GET", f"{v}/audits", 200, shape=AuditResponse, is_list=True),
        c("audits.list.viewer", "viewer", "GET", f"{v}/audits", 200, shape=AuditResponse, is_list=True),
        c("audits.list.client", "client", "GET", f"{v}/audits", 403),
        c("audits.list.unauth", None, "GET", f"{v}/audits", 401),
        c("audits.stats.owner", "owner", "GET", f"{v}/audits/stats", 200, shape=AuditStatsResponse),
        c("audits.stats.client", "client", "GET", f"{v}/audits/stats", 403),
        c("audits.get.owner", "owner", "GET", f"{v}/audits/{i['audit_queued']}", 200, shape=AuditResponse),
        c("audits.get.missing", "owner", "GET", f"{v}/audits/{missing}", 404),
        c("audits.get.client", "client", "GET", f"{v}/audits/{i['audit_queued']}", 403),
        c("audits.pdf.client", "client", "GET", f"{v}/audits/{i['audit_done']}/report.pdf", 403),
        c("audits.json.client", "client", "GET", f"{v}/audits/{i['audit_done']}/findings.json", 403),
        c("audits.post.viewer", "viewer", "POST", f"{v}/audits", 403, body=valid_audit_body),
        c("audits.post.unauth", None, "POST", f"{v}/audits", 401, body=valid_audit_body),
        # --- tasks (staff) ---
        c("tasks.list.owner", "owner", "GET", f"{v}/tasks", 200, shape=TaskResponse, is_list=True),
        c("tasks.list.client", "client", "GET", f"{v}/tasks", 403),
        c("tasks.list.unauth", None, "GET", f"{v}/tasks", 401),
        c("tasks.post.specialist", "specialist", "POST", f"{v}/tasks", 403, body=valid_task_body),
        c("tasks.advance.nonassignee", "viewer", "POST", f"{v}/tasks/{i['task']}/advance", 403),
        c("tasks.advance.client", "client", "POST", f"{v}/tasks/{i['task']}/advance", 403),
        c("tasks.review.specialist", "specialist", "POST", f"{v}/tasks/{i['task']}/review", 403, body={"action": "approve"}),
        c("tasks.patch.specialist", "specialist", "PATCH", f"{v}/tasks/{i['task']}", 403, body={"priority": "high"}),
        # --- me (staff) ---
        c("me.owner", "owner", "GET", f"{v}/me", 200, shape=MemberResponse),
        c("me.client", "client", "GET", f"{v}/me", 403),
        c("me.unauth", None, "GET", f"{v}/me", 401),
        # --- portal (client only; staff 403'd out) ---
        c("portal.dashboard.client", "client", "GET", f"{v}/portal/dashboard", 200, shape=ClientDashboard),
        c("portal.dashboard.owner", "owner", "GET", f"{v}/portal/dashboard", 403),
        c("portal.dashboard.unauth", None, "GET", f"{v}/portal/dashboard", 401),
        c("portal.audits.client", "client", "GET", f"{v}/portal/audits", 200, shape=PortalAuditResponse, is_list=True),
        c("portal.audits.owner", "owner", "GET", f"{v}/portal/audits", 403),
        c("portal.audit.get.client", "client", "GET", f"{v}/portal/audits/{i['audit_done']}", 200, shape=PortalAuditResponse),
        c("portal.audit.get.missing", "client", "GET", f"{v}/portal/audits/{missing}", 404),
        c("portal.audit.get.owner", "owner", "GET", f"{v}/portal/audits/{i['audit_done']}", 403),
        c("portal.pdf.owner", "owner", "GET", f"{v}/portal/audits/{i['audit_done']}/report.pdf", 403),
        c("portal.json.owner", "owner", "GET", f"{v}/portal/audits/{i['audit_done']}/findings.json", 403),
        c("portal.post.owner", "owner", "POST", f"{v}/portal/audits", 403, body={"url": _PUBLIC_URL}),
    ]
    return cases


async def test_contract_matrix(env: Any) -> None:
    """Every endpoint x role: assert HTTP status, and response shape on 2xx reads.

    Re-hits every RLS-backed route as a real owner -> would 500 on pre-e53fc05.
    """
    app = env["app"]
    failures: list[str] = []

    def _matches(resp: httpx.Response, exp: Any) -> bool:
        return resp.status_code in exp if isinstance(exp, tuple) else resp.status_code == exp

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            for case in _matrix_cases(env):
                token = env["tokens"].get(case["principal"]) if case["principal"] else None
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                exp = case["status"]
                # Bounded retry ONLY on a transient upstream 5xx when we expected a
                # non-5xx. This suite makes ~85 sequential cross-region round-trips
                # to a free-tier Supabase; a connection reset / timeout surfaces as
                # a 500 through the generic error envelope (observed: WinError 10054).
                # A DETERMINISTIC 5xx - the empty-JWT class - returns 5xx on EVERY
                # attempt, so it still fails here (proven: reverting the repo-auth
                # fix keeps clients.list.owner at 500 across all retries). A wrong
                # NON-5xx status (a broken guard / contract drift) is never retried
                # -> reported immediately. The only thing absorbed is a self-healing
                # 5xx->2xx, an acceptable, documented trade for a reliable net.
                resp = await ac.request(case["method"], case["path"], headers=headers, json=case["body"])
                for _ in range(2):
                    if _matches(resp, exp) or resp.status_code < 500:
                        break
                    await asyncio.sleep(1.5)
                    resp = await ac.request(case["method"], case["path"], headers=headers, json=case["body"])
                who = case["principal"] or "unauth"
                if not _matches(resp, exp):
                    failures.append(
                        f"[{case['id']}] {who} {case['method']} {case['path']}: "
                        f"status {resp.status_code} != {exp}; body={resp.text[:200]}"
                    )
                    continue
                if case["shape"] is not None and 200 <= resp.status_code < 300:
                    payload = _body(resp)
                    if case["is_list"]:
                        if not isinstance(payload, list):
                            failures.append(f"[{case['id']}] expected a list body, got {type(payload).__name__}")
                        else:
                            for item in payload:
                                failures.extend(f"[{case['id']}] {e}" for e in shape_errors(item, case["shape"]))
                    else:
                        failures.extend(f"[{case['id']}] {e}" for e in shape_errors(payload, case["shape"]))
    assert not failures, "CONTRACT VIOLATIONS:\n" + "\n".join(failures)


# --------------------------------------------------------------------------- #
# Group B: mutation happy-paths + special branches, on THROWAWAY rows (never the
# Group A seed). Each opens its own lifespan.
# --------------------------------------------------------------------------- #
async def test_clients_crud_lifecycle(env: Any) -> None:
    app, tok = env["app"], env["tokens"]["owner"]
    async with LifespanManager(app):
        r = await _req(app, "POST", "/api/v1/clients", tok,
                       {"cn": "Throwaway Co", "industry": "QA", "mrr": 500})
        assert r.status_code == 201, r.text
        assert not shape_errors(_body(r), ClientResponse)
        cid = _body(r)["id"]
        env["cleanup_clients"].append(cid)

        r = await _req(app, "PATCH", f"/api/v1/clients/{cid}", tok, {"mrr": 999})
        assert r.status_code == 200, r.text
        assert _body(r)["mrr"] == 999
        assert not shape_errors(_body(r), ClientResponse)

        r = await _req(app, "POST", f"/api/v1/clients/{cid}/sites", tok, {"domain": "throwaway.example"})
        assert r.status_code == 201, r.text
        assert not shape_errors(_body(r), SiteResponse)
        sid = _body(r)["id"]

        r = await _req(app, "DELETE", f"/api/v1/sites/{sid}", tok)
        assert r.status_code == 204, r.text

        r = await _req(app, "DELETE", f"/api/v1/clients/{cid}", tok)
        assert r.status_code == 204, r.text


async def test_admin_user_create_and_escalation_guard(env: Any) -> None:
    app = env["app"]
    email = f"contract-made-{env['tag']}@example.com"
    async with LifespanManager(app):
        r = await _req(app, "POST", "/api/v1/admin/users", env["tokens"]["owner"],
                       {"email": email, "name": "Made By API", "password": _PASSWORD, "role": "viewer"})
        assert r.status_code == 201, r.text
        assert not shape_errors(_body(r), MemberResponse)
        env["cleanup_uids"].append(_body(r)["id"])

        # An admin may NOT mint an owner/admin (handler-layer privilege guard).
        r = await _req(app, "POST", "/api/v1/admin/users", env["tokens"]["admin"],
                       {"email": f"esc-{env['tag']}@example.com", "name": "Esc",
                        "password": _PASSWORD, "role": "owner"})
        assert r.status_code == 403, r.text


async def test_portal_user_creation(env: Any) -> None:
    app, t = env["app"], env["ids"]["tenant"]
    email = f"contract-portal-{env['tag']}@example.com"
    async with LifespanManager(app):
        r = await _req(app, "POST", f"/api/v1/clients/{t}/portal-users", env["tokens"]["owner"],
                       {"email": email, "name": "Portal Login", "password": _PASSWORD})
        assert r.status_code == 201, r.text
        assert not shape_errors(_body(r), MemberResponse)
        env["cleanup_uids"].append(_body(r)["id"])


async def test_vault_lifecycle(env: Any) -> None:
    app, owner, admin_tok = env["app"], env["tokens"]["owner"], env["tokens"]["admin"]
    async with LifespanManager(app):
        r = await _req(app, "POST", "/api/v1/vault/keys", owner,
                       {"provider": "serper", "label": "Contract Key", "secret": "sk-original-123"})
        assert r.status_code == 201, r.text
        body = _body(r)
        assert not shape_errors(body, VaultKeyResponse)
        assert body["secret"] == "", "a create/list must never echo the raw secret"
        kid = body["id"]
        env["cleanup_vault"].append(kid)

        r = await _req(app, "GET", "/api/v1/vault/keys", owner)
        assert r.status_code == 200
        assert any(k["id"] == kid and k["masked"] and k["secret"] == "" for k in _body(r))

        r = await _req(app, "POST", f"/api/v1/vault/keys/{kid}/rotate", owner, {"secret": "sk-rotated-456"})
        assert r.status_code == 200, r.text

        r = await _req(app, "GET", f"/api/v1/vault/keys/{kid}/reveal", owner)
        assert r.status_code == 200, r.text
        assert _body(r)["secret"] == "sk-rotated-456"

        # reveal is owner-only: an admin is 403'd.
        r = await _req(app, "GET", f"/api/v1/vault/keys/{kid}/reveal", admin_tok)
        assert r.status_code == 403, r.text


async def test_cost_writes_with_restore(env: Any) -> None:
    app, owner = env["app"], env["tokens"]["owner"]
    async with LifespanManager(app):
        dial = {f["key"]: f["mode"] for f in _body(await _req(app, "GET", "/api/v1/cost/dial", owner))}
        ss = _body(await _req(app, "GET", "/api/v1/cost/spend-stop", owner))
        orig_keywords, orig_stop, orig_halt = dial["keywords"], ss["dailyStop"], ss["halted"]
        t = env["ids"]["tenant"]
        try:
            r = await _req(app, "PUT", "/api/v1/cost/dial/keywords", owner, {"mode": "api"})
            assert r.status_code == 200, r.text
            assert _body(r)["mode"] == "api"

            r = await _req(app, "PUT", "/api/v1/cost/spend-stop", owner, {"daily_stop": 42.0, "halted": True})
            assert r.status_code == 200, r.text
            assert not shape_errors(_body(r), SpendStopResponse)

            r = await _req(app, "GET", "/api/v1/cost/spend-stop", owner)
            assert _body(r)["dailyStop"] == 42.0 and _body(r)["halted"] is True

            # PUT budget (happy path) validates ClientBudgetResponse against a real row.
            r = await _req(app, "PUT", f"/api/v1/cost/budgets/{t}", owner, {"cap": 250})
            assert r.status_code == 200, r.text
            assert not shape_errors(_body(r), ClientBudgetResponse)
            assert _body(r)["cap"] == 250
        finally:
            # Restore the org-wide singletons this test mutated + drop the budget row.
            await _req(app, "PUT", "/api/v1/cost/dial/keywords", owner, {"mode": orig_keywords})
            await _req(app, "PUT", "/api/v1/cost/spend-stop", owner, {"daily_stop": orig_stop, "halted": orig_halt})
            env["admin"].table("client_budgets").delete().eq("client_id", t).execute()


async def test_staff_audit_create_and_tier_update(env: Any) -> None:
    """Staff run-audit (POST /audits->201) + delivery-tier update (PUT /tiers/clients->200)."""
    app, owner, t = env["app"], env["tokens"]["owner"], env["ids"]["tenant"]
    async with LifespanManager(app):
        r = await _req(app, "POST", "/api/v1/audits", owner,
                       {"client_id": t, "url": _PUBLIC_URL, "tier": "Free", "types": ["technical"]})
        assert r.status_code == 201, r.text
        body = _body(r)
        assert not shape_errors(body, AuditResponse)
        assert body["status"] == "queued" and body["tier"] == "Free"
        env["cleanup_audits"].append(body["id"])

        try:
            r = await _req(app, "PUT", f"/api/v1/tiers/clients/{t}", owner, {"tier": "semi"})
            assert r.status_code == 200, r.text
            assert not shape_errors(_body(r), TierClientResponse)
            assert _body(r)["tier"] == "semi"
        finally:
            # Restore delivery tier: the portal Paid-gate test depends on 'free'.
            await _req(app, "PUT", f"/api/v1/tiers/clients/{t}", owner, {"tier": "free"})


async def test_task_lifecycle_through_review_gate(env: Any) -> None:
    app, t = env["app"], env["ids"]["tenant"]
    owner, specialist = env["tokens"]["owner"], env["tokens"]["specialist"]
    async with LifespanManager(app):
        r = await _req(app, "POST", "/api/v1/tasks", owner,
                       {"title": "Contract lifecycle", "client_id": t, "type": "Content Sprint",
                        "assignee_id": env["staff_uids"]["specialist"], "priority": "high"})
        assert r.status_code == 201, r.text
        assert not shape_errors(_body(r), TaskResponse)
        code = _body(r)["id"]
        env["cleanup_tasks"].append(code)
        assert _body(r)["status"] == "todo"

        # Assignee advances todo -> in_progress -> review (content_sprint routes to review).
        r = await _req(app, "POST", f"/api/v1/tasks/{code}/advance", specialist)
        assert r.status_code == 200 and _body(r)["status"] == "in_progress", r.text
        r = await _req(app, "POST", f"/api/v1/tasks/{code}/advance", specialist)
        assert r.status_code == 200 and _body(r)["status"] == "review", r.text

        # A non-lead cannot leave `review` (the sign-off gate is lead-only) -> 409.
        r = await _req(app, "POST", f"/api/v1/tasks/{code}/advance", specialist)
        assert r.status_code == 409, r.text

        # A lead signs off review -> done.
        r = await _req(app, "POST", f"/api/v1/tasks/{code}/review", owner, {"action": "approve"})
        assert r.status_code == 200 and _body(r)["status"] == "done", r.text

        # Lead PATCH (reassign/repriority) is allowed even post-review.
        r = await _req(app, "PATCH", f"/api/v1/tasks/{code}", owner, {"priority": "low"})
        assert r.status_code == 200 and _body(r)["priority"] == "low", r.text


async def test_artifact_downloads(env: Any) -> None:
    app, i = env["app"], env["ids"]
    owner, client = env["tokens"]["owner"], env["tokens"]["client"]
    async with LifespanManager(app):
        # Staff download of the seeded `done` audit -> 200 with the right media type.
        r = await _req(app, "GET", f"/api/v1/audits/{i['audit_done']}/report.pdf", owner)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        r = await _req(app, "GET", f"/api/v1/audits/{i['audit_done']}/findings.json", owner)
        assert r.status_code == 200 and r.headers["content-type"] == "application/json", r.text

        # The queued audit has no artifacts -> 404 (artifact-absent branch).
        r = await _req(app, "GET", f"/api/v1/audits/{i['audit_queued']}/report.pdf", owner)
        assert r.status_code == 404, r.text

        # The portal client downloads ITS OWN audit -> 200 (ownership via the view).
        r = await _req(app, "GET", f"/api/v1/portal/audits/{i['audit_done']}/report.pdf", client)
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), r.text
        r = await _req(app, "GET", f"/api/v1/portal/audits/{i['audit_done']}/findings.json", client)
        assert r.status_code == 200, r.text

        # A foreign/unknown id via the portal -> 404 (not owned).
        r = await _req(app, "GET", f"/api/v1/portal/audits/{i['missing']}/report.pdf", client)
        assert r.status_code == 404, r.text


async def test_portal_audit_create_and_paid_gate(env: Any) -> None:
    app, client = env["app"], env["tokens"]["client"]
    async with LifespanManager(app):
        r = await _req(app, "POST", "/api/v1/portal/audits", client,
                       {"url": _PUBLIC_URL, "tier": "Free", "types": ["technical"]})
        assert r.status_code == 201, r.text
        assert not shape_errors(_body(r), PortalAuditResponse)
        env["cleanup_audits"].append(_body(r)["id"])

        # The seed tenant is delivery_tier='free' -> a Paid run is refused (D5).
        r = await _req(app, "POST", "/api/v1/portal/audits", client,
                       {"url": _PUBLIC_URL, "tier": "Paid", "types": ["local"]})
        assert r.status_code == 403, r.text


async def test_validation_contract_422(env: Any) -> None:
    """Authorized principal + malformed body -> 422 (guard passes, body fails)."""
    app, owner, t = env["app"], env["tokens"]["owner"], env["ids"]["tenant"]
    async with LifespanManager(app):
        for label, method, path, body in [
            ("clients.missing.cn", "POST", "/api/v1/clients", {"industry": "x"}),
            ("audits.missing.client_id", "POST", "/api/v1/audits", {"url": _PUBLIC_URL}),
            ("tasks.bad.type", "POST", "/api/v1/tasks",
             {"title": "x", "client_id": t, "type": "Bogus Type", "assignee_id": env["staff_uids"]["owner"]}),
            ("budget.negative.cap", "PUT", f"/api/v1/cost/budgets/{t}", {"cap": -5}),
        ]:
            r = await _req(app, method, path, owner, body)
            assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}: {r.text[:200]}"
