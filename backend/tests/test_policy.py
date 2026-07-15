"""Unit tests for the Policy Radar module (7C-1 foundation).

Covers: the four response models (the exact contract keys + camelCase aliases +
safe fallbacks), the SEVEN enum unions pinned verbatim from ``lib/policy.ts`` AND
defined in migration 0019, the baseline-recommendation constant set + the
``merge_baseline`` surfacing/dedup, and the /policy endpoints against a faked repo -
reads (staff only), the recommendation transitions (leads only), baseline
materialize-on-transition, and the RBAC/404 edges. No DB, no network.
"""

from __future__ import annotations

import re
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.policy_repo import get_policy_repo
from app.schemas.policy import (
    Category,
    ChangeEventResponse,
    KBEntryResponse,
    RecommendationResponse,
    RecStatus,
    Region,
    Scope,
    Severity,
    SourceResponse,
    SourceStatus,
    TargetModule,
    action_to_status,
    rec_to_response,
    source_to_response,
)
from app.services.policy_baseline import (
    BASELINE_RECOMMENDATIONS,
    baseline_by_id,
    merge_baseline,
)

pytestmark = pytest.mark.unit

_SOURCE_KEYS = {"id", "name", "kind", "url", "icon", "lastChecked", "lastHash", "status", "note"}
_CHANGE_KEYS = {"id", "sourceId", "sourceName", "summary", "severity", "detected"}
_KB_KEYS = {
    "id", "title", "summary", "severity", "category", "region",
    "regionLabel", "sourceName", "sourceUrl", "version", "detected",
}
_REC_KEYS = {
    "id", "kbId", "title", "why", "action", "scope", "target",
    "region", "regionLabel", "status", "clients",
}

# The seven enums, verbatim from policy.ts (§3 enum fidelity).
_EXPECTED_ENUMS: dict[str, set[str]] = {
    "policy_severity": {"critical", "major", "minor", "info"},
    "policy_category": {"algorithm", "policy", "technical", "content", "local", "geo"},
    "policy_region": {"global", "national"},
    "policy_target_module": {"audit", "content", "portal"},
    "policy_scope": {"global", "client", "site"},
    "rec_status": {"new", "acknowledged", "applied", "dismissed"},
    "source_status": {"ok", "change"},
}


def _emitted(model: type[Any]) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --- schema shape -------------------------------------------------------------

def test_response_models_emit_exactly_the_contract_keys() -> None:
    assert _emitted(SourceResponse) == _SOURCE_KEYS
    assert _emitted(ChangeEventResponse) == _CHANGE_KEYS
    assert _emitted(KBEntryResponse) == _KB_KEYS
    assert _emitted(RecommendationResponse) == _REC_KEYS


def test_camelcase_wire_keys_and_no_internal_ids_leak() -> None:
    change = ChangeEventResponse.from_row(
        {"id": "c1", "source_id": "s-uuid", "source_name": "Search Central",
         "summary": "x", "severity": "major", "detected_at": None}
    ).model_dump(by_alias=True)
    assert set(change) == _CHANGE_KEYS
    assert "sourceId" in change and "source_id" not in change

    rec = rec_to_response(
        {"id": "r-uuid", "kb_entry_id": "kb-uuid", "kb_ref": "kb-base-eeat",
         "title": "T", "why": "W", "action": "A", "scope": "global",
         "target_module": "audit", "region": "global", "region_label": "Global",
         "status": "new", "affected_clients": ""}
    ).model_dump(by_alias=True)
    assert set(rec) == _REC_KEYS
    # kb_entry_id is internal-only; kbId carries the public snapshot instead.
    assert rec["kbId"] == "kb-base-eeat" and "kb_entry_id" not in rec
    assert "target_module" not in rec and rec["target"] == "audit"


def test_source_last_checked_relative_and_never_pre_live() -> None:
    dumped = source_to_response(
        {"id": "s1", "name": "Search Status", "kind": "Incidents", "url": "u",
         "icon": "i", "last_checked": None, "last_hash": "ab·cd", "status": "change",
         "note": "n"}
    ).model_dump(by_alias=True)
    assert set(dumped) == _SOURCE_KEYS
    assert dumped["lastChecked"] == "never"  # null until the watcher's first poll
    assert dumped["lastHash"] == "ab·cd"
    assert dumped["status"] == "change"


def test_response_fallbacks_are_safe_for_unknown_enum_values() -> None:
    src = source_to_response({"id": 1, "status": "bogus"})
    assert src.id == "1" and src.status == "ok"
    kb = KBEntryResponse.from_row({"id": 2, "severity": "x", "category": "y", "region": "z"})
    assert kb.severity == "info" and kb.category == "algorithm" and kb.region == "global"
    rec = rec_to_response({"id": 3, "scope": "x", "target_module": "y", "status": "z"})
    assert rec.scope == "global" and rec.target == "audit" and rec.status == "new"


