"""Competitor-intel endpoints: the access gates and the wire contract.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``, the enqueuers are recorders, and the feature-grant lookup (the
one DB read inside ``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY - a test that only
ever checks the happy path would not notice one of them vanishing:

1. auth            - swept for the whole app by ``tests/test_route_auth_guard.py``;
                     re-pinned for this module's routes below.
2. competitor_intel FEATURE grant - every route.
3. view_reports (reads) / run_research (every mutation).

Plus the two that are unique to this module: the internal ``client_id`` must never
appear in any body, and the paid work must be ENQUEUED rather than run at the edge.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.core.deps import get_redis
from app.modules.competitor_intel.repo import get_competitor_repo
from app.modules.competitor_intel.router import (
    get_analysis_enqueuer,
    get_discovery_enqueuer,
)

pytestmark = pytest.mark.unit

_COMPETITOR_KEYS = {
    "code", "domain", "client", "label", "source", "tracked", "overlap",
    "keywordGaps", "commonKeywords", "shareOfVoice", "analyzed",
}

_CREATE_BODY: dict[str, Any] = {"clientId": "cl-secret", "domain": "rival.com"}
# A body every route accepts, for the sweeps that fire the same payload at all of them
# (each model ignores the keys it does not own).
_ANY_BODY: dict[str, Any] = {**_CREATE_BODY, "label": "x", "tracked": False}

_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/competitor-intel/competitors"),
    ("GET", "/api/v1/competitor-intel/stats"),
    ("GET", "/api/v1/competitor-intel/workspace"),
    ("GET", "/api/v1/competitor-intel/competitors/CI-0001/gaps"),
    ("GET", "/api/v1/competitor-intel/competitors/CI-0001/backlink-gaps"),
    ("GET", "/api/v1/competitor-intel/share-of-voice?clientId=cl-secret"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/competitor-intel/competitors", _CREATE_BODY),
    ("POST", "/api/v1/competitor-intel/discover", {"clientId": "cl-secret"}),
    ("POST", "/api/v1/competitor-intel/competitors/CI-0001/analyze", {}),
    ("POST", "/api/v1/competitor-intel/competitors/CI-0001/gaps/g-1/promote", {}),
    ("PATCH", "/api/v1/competitor-intel/competitors/CI-0001", {"label": "x"}),
    ("DELETE", "/api/v1/competitor-intel/competitors/CI-0001", {}),
]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

# The staff roles that hold run_research (mirrors the 0037 RLS write policies).
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope (invariant #5)."""
    return str(resp.json()["error"]["message"])


def _competitor_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "c-1", "code": "CI-0001", "client_id": "cl-secret",
        "client_name": "NorthPeak Dental", "domain": "rival.com", "label": "Main rival",
        "discovery_source": "manual", "tracked": True, "overlap_pct": 38.0,
        "keyword_gaps_count": 24, "common_keywords": 12, "share_of_voice": 18.0,
        "last_analyzed_at": None,
    }
    row.update(over)
    return row


def _gap_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "g-1", "competitor_id": "c-1", "client_id": "cl-secret",
        "keyword": "dental implants", "volume": 8100, "difficulty": 42.0,
        "intent": "Commercial", "competitor_position": 3, "client_position": None,
        "gap_type": "untapped", "opportunity": 71.5, "keyword_id": None,
    }
    row.update(over)
    return row


