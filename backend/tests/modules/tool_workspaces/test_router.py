"""The nine workspace routes: the access gates + the wire shape + the no-leak sweep.

No DB, no network, no Celery: every repo is an in-memory fake injected through
``dependency_overrides``, and the feature-grant lookup (the one DB read inside
``require_feature``) is monkeypatched so the REAL ``feature_allows`` logic still runs.

Three gates stack on every route, and each is pinned INDEPENDENTLY - a test that only
ever walked the happy path would not notice one of them vanishing:

1. auth          - swept app-wide by ``tests/test_route_auth_guard.py``; re-pinned for
                   these 9 routes below.
2. the tool's OWN feature grant - and pinned to be the RIGHT one per route: these nine
   routes are the only place in the app where nine different feature keys sit on nine
   sibling routes, so a copy-paste of the wrong key is the live risk.
3. view_reports on every read, plus manage_vault on key_vault ONLY (mirroring the 0004
   RLS select policy + the vault router).

The ``client_id`` leak sweep runs over ALL NINE routes: every fake row below carries an
unmistakable client_id precisely so the sweep has something to catch.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.audits_repo import get_audits_repo
from app.db.clients_repo import get_clients_repo
from app.db.content_repo import get_content_repo
from app.db.offpage_repo import get_offpage_repo
from app.db.reports_repo import get_reports_repo
from app.db.tasks_repo import get_tasks_repo
from app.db.vault_repo import get_vault_repo
from app.modules.tool_workspaces import service as service_mod
from app.modules.tool_workspaces.router import get_roster_reader
from app.services.team_metrics import MemberMetrics, get_team_metrics

pytestmark = pytest.mark.unit

# The module's own source dir (taken off the service module - the package re-exports
# ``router`` as the APIRouter, so that name does not resolve to the module).
_MODULE_DIR = Path(inspect.getfile(service_mod)).parent

# The internal id that must never reach a response body, planted in every fake row.
_SECRET_CLIENT_ID = "cl-SECRET-DO-NOT-LEAK"

# (tool_key, path) for every route this module publishes. tool_key is BOTH the RBAC
# feature key and the lib/tools.ts EXTRAS key - they are the same string by design.
_ROUTES: list[tuple[str, str]] = [
    ("technical_audit", "/api/v1/technical-audit/workspace"),
    ("backlink_manager", "/api/v1/backlink-manager/workspace"),
    ("content_pipeline", "/api/v1/content-pipeline/workspace"),
    ("publishing", "/api/v1/publishing/workspace"),
    ("reporting", "/api/v1/reporting/workspace"),
    ("task_board", "/api/v1/task-board/workspace"),
    ("client_setup", "/api/v1/client-setup/workspace"),
    ("key_vault", "/api/v1/key-vault/workspace"),
    ("team_access", "/api/v1/team-access/workspace"),
]
_KEYS = [k for k, _p in _ROUTES]
_PATHS = [p for _k, p in _ROUTES]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope (invariant #5)."""
    return str(resp.json()["error"]["message"])


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


# --------------------------------------------------------------------------- #
# The fakes - one per shared repo these adapters read. Every row carries
# _SECRET_CLIENT_ID so the leak sweep has a real target.
# --------------------------------------------------------------------------- #
class _FakeAudits:
    rows: ClassVar[list[dict[str, Any]]] = []

    def list_audits(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeOffpage:
    rows: ClassVar[list[dict[str, Any]]] = []
    web2_rows: ClassVar[list[dict[str, Any]]] = []

    def referring_domain_count(self) -> int:
        return len(self.rows)

    def backlink_status_counts(self) -> dict[str, int]:
        return {"new": len(self.rows)}

    def new_backlink_count(self, **kwargs: Any) -> int:
        return len(self.rows)

    def list_backlinks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.rows)

    def web2_publish_stats(self, **kwargs: Any) -> dict[str, int]:
        return {"scheduled": 0, "failed": 0, "published": len(self.web2_rows)}

    def list_web2(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.web2_rows)


