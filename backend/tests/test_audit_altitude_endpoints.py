"""The macro -> micro -> nano API: shapes, RBAC, and the honesty guarantees.

Repos are faked - these assert the CONTRACT the frontend and skills will code
against, not the database. The database behaviour is covered in
tests/integration/test_audit_altitudes.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
    def __init__(
        self,
        exists: bool = True,
        *,
        previous: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
        others: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.exists = exists
        self.previous = previous
        self.history = history if history is not None else []
        self.others = others or {}

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        if audit_id in self.others:
            return self.others[audit_id]
        return {"id": audit_id, "url": "https://x.test", "depth": "deep"} if self.exists else None

    def previous_audit(self, audit_id: str) -> dict[str, Any] | None:
        return self.previous

    def audits_of_same_site(self, audit_id: str) -> list[dict[str, Any]]:
        return list(self.history)


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

    def finding_count(self, audit_id, **kw):
        # Accepts the same filters as `findings`, because the route now passes
        # them: counting every finding regardless of filter made a filtered page
        # report a total for the whole audit.
        self.calls.append(("finding_count", kw))
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
    def _as(
        role: str = "manager", *, audit_exists: bool = True, audits: Any | None = None
    ) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_audits_repo] = lambda: audits or FakeAuditsRepo(audit_exists)
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


async def test_the_findings_total_honours_the_same_filters_as_the_page(client, wire, altitudes):
    """The count used to ignore every filter, so a severity-filtered request
    returned 14 rows and a total of 461. A pager then read "1 to 100 of 461"
    over a set of 14, and nothing in the UI contradicted it."""
    wire()
    r = await client.get(
        f"{API}/audits/{AUDIT}/findings",
        params={"severity": "critical", "dimension": "technical"},
    )
    assert r.status_code == 200

    counted = [kw for name, kw in altitudes.calls if name == "finding_count"]
    assert counted, "the route never asked for a count"
    assert counted[0]["severity"] == "critical"
    assert counted[0]["dimension"] == "technical"


# ------------------------------------------------------- SINCE LAST AUDIT
#
# "Fixed" is the word a client hears as a promise, so the route's job is to be careful about
# exactly one claim: a finding that vanished because THIS run did not measure its dimension
# is `unchecked`, never `fixed`. The pure comparison is covered in test_audit_compare.py;
# what is asserted here is the ROUTE's behaviour around it - the calm first-audit state, the
# different-site refusal, and that the withheld score delta carries its reason.


class _CompareRepo(FakeAltitudeRepo):
    """Two runs' findings + coverage, keyed by audit id."""

    def __init__(self, before: Any, after: Any, before_roll: Any, after_roll: Any) -> None:
        super().__init__()
        self._by_id = {"aud-0": (before, before_roll), "aud-1": (after, after_roll)}

    def findings(self, audit_id, **kw):  # type: ignore[override]
        return list(self._by_id.get(audit_id, ([], []))[0])

    def rollups(self, audit_id, *, level=None):  # type: ignore[override]
        rows = self._by_id.get(audit_id, ([], []))[1]
        return [r for r in rows if level is None or r["level"] == level]


def _finding(check: str, *, pages: int = 1, sev: str = "critical", dim: str = "onpage"):
    return {
        "id": f"f-{check}", "check_id": check, "check_name": f"{check} name",
        "severity": sev, "instance_count": pages, "pages_affected": pages,
        "dimension": dim, "pillar": "on-page", "subcategory": "x",
    }


def _dim(key: str, *, score: Any, ran: int, basis: str = "b1"):
    return {
        "level": "dimension", "key": key, "label": key.title(), "score": score,
        "checks_ran": ran, "checks_applicable": 100, "basis_hash": basis,
    }


async def test_a_first_audit_says_so_calmly_instead_of_failing(client, wire):
    wire(audits=FakeAuditsRepo(previous=None, history=[{"id": "aud-1", "created_at": None,
                                                        "depth": "deep", "score": 61}]))
    r = await client.get(f"{API}/audits/{AUDIT}/compare")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "first completed audit" in body["reason"]
    # The history is still returned, so the picker can offer runs once there are some.
    assert body["runs"][0]["id"] == "aud-1"


async def test_a_vanished_finding_from_an_unmeasured_dimension_is_never_fixed(
    client, app, wire
):
    """The one outright lie this feature could tell, asserted at the route."""
    wire(audits=FakeAuditsRepo(previous={"id": "aud-0", "created_at": None, "depth": "deep"}))
    # AFTER wire(), which sets its own findings-repo override.
    app.dependency_overrides[get_audit_findings_repo] = lambda: _CompareRepo(
        before=[_finding("ON-041"), _finding("OFF-002", dim="offpage")],
        after=[_finding("ON-041")],
        before_roll=[_dim("onpage", score=70, ran=25), _dim("offpage", score=40, ran=10)],
        after_roll=[_dim("onpage", score=80, ran=25), _dim("offpage", score=None, ran=0)],
    )
    r = await client.get(f"{API}/audits/{AUDIT}/compare")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert [f["checkId"] for f in body["unchecked"]] == ["OFF-002"]
    assert body["fixed"] == []
    assert body["counts"]["fixed"] == 0 and body["counts"]["unchecked"] == 1


async def test_comparing_two_different_sites_is_refused_not_rendered(client, wire):
    wire(audits=FakeAuditsRepo(
        previous=None,
        others={"aud-9": {"id": "aud-9", "url": "https://other.test", "depth": "deep"}},
    ))
    r = await client.get(f"{API}/audits/{AUDIT}/compare?to=aud-9")
    assert r.status_code == 409
    assert "different sites" in r.json()["error"]["message"]


async def test_an_unknown_baseline_is_a_404(client, wire):
    wire(audits=FakeAuditsRepo(previous=None))
    # `others` is empty and get_audit answers for any id, so ask for the one id the fake
    # deliberately cannot resolve: a repo with exists=False.
    wire(audits=FakeAuditsRepo(exists=False))
    r = await client.get(f"{API}/audits/{AUDIT}/compare?to=aud-missing")
    assert r.status_code == 404


async def test_the_compare_route_is_reads_only_and_open_to_any_report_viewer(client, wire):
    wire("analyst", audits=FakeAuditsRepo(previous=None))
    assert (await client.get(f"{API}/audits/{AUDIT}/compare")).status_code == 200


async def test_a_client_cannot_reach_it(client, wire):
    wire("client", audits=FakeAuditsRepo(previous=None))
    assert (await client.get(f"{API}/audits/{AUDIT}/compare")).status_code == 403

