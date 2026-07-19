"""Unit tests for the Command Center (admin-home) aggregate (chunk 7C-4).

Covers the PURE builders (weekly audit series, the PLACEHOLDER-flagged traffic
series, team jobs, client progress, spend rollup, the open-recs digest, the KPI
tiles) and the ``GET /command-center`` endpoint against faked repos - the payload
shape, the ``traffic.placeholder`` flag (N8), and the staff-only RBAC. No DB, no
network.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.audits_repo import get_audits_repo
from app.db.clients_repo import get_clients_repo
from app.db.cost_repo import get_cost_repo
from app.db.policy_repo import get_policy_repo
from app.db.tasks_repo import get_tasks_repo
from app.modules.site_analytics.repo import get_site_analytics_repo
from app.schemas.command_center import (
    CommandCenterResponse,
    build_audit_series,
    build_client_series,
    build_command_center,
    build_digest,
    build_spend_snapshot,
    build_stat_tiles,
    build_team_series,
    build_traffic_series,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
_CC_KEYS = {"statTiles", "audits", "traffic", "team", "clients", "digest", "spend", "gsc", "ga4"}


def _audit(created: datetime, *, client: str = "Acme", score: int | None = 88,
           types: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": f"a-{created.timestamp()}", "client_name": client, "score": score,
        "types": types if types is not None else ["technical"], "status": "done",
        "created_at": created,
    }


# --- audit series ------------------------------------------------------------- #


def test_audit_series_buckets_into_twelve_weeks_newest_last() -> None:
    audits = [
        _audit(_NOW),                                   # this week -> W12
        _audit(_NOW.replace(day=8)),                    # 1 week ago -> W11
        _audit(datetime(2026, 5, 20, tzinfo=UTC)),      # ~8 weeks ago
    ]
    series = build_audit_series(audits, now=_NOW)
    assert len(series) == 12
    assert [p.w for p in series] == [f"W{i + 1}" for i in range(12)]
    assert series[-1].v == 1  # this week
    assert series[-2].v == 1  # last week
    assert sum(p.v for p in series) == 3


# --- traffic series (PLACEHOLDER, N8) ----------------------------------------- #


def test_traffic_series_is_flagged_placeholder_and_audit_derived() -> None:
    audits = [_audit(_NOW), _audit(_NOW), _audit(datetime(2026, 6, 3, tzinfo=UTC))]
    series = build_traffic_series(audits, now=_NOW)
    assert series.placeholder is True  # honest: audits are URL-only, no live traffic
    assert len(series.points) == 6
    assert [p.m for p in series.points] == ["Feb", "Mar", "Apr", "May", "Jun", "Jul"]
    assert series.points[-1].v == 2   # two audits in Jul
    assert series.points[-2].v == 1   # one in Jun


# --- team series -------------------------------------------------------------- #


def test_team_series_counts_jobs_resolves_users_and_tops_five() -> None:
    tasks = (
        [{"assignee_id": "u-a", "status": "done"}] * 3
        + [{"assignee_id": "u-b", "status": "todo"}] * 5
        + [{"assignee_id": "u-x", "status": "todo"}]      # unknown user -> skipped
        + [{"assignee_id": None, "status": "todo"}]        # unassigned -> skipped
    )
    users = {
        "u-a": {"name": "Ayesha Raza", "avatar_color": "#7B69EE"},
        "u-b": {"name": "Bilal Anwar", "avatar_color": "#1FA890"},
    }
    team = build_team_series(tasks, users)
    # init is COMPUTED from the name (first letter of the first two words).
    assert [(t.nm, t.jobs, t.init) for t in team] == [
        ("Bilal Anwar", 5, "BA"), ("Ayesha Raza", 3, "AR"),
    ]
    assert team[0].c == "#1FA890"


# --- client series ------------------------------------------------------------ #


def test_client_series_uses_latest_audit_type_and_score() -> None:
    clients = [
        {"name": "Acme", "tier": "Growth", "status": "active"},
        {"name": "Globex", "tier": "Starter", "status": "trial"},  # no audit
    ]
    audits = [
        _audit(datetime(2026, 6, 1, tzinfo=UTC), client="Acme", score=70, types=["local"]),
        _audit(_NOW, client="Acme", score=91, types=["actionable"]),  # newer wins
    ]
    series = build_client_series(clients, audits)
    acme = next(c for c in series if c.cn == "Acme")
    globex = next(c for c in series if c.cn == "Globex")
    assert acme.cd == "Actionable" and acme.p == 91   # latest audit
    assert globex.cd == "Starter client" and globex.p == 0  # no audit -> tier label


# --- spend snapshot ----------------------------------------------------------- #


def test_spend_snapshot_totals_and_flags_near_over_cap() -> None:
    budgets = [
        {"cn": "Acme", "cap": 500, "spent": 312, "c": "#1"},   # 62% -> ok
        {"cn": "Globex", "cap": 250, "spent": 261, "c": "#2"}, # 104% -> flagged
        {"cn": "Initech", "cap": 120, "spent": 103, "c": "#3"},# 86% -> flagged
    ]
    snap = build_spend_snapshot(budgets, {"daily_stop": 75, "halted": False})
    assert snap.total_spent == 676 and snap.total_cap == 870
    assert snap.pct == round(676 / 870 * 100)
    # Worst-first, only the >=80% accounts.
    assert [f.cn for f in snap.flagged] == ["Globex", "Initech"]
    assert snap.flagged[0].pct == 104
    assert snap.daily_stop == 75.0 and snap.halted is False


# --- digest ------------------------------------------------------------------- #


def test_digest_keeps_open_recs_only_and_caps_at_four() -> None:
    rows = [
        {"id": f"r{i}", "kb_ref": f"k{i}", "title": f"T{i}", "status": "new",
         "target_module": "audit", "region": "global"}
        for i in range(6)
    ]
    rows.append({"id": "done", "kb_ref": "kd", "title": "applied", "status": "applied",
                 "target_module": "audit", "region": "global"})
    digest = build_digest(rows)
    assert len(digest) == 4  # capped
    assert all(d.status in ("new", "acknowledged") for d in digest)
    assert "applied" not in [d.title for d in digest]


# --- stat tiles --------------------------------------------------------------- #


def test_stat_tiles_are_live_with_a_real_audit_mom() -> None:
    audits = [
        _audit(_NOW), _audit(_NOW), _audit(_NOW),               # 3 this month (Jul)
        _audit(datetime(2026, 6, 10, tzinfo=UTC)),               # 1 last month (Jun)
    ]
    clients = [
        {"status": "active", "created_at": _NOW},                # active + new this month
        {"status": "active", "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
        {"status": "trial", "created_at": _NOW},                 # new this month too
    ]
    tasks = [
        {"status": "todo"}, {"status": "review"}, {"status": "done"},
    ]
    budgets = [{"cap": 100, "spent": 80}]
    tiles = build_stat_tiles(audits, clients, tasks, budgets, now=_NOW)
    assert [t.label for t in tiles] == [
        "Audits this month", "Active clients", "Active tasks", "Spend month-to-date",
    ]
    audits_tile = tiles[0]
    assert audits_tile.value == 3 and audits_tile.hero is True
    assert audits_tile.delta == "200%" and audits_tile.delta_dir == "up"  # (3-1)/1
    # value = active clients (2); delta = clients created this month (2: the active + the trial)
    assert tiles[1].value == 2 and tiles[1].delta == "2"
    assert tiles[2].value == 2 and tiles[2].delta == "1"   # 2 not-done, 1 in review
    assert tiles[3].value == 80 and tiles[3].delta == "80%"


# --- composite ---------------------------------------------------------------- #


def test_build_command_center_composes_every_section() -> None:
    payload = build_command_center(
        audits=[_audit(_NOW)],
        clients=[{"name": "Acme", "tier": "Growth", "status": "active", "created_at": _NOW}],
        tasks=[{"assignee_id": "u-a", "status": "todo"}],
        users_by_id={"u-a": {"name": "Ayesha Raza", "avatar_color": "#7B69EE"}},
        budgets=[{"cn": "Acme", "cap": 100, "spent": 90, "c": "#1"}],
        settings={"daily_stop": 75, "halted": False},
        rec_rows=[{"id": "r1", "kb_ref": "k1", "title": "T", "status": "new",
                   "target_module": "audit", "region": "global"}],
        now=_NOW,
    )
    assert isinstance(payload, CommandCenterResponse)
    assert len(payload.stat_tiles) == 4
    assert payload.traffic.placeholder is True
    assert payload.team[0].nm == "Ayesha Raza"
    assert payload.spend.flagged[0].cn == "Acme"  # 90% -> flagged
    assert len(payload.digest) == 1


# --- endpoint ----------------------------------------------------------------- #


class _FakeAuditsRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self._rows


class _FakeClientsRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_clients(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self._rows


class _FakeTasksRepo:
    def __init__(self, rows: list[dict[str, Any]], users: dict[str, dict[str, Any]]) -> None:
        self._rows = rows
        self._users = users

    def list_tasks(
        self, assignee_id: str | None = None, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return self._rows

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._users.get(user_id)


class _FakeCostRepo:
    def __init__(self, budgets: list[dict[str, Any]], settings: dict[str, Any]) -> None:
        self._budgets = budgets
        self._settings = settings

    def list_budgets(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self._budgets

    def get_settings(self) -> dict[str, Any]:
        return self._settings


class _FakePolicyRepo:
    def __init__(self, recs: list[dict[str, Any]]) -> None:
        self._recs = recs

    def list_recommendations(
        self, *, status: str | None = None, include_baseline: bool = True,
        limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._recs


class _FakeSiteAnalyticsRepo:
    def __init__(self, gsc: list[dict[str, Any]], ga4: list[dict[str, Any]]) -> None:
        self._gsc = gsc
        self._ga4 = ga4

    def list_gsc(self, *, client_id: str | None = None) -> list[dict[str, Any]]:
        return self._gsc

    def list_ga4(self, *, client_id: str | None = None) -> list[dict[str, Any]]:
        return self._ga4


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def wire(app: FastAPI) -> Callable[..., None]:
    app.dependency_overrides[get_audits_repo] = lambda: _FakeAuditsRepo([_audit(_NOW)])
    app.dependency_overrides[get_clients_repo] = lambda: _FakeClientsRepo(
        [{"name": "Acme", "tier": "Growth", "status": "active", "created_at": _NOW}]
    )
    app.dependency_overrides[get_tasks_repo] = lambda: _FakeTasksRepo(
        [{"assignee_id": "u-a", "status": "todo"}],
        {"u-a": {"name": "Ayesha Raza", "avatar_color": "#7B69EE"}},
    )
    app.dependency_overrides[get_cost_repo] = lambda: _FakeCostRepo(
        [{"cn": "Acme", "cap": 100, "spent": 95, "c": "#1"}], {"daily_stop": 75, "halted": False}
    )
    app.dependency_overrides[get_policy_repo] = lambda: _FakePolicyRepo(
        [{"id": "r1", "kb_ref": "k1", "title": "T", "status": "new",
          "target_module": "audit", "region": "global"}]
    )
    app.dependency_overrides[get_site_analytics_repo] = lambda: _FakeSiteAnalyticsRepo(
        [{"oauth_connected": True, "clicks_28d": 120, "impressions_28d": 4000}],
        [{"oauth_connected": False, "sessions_28d": 0, "users_28d": 0}],
    )

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


async def test_command_center_payload_shape_and_placeholder_flag(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/command-center")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _CC_KEYS
    assert len(body["statTiles"]) == 4
    assert len(body["audits"]) == 12
    # The traffic series is the explicit audit-derived PLACEHOLDER (N8).
    assert body["traffic"]["placeholder"] is True
    assert len(body["traffic"]["points"]) == 6
    assert body["team"][0]["nm"] == "Ayesha Raza"
    assert body["spend"]["flagged"][0]["cn"] == "Acme"  # 95% -> flagged
    assert body["digest"][0]["kbId"] == "k1"
    # One connected GSC property -> real numbers, not a placeholder.
    assert body["gsc"]["placeholder"] is False
    assert body["gsc"]["connected"] == 1 and body["gsc"]["clicks28d"] == 120
    # Zero connected GA4 properties -> honest placeholder.
    assert body["ga4"]["placeholder"] is True
    assert body["ga4"]["connected"] == 0


async def test_command_center_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/command-center")).status_code == 403
