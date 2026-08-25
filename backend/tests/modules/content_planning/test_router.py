"""P4: the engagement planning endpoints - access gates, and read-only by design.

No DB and no network: the repo is an in-memory fake injected through
``dependency_overrides``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.content_planning.repo import get_content_planning_repo

pytestmark = pytest.mark.unit

_HAS_RUN_AUDITS = ["owner", "admin", "manager", "specialist", "analyst"]
_VIEWER_ONLY = ["viewer"]


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000c1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="cp@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="CP", title="", avatar_color="#000", phone="", two_fa=False, client_id=None,
    )


def _row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "e1", "shape": "page_set", "status": "ready", "name": "Spring pages",
        "client_id": "c1", "client_name": "Delaney Plumbing",
        "scope": {"services": ["slab leak repair"], "cities": ["San Jose"]},
        "budget_cap": 50.0, "page_target": 12, "source_audit_id": None,
        "owner_id": None, "created_at": "2026-08-25T00:00:00Z",
    }
    base.update(over)
    return base


def _node(kw: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": kw, "map_id": "m1", "primary_keyword": kw, "status": "planned",
        "parent_id": None, "silo": "repairs", "page_type": "service",
        "secondary_keywords": [], "intent": "commercial", "target_city": "San Jose",
        "priority": 0, "target_words": 1200, "cluster_key": "slab",
        "evidence": "", "info_gain_thesis": "", "content_job_id": None,
        "published_url": "",
    }
    base.update(over)
    return base


class FakeRepo:
    def __init__(self) -> None:
        self.engagements: dict[str, dict[str, Any]] = {}
        self.nodes: list[dict[str, Any]] = []
        self.terms: list[dict[str, Any]] = []
        self.brand_kit = False

    def list_engagements(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = list(self.engagements.values())
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows[:limit]

    def get_engagement(self, engagement_id: str) -> dict[str, Any] | None:
        return self.engagements.get(engagement_id)

    def map_nodes(self, engagement_id: str) -> list[dict[str, Any]]:
        return list(self.nodes)

    def keyword_terms(self, engagement_id: str, *, limit: int = 2000) -> list[dict[str, Any]]:
        return self.terms[:limit]

    def has_brand_kit(self, client_id: str | None) -> bool:
        return self.brand_kit


@pytest.fixture
def repo(app: FastAPI) -> FakeRepo:
    fake = FakeRepo()
    fake.engagements["e1"] = _row()
    app.dependency_overrides[get_content_planning_repo] = lambda: fake
    return fake


def _as(app: FastAPI, role: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: _user(role)


class TestAccess:
    @pytest.mark.parametrize("role", _HAS_RUN_AUDITS + _VIEWER_ONLY)
    async def test_reading_an_engagement_needs_only_view_reports(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo, role: str
    ) -> None:
        _as(app, role)
        assert (await client.get("/api/v1/content/engagements")).status_code == 200

    @pytest.mark.parametrize("role", _VIEWER_ONLY)
    async def test_the_work_plan_needs_run_audits_because_it_reports_budget(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo, role: str
    ) -> None:
        _as(app, role)
        resp = await client.get("/api/v1/content/engagements/e1/plan")
        assert resp.status_code == 403

    @pytest.mark.parametrize("role", _HAS_RUN_AUDITS)
    async def test_staff_with_run_audits_can_read_the_plan(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo, role: str
    ) -> None:
        _as(app, role)
        assert (await client.get("/api/v1/content/engagements/e1/plan")).status_code == 200


class TestReadOnlyByDesign:
    async def test_there_is_no_write_route_on_this_module(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo
    ) -> None:
        """Every write path runs in the pipeline, where the SME halt, the uniqueness
        gate and the engagement budget live. An endpoint that enqueued production would
        sit in FRONT of those checks instead of behind them."""
        from app.modules.content_planning.router import router

        methods = {m for r in router.routes for m in getattr(r, "methods", set())}
        assert methods <= {"GET", "HEAD"}, f"unexpected write methods: {methods}"


class TestAnEngagementRlsHidLooksAbsent:
    async def test_a_hidden_engagement_is_404_not_403(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo
    ) -> None:
        """Distinguishing them would confirm the row exists to a caller who is not
        allowed to know that."""
        _as(app, "owner")
        for path in ("", "/plan", "/keywords"):
            resp = await client.get(f"/api/v1/content/engagements/nope{path}")
            assert resp.status_code == 404


class TestThePlanEndpoint:
    async def test_it_reports_the_shape_and_what_that_shape_runs(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo
    ) -> None:
        _as(app, "owner")
        body = (await client.get("/api/v1/content/engagements/e1")).json()
        assert body["shape"] == "page_set"
        assert "keyword_discovery" in body["runs"]["engagement_stages"]
        assert body["runs"]["page_stages"][0] == "sme"

    async def test_pages_come_back_grouped_for_the_doctrine_cache(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo
    ) -> None:
        repo.nodes = [_node("a", page_type="service"), _node("b", page_type="local"),
                      _node("c", page_type="service")]
        _as(app, "owner")
        body = (await client.get("/api/v1/content/engagements/e1/plan")).json()
        assert [p["page_type"] for p in body["pages"]] == ["local", "service", "service"]

    async def test_a_blocked_prerequisite_is_explained_not_just_flagged(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo
    ) -> None:
        repo.engagements["e1"] = _row(shape="full_site")
        repo.nodes = [_node("a")]
        repo.brand_kit = False
        _as(app, "owner")
        body = (await client.get("/api/v1/content/engagements/e1/plan")).json()
        assert body["can_start"] is False
        assert "brand_kit" in body["readiness"]["missing"]
        assert any("different people" in r for r in body["readiness"]["reasons"])


class TestKeywordsCarryProvenance:
    async def test_every_term_says_whether_it_was_bought_or_derived(
        self, app: FastAPI, client: httpx.AsyncClient, repo: FakeRepo
    ) -> None:
        """A UI showing volume without saying whether it was measured reproduces v1's
        central lie in a nicer font."""
        repo.terms = [
            {"keyword": "a", "volume": 880, "estimated": False, "cluster_key": "x"},
            {"keyword": "b", "volume": 170, "estimated": True, "cluster_key": "x"},
        ]
        _as(app, "owner")
        body = (await client.get("/api/v1/content/engagements/e1/keywords")).json()
        assert body["total"] == 2 and body["measured"] == 1 and body["estimated"] == 1
        assert {t["estimated"] for t in body["terms"]} == {True, False}
