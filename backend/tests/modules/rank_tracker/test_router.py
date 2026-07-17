"""Rank-tracker endpoints: the access gates, the wire contract, and the N-A commitment
gate at the edge.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``, the check enqueuer is a recorder, and the feature-grant lookup
(the one DB read inside ``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY - a test that only
ever checks the happy path would not notice one of them vanishing:

1. auth            - swept for the whole app by ``tests/test_route_auth_guard.py``;
                     re-pinned for this module's 7 routes below.
2. rank_tracker FEATURE grant - every route.
3. view_reports (reads) / run_research (every mutation).

Plus the one that is unique to this module: ``POST /keywords`` must REFUSE an add whose
standing monthly commitment would breach the client's remaining budget (N-A).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.core.auth import CurrentUser, get_current_user
from app.core.deps import get_redis
from app.modules.rank_tracker.repo import get_rank_repo
from app.modules.rank_tracker.router import get_check_enqueuer

pytestmark = pytest.mark.unit

_KEYWORD_KEYS = {
    "code", "keyword", "client", "position", "change", "bestPosition", "url",
    "targetUrl", "tags", "engine", "device", "location", "cadence", "status",
    "features", "checked", "stale",
}

_ADD_BODY: dict[str, Any] = {"clientId": "cl-secret", "keywords": ["plumber karachi"]}
# A body every route accepts, for the sweeps that fire the same payload at all of them:
# the add fields plus a valid PATCH field (both models ignore the keys they do not own).
_ANY_BODY: dict[str, Any] = {**_ADD_BODY, "status": "paused"}

# (method, path) for every route the module publishes.
_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/rank-tracker/keywords"),
    ("GET", "/api/v1/rank-tracker/stats"),
    ("GET", "/api/v1/rank-tracker/workspace"),
    ("GET", "/api/v1/rank-tracker/keywords/RK-00001/history"),
    ("GET", "/api/v1/rank-tracker/cost-projection?clientId=cl-secret"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/rank-tracker/keywords", _ADD_BODY),
    ("POST", "/api/v1/rank-tracker/keywords/RK-00001/check", {}),
    ("PATCH", "/api/v1/rank-tracker/keywords/RK-00001", {"status": "paused"}),
]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

# The staff roles that hold run_research (mirrors the 0036 RLS write policies).
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope (invariant #5)."""
    return str(resp.json()["error"]["message"])


def _keyword_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "kw-1", "code": "RK-00001", "client_id": "cl-secret",
        "client_name": "NorthPeak Dental", "keyword": "dental implants karachi",
        "normalized_keyword": "dental implants karachi", "site_id": None,
        "target_url": "https://np.example/x", "engine": "google", "device": "desktop",
        "location": "Karachi,Pakistan", "language": "en", "country": "pk",
        "tags": ["money"], "cadence": "weekly", "status": "active", "latest_position": 3,
        "latest_url": "https://np.example/y", "previous_position": 7, "best_position": 2,
        "latest_features": ["local_pack"], "latest_checked_at": datetime.now(UTC),
    }
    row.update(over)
    return row


