"""Unit tests for the Milestones module: the response/request models (contract
shapes + §3 enum fidelity), the ``project_progress`` / ``current_stage`` helpers,
and the /milestones endpoints with a faked repo (no DB, no network).

The frontend contract (``lib/milestones.ts``) is the source of truth: ``Health`` is
SEPARATE from ``StageStatus`` (they share ``completed`` but are distinct), and a
``ClientProject`` is always its 5 lifecycle stages in order.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.milestones_repo import get_milestones_repo
from app.schemas.milestones import (
    AutoAdvanceResponse,
    ClientProjectResponse,
    Health,
    StageResponse,
    StageStatus,
    current_stage,
    project_progress,
)

pytestmark = pytest.mark.unit

_PROJECT_KEYS = {"id", "client", "site", "init", "c", "health", "stages"}
_STAGE_KEYS = {"key", "status", "auto_source", "updated_at"}
_AUTO_KEYS = {"id", "client", "init", "c", "milestone", "trigger", "icon", "ago", "flag"}

_ORDER = ["onboarding", "baseline", "content", "authority", "reporting"]


def _emitted(model: type[Any]) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --- schema shape / enum fidelity --------------------------------------------

def test_project_response_emits_exactly_the_contract_keys() -> None:
    assert _emitted(ClientProjectResponse) == _PROJECT_KEYS


def test_stage_response_emits_exactly_the_contract_keys() -> None:
    assert _emitted(StageResponse) == _STAGE_KEYS


def test_auto_advance_response_emits_exactly_the_contract_keys() -> None:
    assert _emitted(AutoAdvanceResponse) == _AUTO_KEYS


def test_health_and_stage_status_are_separate_unions() -> None:
    import typing

    health = set(typing.get_args(Health))
    stage = set(typing.get_args(StageStatus))
    assert health == {"on_track", "at_risk", "completed"}
    assert stage == {"completed", "in_progress", "upcoming", "blocked"}
    # They share only 'completed' - never merged (a superset of one is not the other).
    assert health != stage
    assert health & stage == {"completed"}


def test_stage_from_row_upcoming_shows_em_dash() -> None:
    stage = StageResponse.from_row(
        {"stage_key": "content", "status": "upcoming", "auto_source": "later",
         "updated_at": datetime.now(UTC)}
    )
    assert stage.updated_at == "—"  # an un-advanced stage shows the em-dash


def test_stage_from_row_advanced_shows_relative_time() -> None:
    stage = StageResponse.from_row(
        {"stage_key": "baseline", "status": "completed", "auto_source": "audit done",
         "updated_at": datetime.now(UTC) - timedelta(hours=3)}
    )
    assert stage.updated_at == "3h ago"


def test_stage_from_row_unknown_values_fall_back_safely() -> None:
    stage = StageResponse.from_row({"stage_key": "???", "status": "???"})
    assert stage.key == "onboarding"
    assert stage.status == "upcoming"


# --- ClientProject assembly ---------------------------------------------------

def _project_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "mp-1", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "site": "northpeakdental.com", "init": "ND", "accent": "#7B69EE",
        "health": "on_track",
    }
    row.update(over)
    return row


def _stage_row(key: str, status: str = "upcoming", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "project_id": "mp-1", "stage_key": key, "status": status,
        "auto_source": f"{key} source", "updated_at": datetime.now(UTC),
    }
    row.update(over)
    return row


def test_from_rows_orders_stages_and_snapshots_without_leaking_client_id() -> None:
    # Feed the stages OUT of lifecycle order to prove the model re-sorts them.
    scrambled = [_stage_row(k) for k in ["reporting", "onboarding", "content", "authority", "baseline"]]
    project = ClientProjectResponse.from_rows(_project_row(), scrambled)
    dumped = project.model_dump(by_alias=True)
    assert set(dumped) == _PROJECT_KEYS
    assert dumped["c"] == "#7B69EE"  # accent -> `c`
    assert dumped["client"] == "NorthPeak Dental"
    assert "client_id" not in dumped
    assert [s["key"] for s in dumped["stages"]] == _ORDER  # re-sorted to lifecycle order


def test_from_rows_unknown_health_falls_back() -> None:
    project = ClientProjectResponse.from_rows(_project_row(health="???"), [])
    assert project.health == "on_track"


# --- helpers mirror milestones.ts --------------------------------------------

def _project(statuses: list[str]) -> ClientProjectResponse:
    stages = [_stage_row(_ORDER[i], status=s) for i, s in enumerate(statuses)]
    return ClientProjectResponse.from_rows(_project_row(), stages)


def test_project_progress_matches_weighting() -> None:
    # weights: completed=1, in_progress=0.5, blocked=0.25, upcoming=0 over 5 stages.
    p = _project(["completed", "completed", "in_progress", "upcoming", "upcoming"])
    # (1 + 1 + 0.5 + 0 + 0) / 5 * 100 = 50
    assert project_progress(p) == 50
    assert project_progress(_project(["completed"] * 5)) == 100
    assert project_progress(_project(["upcoming"] * 5)) == 0


def test_project_progress_empty_is_zero() -> None:
    assert project_progress(ClientProjectResponse.from_rows(_project_row(), [])) == 0


def test_current_stage_prefers_in_progress_or_blocked_then_upcoming() -> None:
    p = _project(["completed", "completed", "in_progress", "upcoming", "upcoming"])
    assert current_stage(p) is not None
    cs = current_stage(p)
    assert cs is not None and cs.key == "content"  # first in_progress
    # all completed -> the last stage
    all_done = _project(["completed"] * 5)
    last = current_stage(all_done)
    assert last is not None and last.key == "reporting"
    # first upcoming when none in progress/blocked
    early = _project(["completed", "upcoming", "upcoming", "upcoming", "upcoming"])
    up = current_stage(early)
    assert up is not None and up.key == "baseline"


def test_current_stage_empty_is_none() -> None:
    assert current_stage(ClientProjectResponse.from_rows(_project_row(), [])) is None


# --- AutoAdvance feed shape ---------------------------------------------------

def test_auto_advance_blocked_row_is_flagged() -> None:
    aa = AutoAdvanceResponse.from_row(
        {"id": "s-1", "stage_key": "baseline", "status": "blocked",
         "auto_source": "renewal past due", "client_name": "Atlas Legal",
         "init": "AL", "accent": "#f00", "updated_at": datetime.now(UTC)}
    )
    assert aa.flag is True
    assert aa.icon == "block"
    assert aa.milestone == "Baseline Audit"  # stage label, not the raw key
    assert aa.trigger == "renewal past due"
    assert aa.c == "#f00"


def test_auto_advance_forward_advance_uses_stage_icon() -> None:
    aa = AutoAdvanceResponse.from_row(
        {"id": "s-2", "stage_key": "content", "status": "in_progress",
         "auto_source": "sprint published", "client_name": "Lumen",
         "init": "LR", "accent": "#0f0", "updated_at": datetime.now(UTC)}
    )
    assert aa.flag is False
    assert aa.icon == "article"  # the content stage's lifecycle icon
    assert aa.milestone == "Content Sprint"


# --- endpoints (faked repo) ---------------------------------------------------

class FakeMilestonesRepo:
    def __init__(self) -> None:
        self.projects: list[dict[str, Any]] = []
        self.stages: list[dict[str, Any]] = []
        self.feed: list[dict[str, Any]] = []
        self.listed_project_ids: list[str] | None = None

    def list_projects(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self.projects

    def list_stages(self, project_ids: list[str]) -> list[dict[str, Any]]:
        self.listed_project_ids = project_ids
        ids = set(project_ids)
        return [s for s in self.stages if str(s["project_id"]) in ids]

    def recent_advances(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return self.feed


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeMilestonesRepo:
    return FakeMilestonesRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeMilestonesRepo) -> Callable[..., None]:
    app.dependency_overrides[get_milestones_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_client_forbidden_from_milestones(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/milestones")).status_code == 403
    assert (await client.get("/api/v1/milestones/auto-advance")).status_code == 403


async def test_list_milestones_assembles_ordered_stages(
    client: httpx.AsyncClient, repo: FakeMilestonesRepo, wire: Callable[..., None]
) -> None:
    repo.projects = [_project_row()]
    repo.stages = [_stage_row(k) for k in ["content", "onboarding", "reporting", "baseline", "authority"]]
    wire("viewer")
    resp = await client.get("/api/v1/milestones")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert set(body[0]) == _PROJECT_KEYS
    assert "client_id" not in body[0]
    assert [s["key"] for s in body[0]["stages"]] == _ORDER
    assert repo.listed_project_ids == ["mp-1"]  # stages fetched for the page's projects


async def test_list_milestones_empty_board(
    client: httpx.AsyncClient, repo: FakeMilestonesRepo, wire: Callable[..., None]
) -> None:
    wire("analyst")
    resp = await client.get("/api/v1/milestones")
    assert resp.status_code == 200
    assert resp.json() == []
    assert repo.listed_project_ids == []  # no ids -> no stage query


async def test_auto_advance_feed_shape(
    client: httpx.AsyncClient, repo: FakeMilestonesRepo, wire: Callable[..., None]
) -> None:
    repo.feed = [
        {"id": "s-1", "stage_key": "baseline", "status": "blocked",
         "auto_source": "renewal past due", "client_name": "Atlas Legal",
         "init": "AL", "accent": "#f00", "updated_at": datetime.now(UTC)},
    ]
    wire("manager", "u-lead")
    resp = await client.get("/api/v1/milestones/auto-advance")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == _AUTO_KEYS
    assert body[0]["flag"] is True
    assert body[0]["milestone"] == "Baseline Audit"
