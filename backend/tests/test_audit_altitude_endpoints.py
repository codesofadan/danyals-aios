"""The macro -> micro -> nano API: shapes, RBAC, and the honesty guarantees.

Repos are faked - these assert the CONTRACT the frontend and skills will code
against, not the database. The database behaviour is covered in
tests/integration/test_audit_altitudes.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.audit_findings_repo import get_audit_findings_repo
from app.db.audits_repo import get_audits_repo

pytestmark = pytest.mark.unit

AUDIT = "aud-1"
#: Every route in this app is mounted under the versioned prefix.
API = "/api/v1"


class FakeAuditsRepo:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        return {"id": audit_id, "url": "https://x.test"} if self.exists else None


class FakeAltitudeRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._rollups = [
            {"level": "dimension", "key": "technical", "label": "Technical",
             "score": 97.2, "checks_ran": 25, "checks_applicable": 100},
            {"level": "dimension", "key": "strategy", "label": "Strategy",
             "score": None, "checks_ran": 0, "checks_applicable": 21},
        ]
        self._findings = [{
            "id": "f-1", "check_id": "ON-041", "check_name": "H1 optimization",
            "severity": "critical", "instance_count": 42, "pages_affected": 42,
            "dimension": "onpage", "pillar": "on-page", "subcategory": "headings",
        }]
        self._instances = [
            {"url": f"https://x.test/p{i}", "check_id": "ON-041"} for i in range(3)
        ]

    def rollups(self, audit_id, *, level=None):
        self.calls.append(("rollups", {"level": level}))
        return [r for r in self._rollups if level is None or r["level"] == level]

    def findings(self, audit_id, **kw):
        self.calls.append(("findings", kw))
        return list(self._findings)

    def finding_count(self, audit_id):
        return len(self._findings)

    def instances(self, audit_id, **kw):
        self.calls.append(("instances", kw))
        return list(self._instances)

    def instance_count(self, audit_id, *, finding_id=None):
        return len(self._instances)

    def pages(self, audit_id, **kw):
        self.calls.append(("pages", kw))
        return [{"url": "https://x.test/", "issues_total": 3}]

    def roadmap(self, audit_id):
        self.calls.append(("roadmap", {}))
        return (
            {"id": "r-1", "capacity_points_per_month": 40, "items_planned": 1,
             "items_backlog": 0, "start_date": None},
            [{"phase": "p0_30d", "sequence": 1, "title": "Fix H1 - 42 pages",
              "owner_role": "seo_specialist"}],
        )


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def altitudes() -> FakeAltitudeRepo:
    return FakeAltitudeRepo()


@pytest.fixture
def wire(app: FastAPI, altitudes: FakeAltitudeRepo) -> Callable[..., None]:
    def _as(role: str = "manager", *, audit_exists: bool = True) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_audits_repo] = lambda: FakeAuditsRepo(audit_exists)
        app.dependency_overrides[get_audit_findings_repo] = lambda: altitudes
    return _as


# ----------------------------------------------------------------- MACRO

async def test_rollups_return_score_and_its_coverage(client, wire):
    wire()
    r = await client.get(f"{API}/audits/{AUDIT}/rollups")
    assert r.status_code == 200
    tech = next(x for x in r.json() if x["key"] == "technical")
    assert tech["score"] == 97.2
    assert tech["checks_ran"] == 25 and tech["checks_applicable"] == 100


async def test_an_unmeasured_dimension_returns_null_score_not_zero(client, wire):
    """A caller rendering `score or 0` would report an unmeasured dimension as a
    failing one. The API must make that distinguishable."""
    wire()
    r = await client.get(f"{API}/audits/{AUDIT}/rollups")
    strategy = next(x for x in r.json() if x["key"] == "strategy")
    assert strategy["score"] is None
    assert strategy["checks_ran"] == 0


async def test_rollups_can_be_filtered_to_one_level(client, wire, altitudes):
    wire()
    await client.get(f"{API}/audits/{AUDIT}/rollups", params={"level": "dimension"})
    assert altitudes.calls[-1] == ("rollups", {"level": "dimension"})


async def test_an_unknown_level_is_rejected(client, wire):
    wire()
    r = await client.get(f"{API}/audits/{AUDIT}/rollups", params={"level": "galaxy"})
    assert r.status_code == 422


# ----------------------------------------------------------------- MICRO

async def test_findings_are_causes_with_a_blast_radius(client, wire):
    wire()
    r = await client.get(f"{API}/audits/{AUDIT}/findings")
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["instance_count"] == 42
    assert item["check_name"] == "H1 optimization"


async def test_findings_are_filterable_along_the_pillar_subpoint_spine(client, wire, altitudes):
    wire()
    await client.get(f"{API}/audits/{AUDIT}/findings", params={
        "dimension": "onpage", "subcategory": "headings", "severity": "critical"})
    _, kw = altitudes.calls[-1]
    assert kw["dimension"] == "onpage"
    assert kw["subcategory"] == "headings"
    assert kw["severity"] == "critical"


async def test_finding_paging_is_bounded(client, wire):
    """A single audit can hold hundreds of causes; an unbounded page would let a
    caller pull the whole table in one request."""
    wire()
    assert (await client.get(f"{API}/audits/{AUDIT}/findings", params={"limit": 5000})).status_code == 422
    assert (await client.get(f"{API}/audits/{AUDIT}/findings", params={"limit": 0})).status_code == 422


# ------------------------------------------------------------------ NANO

async def test_instances_enumerate_every_occurrence_of_one_cause(client, wire):
    wire()
    r = await client.get(f"{API}/audits/{AUDIT}/findings/f-1/instances")
    body = r.json()
    assert body["total"] == 3
    assert [i["url"] for i in body["items"]] == [
        "https://x.test/p0", "https://x.test/p1", "https://x.test/p2"]


async def test_instances_are_scoped_to_the_requested_finding(client, wire, altitudes):
    wire()
    await client.get(f"{API}/audits/{AUDIT}/findings/f-9/instances")
    _, kw = altitudes.calls[-1]
    assert kw["finding_id"] == "f-9"


# --------------------------------------------------------------- roadmap

async def test_the_roadmap_groups_items_into_relative_windows(client, wire):
    wire()
    r = await client.get(f"{API}/audits/{AUDIT}/roadmap")
    body = r.json()
    phases = {p["phase"] for p in body["phases"]}
    assert "p0_30d" in phases and "backlog" in phases
    first = next(p for p in body["phases"] if p["phase"] == "p0_30d")
    assert first["items"][0]["title"].startswith("Fix H1")


async def test_the_roadmap_surfaces_the_capacity_assumption_it_rests_on(client, wire):
    """Every timeline number derives from this one operator input, so a caller
    must be able to show it rather than present the schedule as measured."""
    wire()
    body = (await client.get(f"{API}/audits/{AUDIT}/roadmap")).json()
    assert body["roadmap"]["capacity_points_per_month"] == 40
    assert body["roadmap"]["start_date"] is None


async def test_the_roadmap_publishes_the_effort_model(client, wire):
    wire()
    body = (await client.get(f"{API}/audits/{AUDIT}/roadmap")).json()
    assert body["effort_model"]["priority"] == "impact / effort"
    assert "locus" in body["effort_model"]


# --------------------------------------------------------- guards + RBAC

async def test_every_staff_role_including_viewer_can_read_an_audit(client, wire):
    """`view_reports` is held by all six staff roles (matrix.py:244-249), so the
    guard separates STAFF from client, not analyst from viewer. Asserting the
    positive contract keeps this test honest about what the permission does."""
    from app.rbac.matrix import DEFAULT_ROLE_PERMS
    assert "view_reports" in DEFAULT_ROLE_PERMS["viewer"]
    wire("viewer")
    for path in (
        f"{API}/audits/{AUDIT}/rollups", f"{API}/audits/{AUDIT}/findings",
        f"{API}/audits/{AUDIT}/findings/f-1/instances", f"{API}/audits/{AUDIT}/pages",
        f"{API}/audits/{AUDIT}/roadmap",
    ):
        assert (await client.get(path)).status_code == 200, path


async def test_the_altitude_routes_are_guarded_by_view_reports(client, wire):
    """The dependency itself, asserted structurally: if someone removes the guard
    the route keeps working and no behavioural test would notice."""
    from app.routers import audit_findings as mod
    assert mod.ViewReports.__metadata__[0].dependency.__qualname__.startswith("require_perm")


async def test_an_unknown_audit_is_404_at_every_altitude(client, wire):
    wire(audit_exists=False)
    for path in (
        f"{API}/audits/{AUDIT}/rollups", f"{API}/audits/{AUDIT}/findings",
        f"{API}/audits/{AUDIT}/pages", f"{API}/audits/{AUDIT}/roadmap",
    ):
        assert (await client.get(path)).status_code == 404, path


async def test_only_allow_listed_downloads_resolve(client, wire):
    """`name` is checked against the allow-list BEFORE any path is built, so a
    traversal attempt never reaches the filesystem."""
    wire()
    for bad in ("../../etc/passwd", "secrets.env", "report.pdf%00.csv"):
        assert (await client.get(f"{API}/audits/{AUDIT}/download/{bad}")).status_code == 404