class _FakeContent:
    rows: ClassVar[list[dict[str, Any]]] = []

    def stats(self) -> dict[str, int]:
        return {"drafting": len(self.rows)}

    def publish_stats(self, **kwargs: Any) -> dict[str, int]:
        return {"scheduled": 0, "failed": 0, "published": len(self.rows)}

    def list_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeReports:
    events: ClassVar[list[dict[str, Any]]] = []
    workbooks: ClassVar[list[dict[str, Any]]] = []

    def sync_event_count(self, **kwargs: Any) -> int:
        return len(self.events)

    def list_sync_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.events)

    def list_workbooks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.workbooks)


class _FakeTasks:
    rows: ClassVar[list[dict[str, Any]]] = []

    def list_board_tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.rows)

    def list_tasks(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeClients:
    sites: ClassVar[list[dict[str, Any]]] = []
    clients: ClassVar[list[dict[str, Any]]] = []

    def list_all_sites(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.sites)

    def list_clients(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.clients)

    def site_counts(self) -> dict[str, int]:
        return {_SECRET_CLIENT_ID: len(self.sites)}


class _FakeVault:
    rows: ClassVar[list[dict[str, Any]]] = []

    def list_keys(self) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeMetrics:
    def member_metrics(self, ids: Any = None) -> dict[str, MemberMetrics]:
        return {"u1": MemberMetrics(active_tasks=6)}


class _FakeRoster:
    """The roster bank. A CLASS attribute (like the repo fakes above) rather than a
    module global on purpose: ``seeded`` installs it with ``monkeypatch.setattr``, which
    auto-restores - a hand-mutated global would bleed into the empty-ledger tests that
    deliberately run WITHOUT ``seeded``."""

    rows: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def read(cls, _caller_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return list(cls.rows)


@pytest.fixture
def wire(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Wire every fake repo + an identity + the caller's feature grants.

    All nine repos are wired at once (rather than per-route) so the parametrized gate
    sweeps can drive any route without knowing which repo it reaches for.
    """
    app.dependency_overrides[get_audits_repo] = _FakeAudits
    app.dependency_overrides[get_offpage_repo] = _FakeOffpage
    app.dependency_overrides[get_content_repo] = _FakeContent
    app.dependency_overrides[get_reports_repo] = _FakeReports
    app.dependency_overrides[get_tasks_repo] = _FakeTasks
    app.dependency_overrides[get_clients_repo] = _FakeClients
    app.dependency_overrides[get_vault_repo] = _FakeVault
    app.dependency_overrides[get_team_metrics] = _FakeMetrics
    app.dependency_overrides[get_roster_reader] = lambda: _FakeRoster.read
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))

    def _as(role: str, *, features: list[str] | None = None) -> None:
        grants.clear()
        for key in _KEYS if features is None else features:
            grants[key] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.fixture
def seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """One row of everything, each carrying the secret client_id the sweep hunts for."""
    monkeypatch.setattr(_FakeAudits, "rows", [
        {"id": "a1", "client_id": _SECRET_CLIENT_ID, "client_name": "NorthPeak Dental",
         "url": "northpeakdental.com", "status": "done", "score": 88,
         "runtime_seconds": 372, "created_at": "2026-07-16T09:14:00+00:00"},
    ])
    monkeypatch.setattr(_FakeOffpage, "rows", [
        {"client_id": _SECRET_CLIENT_ID, "client_name": "NorthPeak Dental",
         "ref_domain": "healthline.com", "authority": 91, "status": "new"},
    ])
    monkeypatch.setattr(_FakeOffpage, "web2_rows", [
        {"client_id": _SECRET_CLIENT_ID, "client_name": "Verde Cafe",
         "topic": "Seasonal menu launch", "platform": "Medium", "status": "published",
         "created_at": "2026-07-14T09:00:00+00:00"},
    ])
    monkeypatch.setattr(_FakeContent, "rows", [
        {"client_id": _SECRET_CLIENT_ID, "client_name": "NorthPeak Dental",
         "topic": "Teeth whitening guide", "stage": "Drafting", "status": "drafting",
         "words": 1850, "target": "WordPress", "created_at": "2026-07-16T09:00:00+00:00"},
    ])
    monkeypatch.setattr(_FakeReports, "events", [
        {"id": "e1", "client_id": _SECRET_CLIENT_ID, "client_name": "NorthPeak Dental",
         "dataset": "audit", "rows": 120, "synced_at": "2026-06-30T09:00:00+00:00"},
    ])
    monkeypatch.setattr(_FakeReports, "workbooks", [
        {"id": "w1", "client_id": _SECRET_CLIENT_ID, "client_name": "NorthPeak Dental",
         "status": "synced"},
    ])
    monkeypatch.setattr(_FakeTasks, "rows", [
        {"code": "J-2042", "client_id": _SECRET_CLIENT_ID, "client_name": "NorthPeak Dental",
         "title": "Technical crawl + CWV", "status": "in_progress",
         "assignee_name": "Bilal", "updated_at": "2026-07-16T09:00:00+00:00"},
    ])
    monkeypatch.setattr(_FakeClients, "sites", [
        {"id": "s1", "domain": "northpeakdental.com", "cms_type": "wordpress",
         "client_name": "NorthPeak Dental", "client_status": "active"},
    ])
    monkeypatch.setattr(_FakeClients, "clients", [
        {"id": _SECRET_CLIENT_ID, "name": "NorthPeak Dental", "status": "active"},
    ])
    monkeypatch.setattr(_FakeVault, "rows", [
        {"id": "k1", "provider": "Serper.dev", "label": "Search",
         "masked": "sk-abc••••••••4cb6", "secret_sealed": b"SEALED-DO-NOT-LEAK",
         "kind": "api_key", "key_version": 1,
         "created_at": "2026-01-04T09:00:00+00:00", "updated_at": "2026-05-04T09:00:00+00:00"},
    ])
    monkeypatch.setattr(_FakeRoster, "rows", [
        {"id": "u1", "name": "Ayesha Raza", "role": "manager", "status": "active",
         "email": "ayesha@aios.dev", "avatar_color": "#7B69EE", "title": "Manager"},
    ])


# --------------------------------------------------------------------------- #
# 1. Gate 1 - authentication.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_every_route_rejects_an_unauthenticated_caller(
    client: httpx.AsyncClient, path: str
) -> None:
    # No identity override + no bearer -> 401 before any repo/DB is touched.
    assert (await client.get(path)).status_code == 401


# --------------------------------------------------------------------------- #
# 2. Gate 2 - each route's OWN feature grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("tool_key", "path"), _ROUTES, ids=_KEYS)
async def test_every_route_requires_its_feature_grant(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None,
    tool_key: str, path: str
) -> None:
    # An admin holds view_reports AND manage_vault, so an ungranted feature is the only
    # thing that can reject here.
    wire("admin", features=[])
    resp = await client.get(path)
    assert resp.status_code == 403, resp.text
    assert tool_key in _message(resp)


@pytest.mark.parametrize(("tool_key", "path"), _ROUTES, ids=_KEYS)
async def test_each_route_is_gated_on_its_own_key_not_a_siblings(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None,
    tool_key: str, path: str
) -> None:
    """The copy-paste guard. Nine sibling routes carry nine different feature keys; a
    route wearing the wrong one would still pass the happy-path test above (an operator
    granted every tool notices nothing) but would silently hand a caller a tool they
    were never granted. Granting EVERY OTHER key must still reject this route.
    """
    wire("admin", features=[k for k in _KEYS if k != tool_key])
    resp = await client.get(path)
    assert resp.status_code == 403, f"{path} is not gated on {tool_key}: {resp.text}"
    assert tool_key in _message(resp)


@pytest.mark.parametrize(("tool_key", "path"), _ROUTES, ids=_KEYS)
async def test_the_grant_alone_admits_the_caller(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None,
    tool_key: str, path: str
) -> None:
    """The other half of the pin above: the route's own key is SUFFICIENT (an admin
    holding only it gets in), so the test above is failing on the grant and not on
    something incidental."""
    wire("admin", features=[tool_key])
    assert (await client.get(path)).status_code == 200


@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, path: str
) -> None:
    # Owner short-circuits require_feature (no grant lookup at all).
    wire("owner", features=[])
    assert (await client.get(path)).status_code == 200


@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_a_view_only_grant_does_not_satisfy_a_full_feature_requirement(
    app: FastAPI, client: httpx.AsyncClient, wire: Callable[..., None], seeded: None,
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    wire("admin", features=[])
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: dict.fromkeys(_KEYS, "view")
    )
    assert (await client.get(path)).status_code == 403  # require_feature defaults to "full"


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports on every read; manage_vault on key_vault only.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_a_portal_client_is_rejected_from_every_workspace(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, path: str
) -> None:
    """A portal client holds NO staff permission (``role_has_perm`` returns False before
    it ever indexes the matrix), so view_reports rejects it from the whole staff tool
    surface even if a grant row somehow existed."""
    wire("client")
    assert (await client.get(path)).status_code == 403


@pytest.mark.parametrize("role", ["manager", "specialist", "analyst", "viewer"])
async def test_key_vault_additionally_requires_manage_vault(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, role: str
) -> None:
    """The 0004 RLS select policy is owner/admin only. Without this gate a granted
    manager would get a silently EMPTY key list - an empty table that actually means
    "forbidden" is a lie worth 403-ing instead. Mirrors the vault router's own gate.
    """
    wire(role)
    resp = await client.get("/api/v1/key-vault/workspace")
    assert resp.status_code == 403, resp.text
    assert "manage_vault" in _message(resp)


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_key_vault_admits_a_manage_vault_holder(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, role: str
) -> None:
    wire(role)
    assert (await client.get("/api/v1/key-vault/workspace")).status_code == 200


@pytest.mark.parametrize("path", [p for k, p in _ROUTES if k != "key_vault"])
async def test_every_other_workspace_admits_a_granted_non_vault_role(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, path: str
) -> None:
    """manage_vault must NOT have leaked onto the sibling routes: a viewer holds
    view_reports only, and that is the whole read gate everywhere but the vault."""
    wire("viewer")
    assert (await client.get(path)).status_code == 200, path


# --------------------------------------------------------------------------- #
# 4. The wire shape.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_every_route_returns_the_tool_extra_envelope(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, path: str
) -> None:
    wire("owner")
    body = (await client.get(path)).json()
    assert set(body) <= {"kpis", "table", "primary", "bullets"}
    assert {"kpis", "bullets"} <= set(body)
    assert len(body["kpis"]) == 3
    assert body["table"]["rows"], f"{path}: seeded data produced no rows"
    for row in body["table"]["rows"]:
        assert len(row) == len(body["table"]["cols"])


# --------------------------------------------------------------------------- #
# 5. The no-leak sweep - ALL NINE routes.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_client_id_never_appears_in_any_workspace_body(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None, path: str
) -> None:
    """Every fake row carries ``_SECRET_CLIENT_ID``; every response must show the
    ``client_name`` snapshot instead. Asserted over the RAW response text so a leak
    cannot hide inside a nested cell, a key, or a KPI value.
    """
    wire("owner")
    resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    assert _SECRET_CLIENT_ID not in resp.text, f"{path} leaked the internal client_id"
    assert "client_id" not in resp.text
    assert "clientId" not in resp.text


async def test_the_leak_sweep_can_actually_see_a_leak(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: None
) -> None:
    """Guard for the guard: prove the sweep above is looking somewhere real. The seeded
    client NAME does reach the body, so a matching assertion on the id is meaningful
    rather than passing because the body was empty."""
    wire("owner")
    resp = await client.get("/api/v1/technical-audit/workspace")
    assert "NorthPeak Dental" in resp.text  # the snapshot IS surfaced...
    assert _SECRET_CLIENT_ID not in resp.text  # ... and the id behind it is not


# --------------------------------------------------------------------------- #
# 6. Empty data renders an empty-but-valid table, never a 500.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_empty_repo_data_renders_an_empty_table_not_a_500(
    client: httpx.AsyncClient, wire: Callable[..., None], path: str
) -> None:
    """A fresh deploy has empty ledgers (no ``seeded`` fixture here) - every card must
    still render its columns + tiles."""
    wire("owner")
    resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["table"]["rows"] == []
    assert len(body["table"]["cols"]) == 4
    assert len(body["kpis"]) == 3
    assert body["bullets"]


# --------------------------------------------------------------------------- #
# 7. These are READS: no route may mutate or record activity.
# --------------------------------------------------------------------------- #
# Symbols this module must never reference IN CODE. Checked over the AST, not the raw
# text: the module's docstrings discuss all of these at length (explaining precisely why
# it does not call them), and prose saying "we deliberately do NOT record activity" must
# not fail the test that enforces exactly that. The tree carries no comments and this
# sweep skips docstrings, so only real code counts.
_FORBIDDEN_IN_CODE: dict[str, str] = {
    # Activity feeds the 6B context memory with things that HAPPENED; opening a
    # dashboard card is not one of them. If a workspace ever wrote activity, every page
    # view would pollute a client's context history.
    "record_activity": "these routes are READS - activity is for things that HAPPENED",
    # This module is an ADAPTER: it reuses existing repos and owns no SQL. Not the
    # service_role write path (which would bypass RLS outright), and not even the RLS
    # read seam - naming either would mean this layer had started owning storage.
    "privileged_connection": "an adapter must never open the service_role pool",
    "rls_connection": "an adapter reuses repos; it does not open its own DB seam",
}
_FORBIDDEN_MODULES = ("app.services.activity", "app.db.database")


def _code_references(path: Path) -> set[str]:
    """Every identifier/attribute/string literal the file references in CODE.

    Docstrings are excluded (a module is free to DOCUMENT what it must not do);
    comments never reach the AST at all.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, holders)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            found.add(node.value)
    return found


def _module_files() -> list[Path]:
    return sorted(_MODULE_DIR.glob("*.py"))


@pytest.mark.parametrize(("symbol", "why"), sorted(_FORBIDDEN_IN_CODE.items()))
def test_the_module_never_references_a_write_or_db_seam(symbol: str, why: str) -> None:
    for path in _module_files():
        assert symbol not in _code_references(path), f"{path.name} names {symbol!r}: {why}"


@pytest.mark.parametrize("module_name", _FORBIDDEN_MODULES)
def test_the_module_never_imports_a_write_or_db_seam(module_name: str) -> None:
    """Catches a nested (in-function) import too, which a module-attribute check would
    miss entirely."""
    for path in _module_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.module != module_name, f"{path.name} line {node.lineno}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != module_name, f"{path.name} line {node.lineno}"


def test_the_forbidden_symbol_sweep_can_actually_see_a_violation(tmp_path: Path) -> None:
    """Guard for the guard: prove the AST walk rejects the code it exists to prevent,
    and that a DOCSTRING mentioning the same symbol is correctly tolerated."""
    offender = tmp_path / "offender.py"
    offender.write_text("async def go(u):\n    await record_activity(u)\n", encoding="utf-8")
    assert "record_activity" in _code_references(offender)

    documented = tmp_path / "documented.py"
    documented.write_text('"""This module never calls record_activity."""\n', encoding="utf-8")
    assert "record_activity" not in _code_references(documented)


@pytest.mark.parametrize("path", _PATHS, ids=_KEYS)
async def test_no_workspace_route_answers_a_mutating_verb(
    client: httpx.AsyncClient, wire: Callable[..., None], path: str
) -> None:
    """The module publishes GET only; a POST/PATCH/DELETE must 405, not fall through to
    some sibling route."""
    wire("owner")
    for method in ("POST", "PATCH", "DELETE"):
        resp = await client.request(method, path, json={})
        assert resp.status_code == 405, f"{method} {path} -> {resp.status_code}"