# --- enum fidelity (all seven) ------------------------------------------------

def test_python_literal_unions_match_policy_ts() -> None:
    got = {
        "policy_severity": set(typing.get_args(Severity)),
        "policy_category": set(typing.get_args(Category)),
        "policy_region": set(typing.get_args(Region)),
        "policy_target_module": set(typing.get_args(TargetModule)),
        "policy_scope": set(typing.get_args(Scope)),
        "rec_status": set(typing.get_args(RecStatus)),
        "source_status": set(typing.get_args(SourceStatus)),
    }
    assert got == _EXPECTED_ENUMS


def test_migration_0019_defines_all_seven_enums_verbatim() -> None:
    # backend/tests/ -> backend/ -> repo root -> db/migrations/0019_policy.sql
    sql = (
        Path(__file__).resolve().parents[2] / "db" / "migrations" / "0019_policy.sql"
    ).read_text(encoding="utf-8")
    for enum_name, labels in _EXPECTED_ENUMS.items():
        match = re.search(
            rf"create type public\.{enum_name} as enum\s*\((.*?)\)", sql, re.DOTALL
        )
        assert match, f"enum {enum_name} not defined in 0019_policy.sql"
        defined = set(re.findall(r"'([^']*)'", match.group(1)))
        assert defined == labels, f"{enum_name} labels drifted: {defined} != {labels}"


# --- baseline recommendations -------------------------------------------------

def test_baseline_recommendations_present_and_well_formed() -> None:
    assert len(BASELINE_RECOMMENDATIONS) >= 5  # Command Center isn't empty pre-live
    ids = {r["id"] for r in BASELINE_RECOMMENDATIONS}
    kb_refs = {r["kb_ref"] for r in BASELINE_RECOMMENDATIONS}
    assert len(ids) == len(BASELINE_RECOMMENDATIONS)  # unique synthetic ids
    assert len(kb_refs) == len(BASELINE_RECOMMENDATIONS)  # unique kb_refs (dedup key)
    for r in BASELINE_RECOMMENDATIONS:
        assert r["id"].startswith("rec-base-") and r["kb_ref"].startswith("kb-base-")
        assert r["kb_entry_id"] is None  # no live KB entry backs a baseline rec
        assert r["scope"] in _EXPECTED_ENUMS["policy_scope"]
        assert r["target_module"] in _EXPECTED_ENUMS["policy_target_module"]
        assert r["region"] in _EXPECTED_ENUMS["policy_region"]
        assert r["status"] in _EXPECTED_ENUMS["rec_status"]
        # Every baseline rec renders cleanly through the contract mapper.
        assert set(rec_to_response(r).model_dump(by_alias=True)) == _REC_KEYS


def test_merge_baseline_appends_then_dedupes_by_kb_ref() -> None:
    # Empty DB -> the full baseline set surfaces.
    surfaced = merge_baseline([])
    assert len(surfaced) == len(BASELINE_RECOMMENDATIONS)

    # A materialized baseline rec (same kb_ref, a real uuid + acted status) wins;
    # the constant is dropped so the rec appears exactly once.
    materialized = {"id": "db-uuid", "kb_ref": "kb-base-eeat", "status": "applied"}
    merged = merge_baseline([materialized])
    kb_refs = [r["kb_ref"] for r in merged]
    assert kb_refs.count("kb-base-eeat") == 1
    assert merged[0] is materialized  # DB rows first
    assert len(merged) == len(BASELINE_RECOMMENDATIONS)  # one replaced, none added twice

    # include_baseline=False leaves DB rows untouched.
    assert merge_baseline([materialized], include_baseline=False) == [materialized]


def test_baseline_by_id_and_action_to_status() -> None:
    assert baseline_by_id("rec-base-eeat") is not None
    assert baseline_by_id("nope") is None
    assert action_to_status("acknowledge") == "acknowledged"
    assert action_to_status("apply") == "applied"
    assert action_to_status("dismiss") == "dismissed"


# --- endpoints (faked repo) ---------------------------------------------------