class FakeRankRepo:
    """In-memory stand-in for the RLS-scoped RankRepo."""

    def __init__(self) -> None:
        self.keywords: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {"tracked": 0, "avg_position": 0, "top_three": 0}
        self.client_names: dict[str, str] = {}
        self.by_code: dict[str, dict[str, Any]] = {}
        self.history_rows: list[dict[str, Any]] = []
        self.cadence_counts: dict[str, int] = {}
        self.budget: tuple[float, float] | None = None
        self.list_kwargs: dict[str, Any] | None = None
        self.stats_kwargs: dict[str, Any] | None = None
        self.history_kwargs: tuple[str, dict[str, Any]] | None = None
        self.added: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def list_keywords(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.keywords)

    def rank_stats(self, **kwargs: Any) -> dict[str, Any]:
        self.stats_kwargs = kwargs
        return dict(self.stats)

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.by_code.get(code)

    def history(self, keyword_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.history_kwargs = (keyword_id, kwargs)
        return list(self.history_rows)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def active_cadence_counts(self, client_id: str) -> dict[str, int]:
        return dict(self.cadence_counts)

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self.budget

    def add_keywords(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.added.append(kwargs)
        return [
            _keyword_row(
                code=f"RK-{i:05d}", keyword=display, client_id=kwargs["client_id"],
                client_name=kwargs["client_name"], cadence=kwargs["cadence"],
            )
            for i, (display, _norm) in enumerate(kwargs["keywords"], start=1)
        ]

    def update_keyword(self, code: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        self.updates.append((code, changes))
        row = self.by_code.get(code)
        if row is None:
            return None
        row.update(changes)
        return row


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
    AFTER paying a connection timeout on every call - which made this file take ~100s.
    An in-memory counter keeps the suite fast AND makes the check route's limit
    assertable for real rather than merely fail-open.
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
def live_provider(app: FastAPI) -> None:
    """Pin a LIVE, priced vendor so the commitment gate has something to price.

    Without a key the module degrades to the fake at $0/check - honest, and covered by
    its own test - but it makes every book free, which would render the N-A budget
    tests vacuous.
    """
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", serper_api_key="test-key",
        rank_tracker_cost_estimate=0.001, rank_tracker_depth=100,
    )


@pytest.fixture
def pricey_provider(app: FastAPI) -> None:
    """A live vendor at $0.10/page = $1.00 per depth-100 check.

    The PATCH gate acts on ONE subscription, and at the real Serper price one
    weekly->daily flip moves the monthly bill by ~$0.26 - too small to write a legible
    budget scenario around. At $1/check a weekly keyword costs ~$4.35/mo and a daily
    one ~$30.44/mo, so the upgrade is unmistakable and the arithmetic stays readable.
    """
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev", serper_api_key="test-key",
        rank_tracker_cost_estimate=0.1, rank_tracker_depth=100,
    )


@pytest.fixture
def repo() -> FakeRankRepo:
    return FakeRankRepo()


@pytest.fixture
def enqueued(app: FastAPI) -> list[tuple[str, bool]]:
    """Recorder for the check enqueuer dep (never touches Celery's broker)."""
    calls: list[tuple[str, bool]] = []
    app.dependency_overrides[get_check_enqueuer] = lambda: (
        lambda keyword_id, force: calls.append((keyword_id, force))
    )
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeRankRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an in-memory
    dict so the REAL ``feature_allows`` logic still runs, unstubbed.
    """
    app.dependency_overrides[get_rank_repo] = lambda: repo
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["rank_tracker"] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


# --------------------------------------------------------------------------- #
# 1. Gate 1 - authentication.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_rejects_an_unauthenticated_caller(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    # No identity override + no bearer -> 401 before any repo/DB is touched.
    assert (await client.request(method, path)).status_code == 401


# --------------------------------------------------------------------------- #
# 2. Gate 2 - the rank_tracker FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_rank_tracker_feature(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    # A manager holds BOTH view_reports and run_research, so an ungranted feature is the
    # only thing that can reject here.
    wire("manager", feature=False)
    resp = await client.request(method, path, json=dict(_ADD_BODY))
    assert resp.status_code == 403, resp.text
    assert "rank_tracker" in _message(resp)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[Any], method: str, path: str
) -> None:
    # Owner short-circuits require_feature (no grant lookup at all).
    repo.by_code["RK-00001"] = _keyword_row()
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    wire("owner", feature=False)
    resp = await client.request(method, path, json=dict(_ADD_BODY))
    assert resp.status_code != 403, resp.text


async def test_a_view_only_grant_does_not_satisfy_a_full_feature_requirement(
    app: FastAPI, client: httpx.AsyncClient, repo: FakeRankRepo,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_rank_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: {"rank_tracker": "view"}
    )
    resp = await client.get("/api/v1/rank-tracker/keywords")
    assert resp.status_code == 403  # require_feature defaults to level="full"


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports on reads, run_research on mutations.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_require_view_reports(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    # A portal client holds NO staff permission. It is granted the feature here on
    # purpose: this pins view_reports as an INDEPENDENT gate, so the staff read surface
    # stays closed to clients even if a grant row were somehow created for one. (A
    # client's own rank data reaches them through the 0036 portal view instead.)
    wire("client")
    resp = await client.request(method, path)
    assert resp.status_code == 403, resp.text
    assert "view_reports" in _message(resp)


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_mutations_require_run_research(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[Any], role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    """Every mutation either CREATES client spend (an add, a cadence change) or TRIGGERS
    it (an on-demand check), so all of them are LEADS-only.

    This mirrors the 0036 RLS insert/update policies exactly: a role that passed this
    gate but failed RLS would get an opaque database error instead of a clean 403.
    """
    repo.by_code["RK-00001"] = _keyword_row()
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, f"{role} must not {method} {path}: {resp.text}"
    assert "run_research" in _message(resp)
    assert enqueued == []  # no paid work was queued
    assert repo.added == [] and repo.updates == []  # nothing was written


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_non_lead_staff_may_still_read_the_board(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None], role: str
) -> None:
    # run_research gates the WRITES only - a specialist/analyst/viewer keeps the read
    # surface (RLS likewise lets any staff select).
    repo.keywords = [_keyword_row()]
    wire(role)
    assert (await client.get("/api/v1/rank-tracker/keywords")).status_code == 200


@pytest.mark.parametrize("role", _LEADS)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_leads_may_mutate(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[Any], role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row(latest_checked_at=None)
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201, 202), f"{role} must {method} {path}: {resp.text}"


# --------------------------------------------------------------------------- #
# 4. The internal client_id must NEVER surface.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_client_id_never_appears_in_any_response_body(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[Any], method: str, path: str
) -> None:
    """Every fixture row carries the secret tenant id; no route may echo it back."""
    repo.keywords = [_keyword_row()]
    repo.by_code["RK-00001"] = _keyword_row(latest_checked_at=None)
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    repo.stats = {"tracked": 1, "avg_position": 3.0, "top_three": 1}
    repo.history_rows = [
        {"checked_on": "2026-07-16", "position": 3, "ranking_url": "/x",
         "serp_features": [], "delta": 4, "client_id": "cl-secret"}
    ]
    wire("owner")
    resp = await client.request(method, path, json=dict(_ANY_BODY))
    assert resp.status_code in (200, 201, 202), resp.text
    raw = resp.text
    assert "client_id" not in raw and "clientId" not in raw
    assert "cl-secret" not in raw  # not the key NOR the value


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/rank-tracker/keywords", None),
        ("POST", "/api/v1/rank-tracker/keywords", _ADD_BODY),
        ("PATCH", "/api/v1/rank-tracker/keywords/RK-00001", {"status": "paused"}),
    ],
)
async def test_the_client_snapshot_name_is_what_replaces_the_hidden_id(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    """The other half of the contract: hiding ``client_id`` must not mean showing
    NOTHING - every route whose model carries ``client`` emits the display snapshot."""
    repo.keywords = [_keyword_row()]
    repo.by_code["RK-00001"] = _keyword_row()
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    wire("owner")
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201), resp.text
    payload = resp.json()
    if isinstance(payload, dict) and "keywords" in payload:
        payload = payload["keywords"]
    row = payload[0] if isinstance(payload, list) else payload
    assert row["client"] == "NorthPeak Dental"
    assert "cl-secret" not in resp.text


async def test_list_keywords_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.keywords = [_keyword_row()]
    wire("viewer")
    resp = await client.get("/api/v1/rank-tracker/keywords")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == _KEYWORD_KEYS
    assert row["client"] == "NorthPeak Dental"  # the snapshot, not the id
    assert row["change"] == {"value": "4", "direction": "up"}  # 7 -> 3 is an improvement


# --------------------------------------------------------------------------- #
# 5. Reads: filters, pagination, shapes.
# --------------------------------------------------------------------------- #
async def test_list_honors_the_page_dep(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/rank-tracker/keywords", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 5 and repo.list_kwargs["offset"] == 10


async def test_list_defaults_to_the_capped_page(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/rank-tracker/keywords")
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 50 and repo.list_kwargs["offset"] == 0


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_list_rejects_an_out_of_range_page(
    client: httpx.AsyncClient, wire: Callable[..., None], params: dict[str, int]
) -> None:
    # The hard caps are enforced at the edge - no handler can ask for an unbounded page.
    wire("viewer")
    assert (
        await client.get("/api/v1/rank-tracker/keywords", params=params)
    ).status_code == 422


async def test_list_passes_every_filter_through_to_the_repo(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/rank-tracker/keywords", params={
        "clientId": "cl-1", "status": "paused", "engine": "bing", "device": "mobile",
        "tag": "money",
    })
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["client_id"] == "cl-1"
    assert repo.list_kwargs["status"] == "paused"
    assert repo.list_kwargs["engine"] == "bing"
    assert repo.list_kwargs["device"] == "mobile"
    assert repo.list_kwargs["tag"] == "money"


async def test_list_filters_default_to_none_not_a_silent_narrowing(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/rank-tracker/keywords")
    assert repo.list_kwargs is not None
    for key in ("client_id", "status", "engine", "device", "tag"):
        assert repo.list_kwargs[key] is None


@pytest.mark.parametrize("params", [{"engine": "yahoo"}, {"device": "watch"}])
async def test_list_rejects_an_off_enum_filter(
    client: httpx.AsyncClient, wire: Callable[..., None], params: dict[str, str]
) -> None:
    wire("viewer")
    assert (
        await client.get("/api/v1/rank-tracker/keywords", params=params)
    ).status_code == 422


async def test_an_unranked_row_reports_a_null_position_never_zero(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    """The end-to-end version of the module's central distinction."""
    repo.keywords = [_keyword_row(latest_position=None, previous_position=4)]
    wire("viewer")
    row = (await client.get("/api/v1/rank-tracker/keywords")).json()[0]
    assert row["position"] is None
    assert row["change"] == {"value": "lost", "direction": "lost"}


async def test_a_stalled_keyword_is_flagged_stale_on_the_wire(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    """The visible half of the degrade path: a blocked money-dial must not leave the
    board silently showing last month's position as if it were fresh."""
    repo.keywords = [
        _keyword_row(latest_checked_at=datetime.now(UTC) - timedelta(days=30)),
        _keyword_row(code="RK-00002", latest_checked_at=datetime.now(UTC)),
    ]
    wire("viewer")
    rows = (await client.get("/api/v1/rank-tracker/keywords")).json()
    assert rows[0]["stale"] is True
    assert rows[1]["stale"] is False


async def test_stats_shape(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.stats = {"tracked": 128, "avg_position": 8.44, "top_three": 34}
    wire("analyst")
    resp = await client.get("/api/v1/rank-tracker/stats")
    assert resp.status_code == 200
    assert resp.json() == {"tracked": 128, "avgPosition": 8.4, "topThree": 34}


async def test_stats_can_be_scoped_to_a_client(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("analyst")
    await client.get("/api/v1/rank-tracker/stats", params={"clientId": "cl-1"})
    assert repo.stats_kwargs == {"client_id": "cl-1"}


async def test_workspace_returns_the_tool_extra_shape(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.stats = {"tracked": 128, "avg_position": 8.4, "top_three": 34}
    repo.keywords = [_keyword_row()]
    wire("viewer")
    resp = await client.get("/api/v1/rank-tracker/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"kpis", "table", "primary", "bullets"}
    assert body["table"]["cols"] == ["Keyword", "Client", "Position", "Change"]
    assert [k["label"] for k in body["kpis"]] == [
        "Tracked keywords", "Avg. position", "Top-3 keywords"
    ]
    assert body["primary"] == {"label": "Add keywords", "icon": "add"}


async def test_workspace_asks_the_repo_for_only_the_top_eight(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/rank-tracker/workspace")
    assert repo.list_kwargs == {"limit": 8, "offset": 0}


async def test_history_resolves_the_code_then_reads_by_id(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    repo.history_rows = [
        {"checked_on": "2026-07-16", "position": 3, "ranking_url": "/x",
         "serp_features": ["local_pack"], "delta": 4}
    ]
    wire("viewer")
    resp = await client.get(
        "/api/v1/rank-tracker/keywords/RK-00001/history", params={"limit": 30}
    )
    assert resp.status_code == 200
    assert repo.history_kwargs == ("kw-1", {"limit": 30})
    assert resp.json() == [
        {"date": "Jul 16, 2026", "position": 3, "url": "/x",
         "features": ["local_pack"], "delta": 4}
    ]


async def test_history_of_an_unknown_code_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    assert (
        await client.get("/api/v1/rank-tracker/keywords/RK-NOPE/history")
    ).status_code == 404


# --------------------------------------------------------------------------- #
# 6. N-A: the commitment gate at the edge.
# --------------------------------------------------------------------------- #
async def test_cost_projection_prices_the_clients_active_book(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.cadence_counts = {"weekly": 10, "daily": 2}
    repo.budget = (50.0, 10.0)
    wire("viewer")
    resp = await client.get("/api/v1/rank-tracker/cost-projection", params={"clientId": "cl-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["client"] == "Acme Roofing"
    assert body["tracked"] == 12 and body["daily"] == 2 and body["weekly"] == 10
    assert body["budgetRemaining"] == 40.0
    assert body["withinBudget"] is True


async def test_cost_projection_of_an_unknown_client_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get(
        "/api/v1/rank-tracker/cost-projection", params={"clientId": "cl-nope"}
    )
    assert resp.status_code == 404


async def test_cost_projection_requires_a_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    # A projection with no client is meaningless - there is nobody to bill.
    wire("viewer")
    assert (await client.get("/api/v1/rank-tracker/cost-projection")).status_code == 422


async def test_an_add_within_budget_returns_the_rows_and_the_commitment(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    """The caller must see the standing bill it just signed the client up to IN THE SAME
    RESPONSE - not a month later on the invoice."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.budget = (50.0, 0.0)
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": ["roof repair", "roofer"], "cadence": "weekly"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["keywords"]) == 2
    assert set(body["keywords"][0]) == _KEYWORD_KEYS
    assert body["projection"]["tracked"] == 2  # the book AS IT WOULD BE after the add
    assert body["projection"]["withinBudget"] is True


async def test_an_add_that_would_breach_the_budget_is_refused_and_writes_nothing(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    """THE N-A REQUIREMENT at the edge. 400 daily keywords is a large standing bill; if
    it exceeds what is left of the cap the add must be REJECTED at configuration time,
    while a human is present to lower the cadence or raise the cap - not discovered at
    2am on the 40th nightly check."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.budget = (50.0, 49.0)  # $1 left
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": [f"kw {i}" for i in range(400)],
              "cadence": "daily"},
    )
    assert resp.status_code == 402  # Payment Required: refused on BUDGET grounds
    assert "Rejected" in _message(resp)
    assert repo.added == []  # and nothing was subscribed


async def test_the_add_prices_the_book_as_it_would_be_not_just_the_new_rows(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    """Pricing only the NEW keywords would let a client be walked past their cap in
    small batches, each of which looks affordable on its own."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.cadence_counts = {"daily": 300}  # already committed
    repo.budget = (50.0, 45.0)  # $5 left
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": ["one more"], "cadence": "daily"},
    )
    # ONE keyword looks trivial in isolation; against the EXISTING book it breaches.
    assert resp.status_code == 402, resp.text
    assert repo.added == []


async def test_an_uncapped_client_may_add_freely(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    # No budget row = no cap configured. Inventing a limit would block legitimate work.
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.budget = None
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": [f"kw {i}" for i in range(400)],
              "cadence": "daily"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["projection"]["withinBudget"] is True


async def test_a_keyless_deploy_projects_zero_and_names_the_caveat(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    """The CURRENT deployed reality (no SERPER key): the module degrades to the
    simulated provider, so the honest commitment is $0 - but the message must say so,
    or an operator would quote a fake number to a client as their real bill."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.cadence_counts = {"daily": 500}
    repo.budget = (50.0, 49.0)
    wire("viewer")
    body = (
        await client.get("/api/v1/rank-tracker/cost-projection", params={"clientId": "cl-1"})
    ).json()
    assert body["monthlyCost"] == 0.0
    assert body["live"] is False and body["provider"] == "fake"
    assert "simulated" in body["message"]


async def test_the_projection_never_builds_an_http_client(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The price-only door exists because the old path opened (and leaked) an httpx
    client on EVERY add and every projection read, purely to look up a number."""
    from app.modules.rank_tracker import provider as provider_mod

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("the API edge must not construct a live provider")

    monkeypatch.setattr(provider_mod, "SerperRankProvider", _boom)
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("viewer")
    resp = await client.get("/api/v1/rank-tracker/cost-projection", params={"clientId": "cl-1"})
    assert resp.status_code == 200, resp.text
    # Priced from settings alone: $0.001/page x 10 pages for the depth-100 window.
    assert resp.json()["costPerCheck"] == 0.01


# --------------------------------------------------------------------------- #
# 6b. The on-demand check is rate-limited.
# --------------------------------------------------------------------------- #
async def test_the_on_demand_check_is_rate_limited_per_user(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[tuple[str, bool]]
) -> None:
    """The one route that fires a PAID, client-billed provider call straight from a
    button. The daily dedupe stops a repeat from re-billing; this stops the hammering
    itself (and `force` would bypass the dedupe entirely)."""
    repo.by_code["RK-00001"] = _keyword_row(latest_checked_at=None)
    wire("manager")
    for _ in range(30):
        resp = await client.post(
            "/api/v1/rank-tracker/keywords/RK-00001/check", params={"force": "true"}
        )
        assert resp.status_code == 202, resp.text
    blocked = await client.post(
        "/api/v1/rank-tracker/keywords/RK-00001/check", params={"force": "true"}
    )
    assert blocked.status_code == 429
    assert len(enqueued) == 30  # the 31st never reached the worker


# --------------------------------------------------------------------------- #
# 7. Mutations.
# --------------------------------------------------------------------------- #
async def test_add_snapshots_the_client_name_and_normalizes_the_keywords(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": ["  Roof Repair  "], "device": "mobile",
              "location": "Karachi", "cadence": "daily", "tags": ["money"]},
    )
    assert resp.status_code == 201, resp.text
    added = repo.added[0]
    assert added["client_name"] == "Acme Roofing"  # resolved server-side
    assert added["keywords"] == [("Roof Repair", "roof repair")]  # display + fold key
    assert added["device"] == "mobile" and added["cadence"] == "daily"
    assert added["tags"] == ["money"]


async def test_add_folds_in_batch_duplicates_before_they_reach_the_db(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    """Same subscription = same nightly bill. A stray double space must not buy a
    duplicate."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": ["Roof Repair", "roof   repair", "ROOF REPAIR"]},
    )
    assert resp.status_code == 201, resp.text
    assert repo.added[0]["keywords"] == [("Roof Repair", "roof repair")]  # one, not three


async def test_a_new_subscription_is_due_immediately(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    # A new keyword should not wait a week for its first reading.
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager")
    await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": ["roofer"], "cadence": "weekly"},
    )
    assert repo.added[0]["next_check_on"] == datetime.now(UTC).date()


async def test_add_unknown_client_is_404_and_writes_nothing(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("manager")  # no client_names registered -> invisible/unknown
    resp = await client.post(
        "/api/v1/rank-tracker/keywords", json={"clientId": "cl-nope", "keywords": ["x"]}
    )
    assert resp.status_code == 404
    assert repo.added == []


async def test_add_requires_a_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    # Unlike the 0035 keyword BANK, a tracked keyword is a standing per-client cost -
    # there is no such thing as an un-owned nightly bill.
    wire("manager")
    resp = await client.post("/api/v1/rank-tracker/keywords", json={"keywords": ["x"]})
    assert resp.status_code == 422


async def test_add_rejects_an_empty_batch(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords", json={"clientId": "cl-1", "keywords": []}
    )
    assert resp.status_code == 422  # min_length=1


async def test_add_rejects_an_all_blank_batch(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords", json={"clientId": "cl-1", "keywords": ["  ", ""]}
    )
    assert resp.status_code == 400
    assert repo.added == []


async def test_add_rejects_an_off_enum_cadence(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords",
        json={"clientId": "cl-1", "keywords": ["x"], "cadence": "hourly"},
    )
    assert resp.status_code == 422


async def test_check_enqueues_and_returns_202(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[tuple[str, bool]]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row(latest_checked_at=None)
    wire("manager")
    resp = await client.post("/api/v1/rank-tracker/keywords/RK-00001/check")
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"code": "RK-00001", "queued": True, "reason": ""}
    assert enqueued == [("kw-1", False)]


async def test_check_is_deduped_to_today_and_queues_nothing(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[tuple[str, bool]]
) -> None:
    """A button-masher must not be able to queue work that is only going to no-op."""
    repo.by_code["RK-00001"] = _keyword_row(latest_checked_at=datetime.now(UTC))
    wire("manager")
    resp = await client.post("/api/v1/rank-tracker/keywords/RK-00001/check")
    assert resp.status_code == 202
    assert resp.json() == {
        "code": "RK-00001", "queued": False, "reason": "already checked today"
    }
    assert enqueued == []  # nothing queued, nothing billed


async def test_force_overrides_the_daily_dedupe(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    enqueued: list[tuple[str, bool]]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row(latest_checked_at=datetime.now(UTC))
    wire("manager")
    resp = await client.post(
        "/api/v1/rank-tracker/keywords/RK-00001/check", params={"force": "true"}
    )
    assert resp.status_code == 202
    assert resp.json()["queued"] is True
    assert enqueued == [("kw-1", True)]  # the force flag reaches the worker


async def test_check_of_an_unknown_code_is_404_and_never_enqueues(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[Any]
) -> None:
    wire("manager")
    assert (
        await client.post("/api/v1/rank-tracker/keywords/RK-NOPE/check")
    ).status_code == 404
    assert enqueued == []  # the paid run is validated BEFORE it is queued


async def test_patch_pauses_a_subscription(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"status": "paused"}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"status": "paused"})]


async def test_resuming_makes_the_keyword_due_immediately(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    """Otherwise the board sits showing a position from before the pause until the old
    next_check_on slot comes round."""
    repo.by_code["RK-00001"] = _keyword_row(status="paused")
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"status": "active"}
    )
    assert resp.status_code == 200, resp.text
    _code, changes = repo.updates[0]
    assert changes == {"status": "active", "next_check_on": datetime.now(UTC).date()}


async def test_re_activating_an_already_active_keyword_does_not_reschedule_it(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    # A no-op status write must not silently pull the next check forward (and with it
    # the client's spend).
    repo.by_code["RK-00001"] = _keyword_row(status="active")
    wire("manager")
    await client.patch("/api/v1/rank-tracker/keywords/RK-00001", json={"status": "active"})
    assert repo.updates == [("RK-00001", {"status": "active"})]


async def test_patch_changes_the_cadence(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"cadence": "daily"}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"cadence": "daily"})]


# --------------------------------------------------------------------------- #
# 7b. N-A at SET-CADENCE time - the add gate's other door.
# --------------------------------------------------------------------------- #
async def test_a_cadence_upgrade_that_would_breach_the_budget_is_refused(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    pricey_provider: None
) -> None:
    """Gating only the ADD is not a gate. weekly -> daily is SEVEN times the standing
    cost, so without this a lead could add cheap weekly keywords (passing the add gate)
    and then flip them to daily one PATCH at a time - walking the client into exactly
    the runaway bill the add gate exists to prevent.

    At $1/check: the book is 1 weekly (~$4.35/mo) against $20 left; the flip makes it
    1 daily (~$30.44/mo), which does not fit.
    """
    repo.by_code["RK-00001"] = _keyword_row(cadence="weekly", status="active")
    repo.cadence_counts = {"weekly": 1}
    repo.budget = (50.0, 30.0)  # $20 left
    wire("manager")

    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"cadence": "daily"}
    )
    assert resp.status_code == 402, resp.text
    assert "Rejected" in _message(resp)
    assert repo.updates == []  # and the cadence was NOT changed


async def test_resuming_a_paused_keyword_over_budget_is_refused(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    pricey_provider: None
) -> None:
    """A resume takes a subscription from $0 back to a full cadence - a real increase
    the add gate never saw. Here: an empty active book (~$0) against $20 left; the
    resume commits one daily keyword (~$30.44/mo), which does not fit."""
    repo.by_code["RK-00001"] = _keyword_row(cadence="daily", status="paused")
    repo.cadence_counts = {}
    repo.budget = (50.0, 30.0)  # $20 left
    wire("manager")

    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"status": "active"}
    )
    assert resp.status_code == 402, resp.text
    assert repo.updates == []


async def test_pausing_is_always_allowed_even_for_a_client_over_their_cap(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    """Only INCREASES are gated. A client already over their cap (ops lowered it, say)
    must still be able to REDUCE their tracking - refusing that would trap them over
    the cap with no way down, which is the opposite of a cost control."""
    repo.by_code["RK-00001"] = _keyword_row(cadence="daily", status="active")
    repo.cadence_counts = {"daily": 400}  # far past the cap already
    repo.budget = (5.0, 5.0)  # nothing left at all
    wire("manager")

    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"status": "paused"}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"status": "paused"})]


