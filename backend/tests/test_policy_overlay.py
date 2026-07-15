"""Unit tests for the Policy Radar R3 CLOSED-LOOP overlay (chunk 7C-3).

Covers: the PURE ``overlay_row_from_rec`` mapping (audit vs advisory weight,
snapshots, enum normalization), ``apply_recommendation`` writing an overlay row
WITHOUT touching the filesystem (THE HARD RULE: the ``danyals-audit-system`` engine
is never mutated - proven by a source scan + a write-guard), the ``OverlayResponse``
shape, and the /policy router wiring (``apply`` writes an overlay, ack/dismiss do
NOT; ``GET /policy/overlay`` reads active rows; RBAC). No DB, no network, no engine.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.policy_repo import get_policy_repo
from app.schemas.policy import OverlayResponse
from app.services.policy_baseline import baseline_by_id, merge_baseline
from app.services.policy_radar import apply_recommendation, overlay_row_from_rec

pytestmark = pytest.mark.unit

_OVERLAY_KEYS = {
    "id", "target", "auditType", "region", "title", "guidance",
    "weight", "kbId", "action", "version", "active",
}

# A materialized (DB-shaped) recommendation row, as the transition returns it.
_APPLIED_AUDIT_REC: dict[str, Any] = {
    "id": "db-uuid-1",
    "kb_ref": "kb-base-eeat",
    "title": "Lead with first-hand experience (E-E-A-T)",
    "why": "helpful-content rewards experience",
    "action": "Keep the audit check 'E-E-A-T depth scan' on every crawl.",
    "scope": "global",
    "target_module": "audit",
    "region": "global",
    "region_label": "Global",
    "status": "applied",
}
_APPLIED_CONTENT_REC: dict[str, Any] = {
    "id": "db-uuid-2",
    "kb_ref": "kb-base-geo",
    "title": "Answer-first passages (GEO)",
    "action": "Require a 40-60 word answer summary in every brief.",
    "scope": "global",
    "target_module": "content",
    "region": "national",
    "region_label": "US · National",
    "status": "applied",
}


# --- pure mapping ------------------------------------------------------------- #


def test_overlay_row_from_audit_rec_is_a_weighted_check_with_snapshots() -> None:
    row = overlay_row_from_rec(_APPLIED_AUDIT_REC, created_by="u-lead")
    assert row["target_module"] == "audit"
    assert row["weight"] == 1.0  # an audit overlay adds a weighted check
    assert row["audit_type"] == ""  # a rec is not audit-type-specific -> all types
    assert row["region"] == "global"
    assert row["source_kb_ref"] == "kb-base-eeat"  # traceable back to the KB finding
    assert row["source_rec_id"] == "db-uuid-1"
    assert row["action"] == _APPLIED_AUDIT_REC["action"]
    assert row["guidance"] == _APPLIED_AUDIT_REC["action"]
    assert row["active"] is True and row["version"] == 1
    assert row["created_by"] == "u-lead"
    assert row["payload"] == {"scope": "global"}  # plain dict (repo wraps it as Jsonb)


def test_overlay_row_from_content_rec_is_a_zero_weight_advisory() -> None:
    row = overlay_row_from_rec(_APPLIED_CONTENT_REC, created_by=None)
    assert row["target_module"] == "content"
    assert row["weight"] == 0.0  # a content/portal overlay is a pure advisory
    assert row["region"] == "national"
    assert row["source_kb_ref"] == "kb-base-geo"
    assert row["created_by"] is None


def test_overlay_row_normalizes_bogus_enums_to_safe_defaults() -> None:
    row = overlay_row_from_rec(
        {"id": "x", "target_module": "nope", "region": "moon", "action": "a"},
        created_by="u",
    )
    assert row["target_module"] == "audit" and row["region"] == "global"
    assert row["weight"] == 1.0  # normalized-to-audit still gets the check weight


# --- OverlayResponse shape ---------------------------------------------------- #


def test_overlay_response_emits_exactly_the_expected_keys() -> None:
    emitted = {
        f.serialization_alias or name for name, f in OverlayResponse.model_fields.items()
    }
    assert emitted == _OVERLAY_KEYS


def test_overlay_response_from_row_maps_and_falls_back() -> None:
    dumped = OverlayResponse.from_row(
        {"id": 7, "target_module": "content", "audit_type": "technical",
         "region": "national", "title": "T", "guidance": "G", "weight": 2,
         "source_kb_ref": "kb-base-geo", "action": "A", "version": 3, "active": False}
    ).model_dump(by_alias=True)
    assert set(dumped) == _OVERLAY_KEYS
    assert dumped["target"] == "content" and dumped["auditType"] == "technical"
    assert dumped["kbId"] == "kb-base-geo" and dumped["weight"] == 2.0
    assert dumped["version"] == 3 and dumped["active"] is False
    # Unknown enums fall back safely.
    fb = OverlayResponse.from_row({"id": 1, "target_module": "x", "region": "y"})
    assert fb.target == "audit" and fb.region == "global"


# --- THE HARD RULE: the engine is NEVER mutated ------------------------------- #

_RADAR_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "policy_radar.py"
_RADAR_TREE = ast.parse(_RADAR_PATH.read_text(encoding="utf-8"))

# The closed loop may import ONLY from this known-safe set - NOTHING that could reach
# the engine (its adapter/dir), spawn a process, or touch the filesystem. (The
# docstring is free to NAME the engine to document the rule; the AST ignores strings.)
_ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {"__future__", "asyncio", "typing", "app.core.auth", "app.db.policy_repo", "app.schemas.policy"}
)


def _imported_modules(tree: ast.Module) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    return mods


def _called_names(tree: ast.Module) -> set[str]:
    return {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}


def test_policy_radar_never_reaches_the_engine() -> None:
    """THE HARD RULE, enforced statically: the closed loop is pure-Postgres. Its
    imports are a subset of a safe allowlist (no engine adapter, no subprocess, no
    os/io), and it calls neither ``open`` nor ``subprocess`` - so no path under the
    ``danyals-audit-system`` engine dir is reachable from the apply."""
    imports = _imported_modules(_RADAR_TREE)
    assert imports <= _ALLOWED_IMPORTS, f"unexpected imports: {sorted(imports - _ALLOWED_IMPORTS)}"
    calls = _called_names(_RADAR_TREE)
    assert "open" not in calls
    assert not any("subprocess" in c or "audit_engine" in c for c in calls)


async def test_apply_writes_overlay_and_touches_no_file() -> None:
    """``apply_recommendation`` records ONE overlay row and writes NOTHING to the
    filesystem (so the engine dir - or any file - is provably untouched)."""
    repo = _FakePolicyRepo()
    actor = _user("admin", "u-lead")

    import builtins

    real_open = builtins.open

    def _guard_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"apply wrote to a file: {file!r} (mode {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    with mock.patch("builtins.open", _guard_open):
        overlay = await apply_recommendation(actor, dict(_APPLIED_AUDIT_REC), repo)

    assert len(repo.overlays) == 1  # exactly one DB overlay write
    assert overlay["source_kb_ref"] == "kb-base-eeat"
    assert overlay["created_by"] == "u-lead"


# --- router wiring ------------------------------------------------------------ #


class _FakePolicyRepo:
    """In-memory PolicyRepo stand-in with the overlay + transition surface."""

    def __init__(self) -> None:
        self.recs: dict[str, dict[str, Any]] = {}
        self.overlays: list[dict[str, Any]] = []
        self._seq = 0

    def list_recommendations(
        self, *, status: str | None = None, include_baseline: bool = True,
        limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.recs.values())
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        return merge_baseline(rows, include_baseline=include_baseline and status is None)

    def transition_recommendation(self, rec_id: str, new_status: str) -> dict[str, Any] | None:
        existing = self.recs.get(rec_id)
        if existing is not None:
            existing["status"] = new_status
            return existing
        base = baseline_by_id(rec_id)
        if base is None:
            return None
        self._seq += 1
        base.pop("id", None)
        base["id"] = f"db-{self._seq}"
        base["status"] = new_status
        self.recs[base["id"]] = base
        return base

    def insert_overlay(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        stored = {**row, "id": f"ov-{self._seq}"}
        self.overlays.append(stored)
        return stored

    def list_active_overlay(
        self, *, target_module: str | None = None, audit_type: str | None = None,
        region: str | None = None, limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = [o for o in self.overlays if o.get("active", True)]
        if target_module is not None:
            rows = [o for o in rows if o.get("target_module") == target_module]
        if audit_type is not None:
            rows = [o for o in rows if o.get("audit_type") == audit_type]
        if region is not None:
            rows = [o for o in rows if o.get("region") == region]
        return list(reversed(rows))


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op Lead", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> _FakePolicyRepo:
    return _FakePolicyRepo()


@pytest.fixture
def wire(app: FastAPI, repo: _FakePolicyRepo) -> Callable[..., None]:
    app.dependency_overrides[get_policy_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_apply_action_writes_a_closed_loop_overlay(
    client: httpx.AsyncClient, repo: _FakePolicyRepo, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/policy/recommendations/rec-base-eeat/apply")
    assert resp.status_code == 200 and resp.json()["status"] == "applied"
    # The closed loop fired: one overlay row, traceable to the applied rec.
    assert len(repo.overlays) == 1
    overlay = repo.overlays[0]
    assert overlay["source_kb_ref"] == "kb-base-eeat"
    assert overlay["target_module"] == "audit" and overlay["active"] is True
    assert overlay["source_rec_id"].startswith("db-")  # the materialized rec id


@pytest.mark.parametrize("action", ["acknowledge", "dismiss"])
async def test_non_apply_actions_write_no_overlay(
    client: httpx.AsyncClient, repo: _FakePolicyRepo, wire: Callable[..., None], action: str
) -> None:
    wire("admin", "u-lead")
    resp = await client.post(f"/api/v1/policy/recommendations/rec-base-eeat/{action}")
    assert resp.status_code == 200
    assert repo.overlays == []  # only 'apply' closes the loop


async def test_overlay_list_returns_active_rows_in_shape(
    client: httpx.AsyncClient, repo: _FakePolicyRepo, wire: Callable[..., None]
) -> None:
    repo.overlays.append(
        {"id": "ov-1", "target_module": "audit", "audit_type": "", "region": "global",
         "title": "Extra E-E-A-T check", "guidance": "scan bylines", "weight": 1,
         "source_kb_ref": "kb-base-eeat", "action": "A", "version": 1, "active": True}
    )
    repo.overlays.append(
        {"id": "ov-2", "target_module": "content", "audit_type": "", "region": "national",
         "title": "retired", "guidance": "", "weight": 0, "source_kb_ref": "kb-base-geo",
         "action": "A", "version": 1, "active": False}
    )
    wire("viewer")
    body = (await client.get("/api/v1/policy/overlay")).json()
    assert len(body) == 1  # the retired (active=false) row never surfaces
    assert set(body[0]) == _OVERLAY_KEYS
    assert body[0]["kbId"] == "kb-base-eeat"


async def test_overlay_target_filter(
    client: httpx.AsyncClient, repo: _FakePolicyRepo, wire: Callable[..., None]
) -> None:
    repo.overlays.append(
        {"id": "ov-1", "target_module": "audit", "audit_type": "", "region": "global",
         "title": "a", "guidance": "", "weight": 1, "source_kb_ref": "k1",
         "action": "", "version": 1, "active": True}
    )
    repo.overlays.append(
        {"id": "ov-2", "target_module": "content", "audit_type": "", "region": "global",
         "title": "b", "guidance": "", "weight": 0, "source_kb_ref": "k2",
         "action": "", "version": 1, "active": True}
    )
    wire("viewer")
    only_content = (await client.get(
        "/api/v1/policy/overlay", params={"target": "content"}
    )).json()
    assert [o["kbId"] for o in only_content] == ["k2"]


async def test_overlay_read_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/policy/overlay")).status_code == 403


async def test_apply_forbidden_for_non_lead_writes_no_overlay(
    client: httpx.AsyncClient, repo: _FakePolicyRepo, wire: Callable[..., None]
) -> None:
    for role in ("viewer", "specialist", "analyst"):
        wire(role)
        resp = await client.post("/api/v1/policy/recommendations/rec-base-eeat/apply")
        assert resp.status_code == 403, role
    assert repo.overlays == []  # the closed loop is lead-only