class FakePolicyRepo:
    """In-memory stand-in mirroring PolicyRepo's surfacing/materialize semantics."""

    def __init__(self) -> None:
        self.sources: list[dict[str, Any]] = []
        self.changes: list[dict[str, Any]] = []
        self.kb: list[dict[str, Any]] = []
        self.recs: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def list_sources(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self.sources

    def list_changes(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self.changes

    def list_kb(
        self, *, severity: str | None = None, category: str | None = None,
        region: str | None = None, limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self.kb
        if severity is not None:
            rows = [r for r in rows if r.get("severity") == severity]
        if category is not None:
            rows = [r for r in rows if r.get("category") == category]
        if region is not None:
            rows = [r for r in rows if r.get("region") == region]
        return rows

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


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakePolicyRepo:
    return FakePolicyRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakePolicyRepo) -> Callable[..., None]:
    app.dependency_overrides[get_policy_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


# reads

async def test_client_forbidden_from_all_reads(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    for path in ("sources", "changes", "kb", "recommendations"):
        assert (await client.get(f"/api/v1/policy/{path}")).status_code == 403


async def test_sources_changes_kb_shapes(
    client: httpx.AsyncClient, repo: FakePolicyRepo, wire: Callable[..., None]
) -> None:
    repo.sources.append(
        {"id": "s1", "name": "Search Status", "kind": "Incidents", "url": "u",
         "icon": "i", "last_checked": None, "last_hash": "ab", "status": "ok", "note": ""}
    )
    repo.changes.append(
        {"id": "c1", "source_id": "s1", "source_name": "Search Status",
         "summary": "x", "severity": "critical", "detected_at": None}
    )
    repo.kb.append(
        {"id": "k1", "title": "Core update", "summary": "s", "severity": "major",
         "category": "algorithm", "region": "global", "region_label": "Global",
         "source_name": "SS", "source_url": "u", "version": "v2", "detected_at": None}
    )
    wire("viewer")
    assert set((await client.get("/api/v1/policy/sources")).json()[0]) == _SOURCE_KEYS
    assert set((await client.get("/api/v1/policy/changes")).json()[0]) == _CHANGE_KEYS
    assert set((await client.get("/api/v1/policy/kb")).json()[0]) == _KB_KEYS


async def test_kb_axis_filter(
    client: httpx.AsyncClient, repo: FakePolicyRepo, wire: Callable[..., None]
) -> None:
    repo.kb.append({"id": "k1", "title": "a", "category": "algorithm", "region": "global"})
    repo.kb.append({"id": "k2", "title": "b", "category": "local", "region": "national"})
    wire("viewer")
    only_local = (await client.get("/api/v1/policy/kb", params={"category": "local"})).json()
    assert [k["id"] for k in only_local] == ["k2"]


async def test_recommendations_surface_baseline_when_db_empty(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    body = (await client.get("/api/v1/policy/recommendations")).json()
    assert len(body) == len(BASELINE_RECOMMENDATIONS)
    assert set(body[0]) == _REC_KEYS
    assert any(r["kbId"] == "kb-base-eeat" for r in body)


async def test_recommendations_status_filter_omits_baseline(
    client: httpx.AsyncClient, repo: FakePolicyRepo, wire: Callable[..., None]
) -> None:
    repo.recs["db-1"] = {"id": "db-1", "kb_ref": "kb-live", "title": "Live",
                         "status": "applied", "target_module": "audit"}
    wire("viewer")
    applied = (await client.get(
        "/api/v1/policy/recommendations", params={"status": "applied"}
    )).json()
    assert [r["id"] for r in applied] == ["db-1"]  # no always-'new' baseline recs


# transitions

@pytest.mark.parametrize(
    ("action", "expected"),
    [("acknowledge", "acknowledged"), ("apply", "applied"), ("dismiss", "dismissed")],
)
async def test_transition_sets_status_and_materializes_baseline(
    client: httpx.AsyncClient, repo: FakePolicyRepo, wire: Callable[..., None],
    action: str, expected: str,
) -> None:
    wire("manager", "u-lead")
    resp = await client.post(f"/api/v1/policy/recommendations/rec-base-eeat/{action}")
    assert resp.status_code == 200
    assert resp.json()["status"] == expected
    # Materialized into the DB with the acted status (kb_ref preserved for dedup).
    assert any(r["kb_ref"] == "kb-base-eeat" and r["status"] == expected
               for r in repo.recs.values())


async def test_transition_on_existing_db_rec(
    client: httpx.AsyncClient, repo: FakePolicyRepo, wire: Callable[..., None]
) -> None:
    repo.recs["db-1"] = {"id": "db-1", "kb_ref": "kb-live", "title": "Live",
                         "status": "new", "target_module": "audit"}
    wire("admin", "u-admin")
    resp = await client.post("/api/v1/policy/recommendations/db-1/apply")
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"
    assert repo.recs["db-1"]["status"] == "applied"


async def test_transition_unknown_id_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    assert (await client.post(
        "/api/v1/policy/recommendations/ghost/apply"
    )).status_code == 404


async def test_transition_rejects_unknown_action_422(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    assert (await client.post(
        "/api/v1/policy/recommendations/rec-base-eeat/frobnicate"
    )).status_code == 422


async def test_transition_forbidden_for_non_lead(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    for role in ("viewer", "specialist", "analyst"):
        wire(role)
        resp = await client.post("/api/v1/policy/recommendations/rec-base-eeat/apply")
        assert resp.status_code == 403, role