async def test_slowing_the_cadence_is_always_allowed_even_over_budget(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    # daily -> weekly REDUCES the bill; refusing it would be perverse.
    repo.by_code["RK-00001"] = _keyword_row(cadence="daily", status="active")
    repo.cadence_counts = {"daily": 400}
    repo.budget = (5.0, 5.0)
    wire("manager")

    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"cadence": "weekly"}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"cadence": "weekly"})]


async def test_a_cost_neutral_edit_skips_the_pricing_round_trip(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    live_provider: None
) -> None:
    """Tag/URL edits cost nothing, so they must not be blocked by a breached budget -
    nor pay for a pricing lookup they cannot possibly need."""
    repo.by_code["RK-00001"] = _keyword_row()
    repo.cadence_counts = {"daily": 400}
    repo.budget = (5.0, 5.0)  # over cap: an increase WOULD be refused here
    wire("manager")

    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"tags": ["money"]}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"tags": ["money"]})]


async def test_a_cadence_upgrade_within_budget_is_allowed(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None],
    pricey_provider: None
) -> None:
    # The gate must not be a blanket ban on upgrades - an affordable one goes through.
    # 1 daily (~$30.44/mo) against the full $50 cap.
    repo.by_code["RK-00001"] = _keyword_row(cadence="weekly", status="active")
    repo.cadence_counts = {"weekly": 1}
    repo.budget = (50.0, 0.0)
    wire("manager")

    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"cadence": "daily"}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"cadence": "daily"})]


async def test_patch_replaces_the_tag_set(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"tags": ["sprint-1", "money"]}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("RK-00001", {"tags": ["sprint-1", "money"]})]


async def test_patch_null_tags_and_target_url_normalise_to_empty(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"tags": None, "targetUrl": None}
    )
    assert resp.status_code == 200, resp.text
    # The columns are NOT NULL with '' / '{}' defaults, so a null clears rather than
    # writing NULL.
    assert repo.updates == [("RK-00001", {"tags": [], "target_url": ""})]


async def test_patch_unknown_code_is_404(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-NOPE", json={"status": "paused"}
    )
    assert resp.status_code == 404
    assert repo.updates == []


async def test_patch_with_no_fields_is_400(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    wire("manager")
    assert (
        await client.patch("/api/v1/rank-tracker/keywords/RK-00001", json={})
    ).status_code == 400
    assert repo.updates == []


async def test_patch_rejects_an_off_enum_status(
    client: httpx.AsyncClient, repo: FakeRankRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["RK-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/rank-tracker/keywords/RK-00001", json={"status": "deleted"}
    )
    assert resp.status_code == 422