class FakeCompetitorRepo:
    """In-memory stand-in for the RLS-scoped CompetitorRepo."""

    def __init__(self) -> None:
        self.competitors: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {"tracked": 0, "keyword_gaps": 0, "share_of_voice": 0}
        self.client_names: dict[str, str] = {}
        self.by_code: dict[str, dict[str, Any]] = {}
        self.gaps: list[dict[str, Any]] = []
        self.gap_by_id: dict[str, dict[str, Any]] = {}
        self.backlinks: list[dict[str, Any]] = []
        self.positions: dict[str, int | None] = {}
        self.volumes: dict[str, int] = {}
        self.gap_positions: tuple[dict[str, int | None], dict[str, int]] = ({}, {})
        self.list_kwargs: dict[str, Any] | None = None
        self.added: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.promoted: list[str] = []
        self.deleted: list[str] = []
        self.add_returns: dict[str, Any] | None = None

    def list_competitors(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.competitors)

    def competitor_stats(self, **kwargs: Any) -> dict[str, Any]:
        return dict(self.stats)

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.by_code.get(code)

    def list_gaps(self, competitor_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.gaps)

    def get_gap(self, competitor_id: str, gap_id: str) -> dict[str, Any] | None:
        return self.gap_by_id.get(gap_id)

    def backlink_gaps(self, client_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.backlinks)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def client_positions(self, client_id: str) -> dict[str, int | None]:
        return dict(self.positions)

    def client_keyword_volumes(self, client_id: str) -> dict[str, int]:
        return dict(self.volumes)

    def competitor_gap_positions(
        self, competitor_id: str
    ) -> tuple[dict[str, int | None], dict[str, int]]:
        return self.gap_positions

    def add_competitor(self, **kwargs: Any) -> dict[str, Any] | None:
        self.added.append(kwargs)
        if self.add_returns is not None:
            return self.add_returns
        return _competitor_row(domain=kwargs["domain"], client_name=kwargs["client_name"])

    def update_competitor(self, code: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        self.updates.append((code, changes))
        row = self.by_code.get(code)
        if row is None:
            return None
        row.update(changes)
        return row

    def delete_competitor(self, code: str) -> bool:
        self.deleted.append(code)
        return code in self.by_code

    def promote_gap(self, gap_id: str, **kwargs: Any) -> tuple[str, str, bool] | None:
        self.promoted.append(gap_id)
        return ("dental implants", "KW-00001", True)


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture(autouse=True)
def ratelimit(app: FastAPI) -> dict[str, int]:
    """An in-memory stand-in for the limiter's Redis.

    Redis is unreachable in unit tests: the limiter correctly fails OPEN, but only
    AFTER paying a connection timeout on every call. An in-memory counter keeps the
    suite fast AND makes the paid routes' limits assertable for real.
    """
    counts: dict[str, int] = {}

    class _FakeRedis:
        async def incr(self, key: str) -> int:
            counts[key] = counts.get(key, 0) + 1
            return counts[key]

        async def expire(self, key: str, seconds: int) -> bool:
            return True

    app.dependency_overrides[get_redis] = _FakeRedis
    return counts


@pytest.fixture
def repo() -> FakeCompetitorRepo:
    return FakeCompetitorRepo()


@pytest.fixture
def analyzed(app: FastAPI) -> list[str]:
    calls: list[str] = []
    app.dependency_overrides[get_analysis_enqueuer] = lambda: calls.append
    return calls


@pytest.fixture
def discovered(app: FastAPI) -> list[str]:
    calls: list[str] = []
    app.dependency_overrides[get_discovery_enqueuer] = lambda: calls.append
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeCompetitorRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an in-memory
    dict so the REAL ``feature_allows`` logic still runs, unstubbed.
    """
    app.dependency_overrides[get_competitor_repo] = lambda: repo
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["competitor_intel"] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


# --------------------------------------------------------------------------- #
# 1. Gate 1 - authentication.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_authentication(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# 2. Gate 2 - the competitor_intel FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_feature_grant(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    """A manager WITHOUT the grant is refused every route - including the reads."""
    wire("manager", feature=False)
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code == 403
    assert "competitor_intel" in _message(resp)


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports (reads) / run_research (mutations).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_mutations_require_the_run_research_module_perm(
    client: httpx.AsyncClient,
    wire: Callable[..., None],
    repo: FakeCompetitorRepo,
    role: str,
    method: str,
    path: str,
    body: dict[str, Any],
) -> None:
    """Every mutation either creates or triggers CLIENT spend, so it is leads-only -
    mirroring the 0037 RLS insert/update policies.

    ``run_research`` is a MODULE perm and must go through ``require_module_perm``:
    routing it through ``require_perm`` would resolve it against DEFAULT_ROLE_PERMS,
    which does not contain it, and would therefore deny every non-owner - locking out
    the admins and managers the RLS policies DO permit.
    """
    wire(role)
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403
    assert "run_research" in _message(resp)


@pytest.mark.parametrize("role", _LEADS)
async def test_every_lead_may_mutate(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo, role: str
) -> None:
    """The other side of the same gate: owner/admin/manager all hold run_research. A
    require_perm regression would break admin + manager here while owner sailed on."""
    wire(role)
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    resp = await client.post("/api/v1/competitor-intel/competitors", json=_CREATE_BODY)
    assert resp.status_code == 201


@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_are_open_to_any_granted_staff(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo,
    method: str, path: str
) -> None:
    """A viewer holds view_reports, so a granted viewer may READ everything."""
    wire("viewer")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.request(method, path)
    assert resp.status_code == 200


async def test_a_client_may_not_read_the_competitive_set(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """Competitor intelligence is agency analysis carrying another business's ranking
    data - 0037 gives portal clients NO select policy at all, and the app gate agrees."""
    wire("client")
    resp = await client.get("/api/v1/competitor-intel/competitors")
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# 4. The wire contract - client_id NEVER leaks.
# --------------------------------------------------------------------------- #
async def test_the_competitor_body_is_the_frozen_shape_without_client_id(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    repo.competitors = [_competitor_row()]
    resp = await client.get("/api/v1/competitor-intel/competitors")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert set(body) == _COMPETITOR_KEYS
    assert body["client"] == "NorthPeak Dental"


@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_no_read_ever_leaks_the_internal_client_id(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo,
    method: str, path: str
) -> None:
    """The fake rows all CARRY ``client_id='cl-secret'``; it must never reach the wire
    on any route. ``client`` is the snapshotted display name."""
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    repo.competitors = [_competitor_row()]
    repo.by_code["CI-0001"] = _competitor_row()
    repo.gaps = [_gap_row()]
    resp = await client.request(method, path)
    assert resp.status_code == 200
    assert "cl-secret" not in resp.text


async def test_a_pure_gap_reaches_the_wire_as_null_never_zero(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    """THE module rule, end to end: the client does not rank -> ``clientPosition:
    null``. A 0 here would read as better than #1."""
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    repo.gaps = [_gap_row(client_position=None)]
    resp = await client.get("/api/v1/competitor-intel/competitors/CI-0001/gaps")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["clientPosition"] is None
    assert body["gapType"] == "untapped"


async def test_the_gaps_read_is_page_bounded(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.get("/api/v1/competitor-intel/competitors/CI-0001/gaps?limit=5&offset=10")
    assert resp.status_code == 200


async def test_the_list_read_passes_its_filters_and_page_to_the_repo(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    await client.get(
        "/api/v1/competitor-intel/competitors?clientId=cl-secret&source=serp_auto&tracked=false"
        "&limit=5&offset=10"
    )
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["client_id"] == "cl-secret"
    assert repo.list_kwargs["source"] == "serp_auto"
    assert repo.list_kwargs["tracked"] is False
    assert repo.list_kwargs["limit"] == 5
    assert repo.list_kwargs["offset"] == 10


# --------------------------------------------------------------------------- #
# 5. The paid paths are ENQUEUED, never run at the edge.
# --------------------------------------------------------------------------- #
async def test_analyze_enqueues_rather_than_pulling_inline(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo,
    analyzed: list[str],
) -> None:
    """The paid pull is cost-gated in the WORKER; the edge only enqueues."""
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.post("/api/v1/competitor-intel/competitors/CI-0001/analyze")
    assert resp.status_code == 202
    assert resp.json() == {"code": "CI-0001", "queued": True, "reason": ""}
    assert analyzed == ["c-1"]  # the internal id, never the code


async def test_discover_enqueues_the_sweep(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo,
    discovered: list[str],
) -> None:
    """One press is N paid SERPs - the worker tier absorbs it."""
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    resp = await client.post("/api/v1/competitor-intel/discover", json={"clientId": "cl-secret"})
    assert resp.status_code == 202
    assert resp.json()["queued"] is True
    assert resp.json()["client"] == "NorthPeak Dental"
    assert "cl-secret" not in resp.text
    assert discovered == ["cl-secret"]


async def test_analyze_and_discover_404_on_an_unknown_target(
    client: httpx.AsyncClient, wire: Callable[..., None], analyzed: list[str],
    discovered: list[str],
) -> None:
    """A 404 must not enqueue: paying to analyse a competitor that does not exist is
    the definition of spending to learn nothing."""
    wire("manager")
    assert (
        await client.post("/api/v1/competitor-intel/competitors/NOPE/analyze")
    ).status_code == 404
    assert (
        await client.post("/api/v1/competitor-intel/discover", json={"clientId": "nope"})
    ).status_code == 404
    assert analyzed == []
    assert discovered == []


async def test_the_discover_sweep_is_rate_limited(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo,
    discovered: list[str],
) -> None:
    """The cost gate stops the SPEND; this stops the hammering. One press is N provider
    calls, so the limit is tighter than a single-call route's."""
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    body = {"clientId": "cl-secret"}
    codes = [
        (await client.post("/api/v1/competitor-intel/discover", json=body)).status_code
        for _ in range(8)
    ]
    assert 429 in codes
    assert codes.count(202) == 6  # the configured per-minute allowance


# --------------------------------------------------------------------------- #
# 6. Create / patch / promote / delete.
# --------------------------------------------------------------------------- #
async def test_create_normalises_the_domain_before_storing_it(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    """One competitor, one bill: a URL and a bare host must not buy two analyses."""
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    resp = await client.post(
        "/api/v1/competitor-intel/competitors",
        json={"clientId": "cl-secret", "domain": "https://WWW.Rival.com/services?x=1"},
    )
    assert resp.status_code == 201
    assert repo.added[0]["domain"] == "rival.com"
    assert repo.added[0]["source"] == "manual"


async def test_create_rejects_an_unusable_domain(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    resp = await client.post(
        "/api/v1/competitor-intel/competitors", json={"clientId": "cl-secret", "domain": "   "}
    )
    assert resp.status_code == 400
    assert repo.added == []


async def test_create_409s_on_a_domain_this_client_already_tracks(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    """A duplicate competitor is a duplicate PAID analysis, so it is refused rather
    than silently created."""
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    repo.add_returns = None  # the repo's on-conflict-do-nothing returned no row

    class _ConflictRepo(FakeCompetitorRepo):
        def add_competitor(self, **kwargs: Any) -> dict[str, Any] | None:
            return None

    conflict = _ConflictRepo()
    conflict.client_names["cl-secret"] = "NorthPeak Dental"
    client._transport.app.dependency_overrides[get_competitor_repo] = lambda: conflict  # type: ignore[attr-defined]
    resp = await client.post("/api/v1/competitor-intel/competitors", json=_CREATE_BODY)
    assert resp.status_code == 409
    assert "already tracks" in _message(resp)


async def test_create_404s_on_an_unknown_client(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/competitor-intel/competitors", json=_CREATE_BODY)
    assert resp.status_code == 404
    assert repo.added == []


async def test_patch_parks_a_competitor_and_rejects_an_empty_body(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.patch(
        "/api/v1/competitor-intel/competitors/CI-0001", json={"tracked": False}
    )
    assert resp.status_code == 200
    assert repo.updates == [("CI-0001", {"tracked": False})]
    assert (
        await client.patch("/api/v1/competitor-intel/competitors/CI-0001", json={})
    ).status_code == 400


async def test_patch_ignores_an_attempt_to_repoint_the_domain(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    """The domain is half the uniqueness key and the subject of every analysed gap;
    re-pointing it would re-label another business's ranking data as this one's. The
    field is not in the model, so it is dropped - and a body carrying ONLY a domain has
    nothing to change."""
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.patch(
        "/api/v1/competitor-intel/competitors/CI-0001", json={"domain": "other.com"}
    )
    assert resp.status_code == 400
    assert repo.updates == []


async def test_promote_pushes_the_gap_into_the_bank(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    repo.gap_by_id["g-1"] = _gap_row()
    resp = await client.post(
        "/api/v1/competitor-intel/competitors/CI-0001/gaps/g-1/promote"
    )
    assert resp.status_code == 201
    assert resp.json() == {"keyword": "dental implants", "code": "KW-00001", "created": True}
    assert repo.promoted == ["g-1"]


async def test_promote_404s_on_a_gap_under_a_different_competitor(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    """The gap is looked up SCOPED to its competitor, so a valid id under the wrong
    competitor cannot be promoted through the wrong client's URL."""
    wire("manager")
    repo.by_code["CI-0001"] = _competitor_row()
    resp = await client.post(
        "/api/v1/competitor-intel/competitors/CI-0001/gaps/not-mine/promote"
    )
    assert resp.status_code == 404
    assert repo.promoted == []


async def test_delete_404s_on_an_unknown_code(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    wire("manager")
    assert (
        await client.delete("/api/v1/competitor-intel/competitors/NOPE")
    ).status_code == 404
    assert repo.deleted == []


# --------------------------------------------------------------------------- #
# 7. Share of voice.
# --------------------------------------------------------------------------- #
async def test_share_of_voice_is_flagged_provisional_and_echoes_its_curve(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeCompetitorRepo
) -> None:
    """The split is modelled from a CTR curve, not measured - so it says so, and it
    echoes the curve it used so any number can be reproduced after ops re-fits it."""
    wire("manager")
    repo.client_names["cl-secret"] = "NorthPeak Dental"
    repo.positions = {"dental implants": 1}
    repo.volumes = {"dental implants": 1_000}
    repo.competitors = [_competitor_row()]
    repo.gap_positions = ({"dental implants": 2}, {"dental implants": 1_000})

    resp = await client.get("/api/v1/competitor-intel/share-of-voice?clientId=cl-secret")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provisional"] is True
    assert body["curve"][0] == 0.316
    assert "cl-secret" not in resp.text
    # The client leads the list, and holds the bigger share from the better position.
    assert body["entries"][0]["isClient"] is True
    assert body["entries"][0]["share"] > body["entries"][1]["share"]
    assert sum(e["share"] for e in body["entries"]) == pytest.approx(100.0, abs=0.05)


async def test_share_of_voice_404s_on_an_unknown_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.get("/api/v1/competitor-intel/share-of-voice?clientId=nope")
    assert resp.status_code == 404
