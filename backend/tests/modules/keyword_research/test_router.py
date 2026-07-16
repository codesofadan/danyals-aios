"""Keyword-research endpoints: the access gates + the wire contract.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``, the research enqueuer is a recorder, and the feature-grant
lookup (the one DB read inside ``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY here - a test
that only ever checks the happy path would not notice one of them vanishing:

1. auth            - swept for the whole app by ``tests/test_route_auth_guard.py``;
                     re-pinned for this module's 7 routes below.
2. keyword_research FEATURE grant - every route.
3. view_reports (reads) / run_research (paid research + mutations).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.keyword_research.repo import get_keyword_repo
from app.modules.keyword_research.router import get_research_enqueuer

pytestmark = pytest.mark.unit

_KEYWORD_KEYS = {
    "code", "keyword", "client", "volume", "difficulty", "cpc", "intent",
    "cluster", "opportunity", "winnable", "targetUrl", "geo",
}

# (method, path) for every route the module publishes.
_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/keyword-research/keywords"),
    ("GET", "/api/v1/keyword-research/stats"),
    ("GET", "/api/v1/keyword-research/workspace"),
    ("GET", "/api/v1/keyword-research/clusters"),
    ("GET", "/api/v1/keyword-research/cannibalization"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/keyword-research/keywords", {"keywords": ["plumber"]}),
    ("POST", "/api/v1/keyword-research/research", {"seed": "plumber"}),
    ("PATCH", "/api/v1/keyword-research/keywords/KW-00001", {"targetUrl": "/x"}),
]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

# The staff roles that hold run_research (mirrors the 0035 RLS write policies).
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope.

    Every raised ``HTTPException`` is rendered by ``install_error_handlers`` as
    ``{"error": {"type", "message", "request_id"}}`` (invariant #5) - there is no
    top-level ``detail`` key on this app, so read the message from the envelope.
    """
    return str(resp.json()["error"]["message"])


def _keyword_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "KW-00001", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "keyword": "invisalign cost", "volume": 8100, "difficulty": 42.0, "cpc": 6.4,
        "intent": "Commercial", "cluster_name": "invisalign", "opportunity": 79.84,
        "winnable": True, "target_url": "https://np.example/x", "geo": "us",
    }
    row.update(over)
    return row


class FakeKeywordRepo:
    """In-memory stand-in for the RLS-scoped KeywordRepo."""

    def __init__(self) -> None:
        self.keywords: list[dict[str, Any]] = []
        self.clusters: list[dict[str, Any]] = []
        self.cannibalization: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {"saved": 0, "clusters": 0, "avg_difficulty": 0}
        self.client_names: dict[str, str] = {}
        self.by_code: dict[str, dict[str, Any]] = {}
        self.list_kwargs: dict[str, Any] | None = None
        self.clusters_kwargs: dict[str, Any] | None = None
        self.cannibalization_kwargs: dict[str, Any] | None = None
        self.added: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def list_keywords(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.keywords)

    def keyword_stats(self) -> dict[str, Any]:
        return dict(self.stats)

    def list_clusters(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.clusters_kwargs = kwargs
        return list(self.clusters)

    def cannibalization_rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.cannibalization_kwargs = kwargs
        return list(self.cannibalization)

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.by_code.get(code)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def add_keywords(
        self, *, client_id: str | None, client_name: str, geo: str | None,
        keywords: list[str], created_by: str,
    ) -> list[dict[str, Any]]:
        self.added.append({
            "client_id": client_id, "client_name": client_name, "geo": geo,
            "keywords": keywords, "created_by": created_by,
        })
        return [
            _keyword_row(code=f"KW-{i:05d}", keyword=kw, client_id=client_id,
                         client_name=client_name, geo=geo)
            for i, kw in enumerate(keywords, start=1)
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


@pytest.fixture
def repo() -> FakeKeywordRepo:
    return FakeKeywordRepo()


@pytest.fixture
def enqueued(app: FastAPI) -> list[tuple[str, str | None, str | None]]:
    """Recorder for the research enqueuer dep (never touches Celery's broker)."""
    calls: list[tuple[str, str | None, str | None]] = []

    def _enqueue(seed: str, geo: str | None, client_id: str | None) -> None:
        calls.append((seed, geo, client_id))

    app.dependency_overrides[get_research_enqueuer] = lambda: _enqueue
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeKeywordRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an
    in-memory dict so the REAL ``feature_allows`` logic still runs, unstubbed.
    """
    app.dependency_overrides[get_keyword_repo] = lambda: repo
    grants: dict[str, str] = {}
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: dict(grants)
    )

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["keyword_research"] = "full"
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
# 2. Gate 2 - the keyword_research FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_keyword_research_feature(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    # A manager holds BOTH view_reports and run_research, so an ungranted feature is
    # the only thing that can reject here.
    wire("manager", feature=False)
    resp = await client.request(method, path, json={"keywords": ["x"], "seed": "x"})
    assert resp.status_code == 403, resp.text
    assert "keyword_research" in _message(resp)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None],
    enqueued: list[Any], method: str, path: str
) -> None:
    # Owner short-circuits require_feature (no grant lookup at all).
    repo.by_code["KW-00001"] = _keyword_row()
    wire("owner", feature=False)
    resp = await client.request(method, path, json={"keywords": ["x"], "seed": "x",
                                                    "targetUrl": "/x"})
    assert resp.status_code != 403, resp.text


async def test_a_view_only_grant_does_not_satisfy_a_full_feature_requirement(
    app: FastAPI, client: httpx.AsyncClient, repo: FakeKeywordRepo,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_keyword_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: {"keyword_research": "view"}
    )
    resp = await client.get("/api/v1/keyword-research/keywords")
    assert resp.status_code == 403  # require_feature defaults to level="full"


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports on reads, run_research on writes.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_require_view_reports(
    client: httpx.AsyncClient, wire: Callable[..., None], method: str, path: str
) -> None:
    # A portal client holds NO staff permission. It is granted the feature here on
    # purpose: this pins view_reports as an INDEPENDENT gate, so the read surface
    # stays closed to clients even if a grant row were somehow created for one.
    wire("client")
    resp = await client.request(method, path)
    assert resp.status_code == 403, resp.text
    assert "view_reports" in _message(resp)


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_mutations_require_run_research(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None],
    enqueued: list[Any], role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    """The paid research + every bank mutation are LEADS-only.

    This mirrors the 0035 RLS insert/update policies
    (``current_app_role() in ('owner','admin','manager')``) exactly: a role that
    passed this gate but failed RLS would get an opaque database error instead of
    a clean 403.
    """
    repo.by_code["KW-00001"] = _keyword_row()
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, f"{role} must not {method} {path}: {resp.text}"
    assert "run_research" in _message(resp)
    assert enqueued == []  # no paid work was queued
    assert repo.added == [] and repo.updates == []  # nothing was written


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_non_lead_staff_may_still_read_the_bank(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None], role: str
) -> None:
    # run_research gates the WRITES only - a specialist/analyst/viewer keeps the
    # read surface (RLS likewise lets any staff select).
    repo.keywords = [_keyword_row()]
    wire(role)
    assert (await client.get("/api/v1/keyword-research/keywords")).status_code == 200


@pytest.mark.parametrize("role", _LEADS)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_leads_may_mutate(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None],
    enqueued: list[Any], role: str, method: str, path: str, body: dict[str, Any]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201, 202), f"{role} must {method} {path}: {resp.text}"


# --------------------------------------------------------------------------- #
# 4. The internal client_id must NEVER surface.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_client_id_never_appears_in_any_response_body(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None],
    enqueued: list[Any], method: str, path: str
) -> None:
    """Every fixture row carries the secret tenant id; no route may echo it back."""
    repo.keywords = [_keyword_row()]
    repo.by_code["KW-00001"] = _keyword_row()
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    repo.stats = {"saved": 1, "clusters": 1, "avg_difficulty": 42.0}
    repo.clusters = [{
        "client_id": "cl-secret", "client_name": "NorthPeak Dental", "name": "invisalign",
        "pillar_keyword": "invisalign", "dominant_intent": "Commercial", "size": 3,
        "total_volume": 900, "avg_difficulty": 42.0,
    }]
    repo.cannibalization = [
        {"keyword": "a", "intent": "Commercial", "target_url": "/x", "client_id": "cl-secret"},
        {"keyword": "b", "intent": "Local", "target_url": "/x", "client_id": "cl-secret"},
    ]
    wire("owner")
    resp = await client.request(
        method, path,
        json={"keywords": ["plumber"], "seed": "plumber", "clientId": "cl-secret"},
    )
    assert resp.status_code in (200, 201, 202), resp.text
    raw = resp.text
    assert "client_id" not in raw and "clientId" not in raw
    assert "cl-secret" not in raw  # not the key NOR the value


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/keyword-research/keywords", None),
        ("GET", "/api/v1/keyword-research/clusters", None),
        ("POST", "/api/v1/keyword-research/keywords",
         {"clientId": "cl-secret", "keywords": ["plumber"]}),
        ("PATCH", "/api/v1/keyword-research/keywords/KW-00001", {"clientId": "cl-secret"}),
    ],
)
async def test_the_client_snapshot_name_is_what_replaces_the_hidden_id(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None],
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    """The other half of the contract: hiding ``client_id`` must not mean showing
    NOTHING - every route whose model carries ``client`` emits the display snapshot.

    Only these four routes have a client field; ``/stats``, ``/workspace``,
    ``/cannibalization`` and ``/research`` legitimately carry no client at all, so
    they are covered by the negative sweep above and excluded here on purpose.
    """
    repo.keywords = [_keyword_row()]
    repo.by_code["KW-00001"] = _keyword_row()
    repo.client_names = {"cl-secret": "NorthPeak Dental"}
    repo.clusters = [{
        "client_id": "cl-secret", "client_name": "NorthPeak Dental", "name": "invisalign",
        "pillar_keyword": "invisalign", "dominant_intent": "Commercial", "size": 3,
        "total_volume": 900, "avg_difficulty": 42.0,
    }]
    wire("owner")
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201), resp.text
    payload = resp.json()
    row = payload[0] if isinstance(payload, list) else payload
    assert row["client"] == "NorthPeak Dental"
    assert "cl-secret" not in resp.text


async def test_list_keywords_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.keywords = [_keyword_row()]
    wire("viewer")
    resp = await client.get("/api/v1/keyword-research/keywords")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == _KEYWORD_KEYS
    assert row["client"] == "NorthPeak Dental"  # the snapshot, not the id
    assert row["targetUrl"] == "https://np.example/x"


# --------------------------------------------------------------------------- #
# 5. Reads: filters, pagination, shapes.
# --------------------------------------------------------------------------- #
async def test_list_honors_the_page_dep(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get(
        "/api/v1/keyword-research/keywords", params={"limit": 5, "offset": 10}
    )
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 5 and repo.list_kwargs["offset"] == 10


async def test_list_defaults_to_the_capped_page(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/keyword-research/keywords")
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 50 and repo.list_kwargs["offset"] == 0


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_list_rejects_an_out_of_range_page(
    client: httpx.AsyncClient, wire: Callable[..., None], params: dict[str, int]
) -> None:
    # The hard caps are enforced at the edge - no handler can ask for an unbounded page.
    wire("viewer")
    resp = await client.get("/api/v1/keyword-research/keywords", params=params)
    assert resp.status_code == 422


async def test_clusters_list_honors_the_page_dep(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/keyword-research/clusters", params={"limit": 7, "offset": 3})
    assert repo.clusters_kwargs is not None
    assert repo.clusters_kwargs["limit"] == 7 and repo.clusters_kwargs["offset"] == 3


async def test_list_passes_every_filter_through_to_the_repo(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/keyword-research/keywords", params={
        "clientId": "cl-1", "clusterId": "cu-1", "intent": "Commercial",
        "winnable": "true", "geo": "us", "source": "research",
    })
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["client_id"] == "cl-1"
    assert repo.list_kwargs["cluster_id"] == "cu-1"
    assert repo.list_kwargs["intent"] == "Commercial"
    assert repo.list_kwargs["winnable"] is True
    assert repo.list_kwargs["geo"] == "us"
    assert repo.list_kwargs["source"] == "research"


async def test_list_filters_default_to_none_not_a_silent_narrowing(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/keyword-research/keywords")
    assert repo.list_kwargs is not None
    for key in ("client_id", "cluster_id", "intent", "winnable", "geo", "source"):
        assert repo.list_kwargs[key] is None


async def test_list_rejects_an_off_enum_intent_filter(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/keyword-research/keywords", params={"intent": "Bogus"})
    assert resp.status_code == 422  # not a SearchIntent


async def test_stats_shape(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.stats = {"saved": 640, "clusters": 28, "avg_difficulty": 34.25}
    wire("analyst")
    resp = await client.get("/api/v1/keyword-research/stats")
    assert resp.status_code == 200
    assert resp.json() == {"saved": 640, "clusters": 28, "avgDifficulty": 34.2}


async def test_workspace_returns_the_tool_extra_shape(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.stats = {"saved": 640, "clusters": 28, "avg_difficulty": 34.2}
    repo.keywords = [_keyword_row()]
    wire("viewer")
    resp = await client.get("/api/v1/keyword-research/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"kpis", "table", "primary", "bullets"}
    assert body["table"]["cols"] == ["Keyword", "Volume", "Difficulty", "Intent"]
    assert [k["label"] for k in body["kpis"]] == ["Saved keywords", "Clusters", "Avg. difficulty"]
    assert body["primary"] == {"label": "Research keywords", "icon": "search"}


async def test_workspace_asks_the_repo_for_only_the_top_eight(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/keyword-research/workspace")
    assert repo.list_kwargs == {"limit": 8, "offset": 0}


async def test_cannibalization_folds_rows_into_conflicts(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.cannibalization = [
        {"keyword": "plumber cost", "intent": "Transactional", "target_url": "/plumbing"},
        {"keyword": "what is plumbing", "intent": "Informational", "target_url": "/plumbing"},
        {"keyword": "best plumber", "intent": "Commercial", "target_url": "/best"},
    ]
    wire("viewer")
    resp = await client.get(
        "/api/v1/keyword-research/cannibalization", params={"clientId": "cl-1"}
    )
    assert resp.status_code == 200
    assert repo.cannibalization_kwargs == {"client_id": "cl-1"}
    assert resp.json() == [{
        "targetUrl": "/plumbing",
        "intents": ["Informational", "Transactional"],
        "keywords": ["plumber cost", "what is plumbing"],
    }]


# --------------------------------------------------------------------------- #
# 6. Mutations.
# --------------------------------------------------------------------------- #
async def test_add_keywords_snapshots_the_client_name(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager")
    resp = await client.post(
        "/api/v1/keyword-research/keywords",
        json={"clientId": "cl-1", "geo": "us", "keywords": ["roof repair", "roofer"]},
    )
    assert resp.status_code == 201, resp.text
    assert repo.added[0]["client_name"] == "Acme Roofing"  # resolved server-side
    assert repo.added[0]["client_id"] == "cl-1"
    assert repo.added[0]["created_by"] == "00000000-0000-0000-0000-0000000000a1"
    body = resp.json()
    assert len(body) == 2
    assert set(body[0]) == _KEYWORD_KEYS


async def test_add_keywords_without_a_client_fills_the_bank(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    # A client-less add is legal: an unassigned bank keyword has no client yet.
    wire("manager")
    resp = await client.post(
        "/api/v1/keyword-research/keywords", json={"keywords": ["plumber"]}
    )
    assert resp.status_code == 201, resp.text
    assert repo.added[0]["client_id"] is None
    assert repo.added[0]["client_name"] == ""
    assert resp.json()[0]["client"] == ""


async def test_add_keywords_unknown_client_is_404_and_writes_nothing(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("manager")  # no client_names registered -> invisible/unknown
    resp = await client.post(
        "/api/v1/keyword-research/keywords",
        json={"clientId": "cl-nope", "keywords": ["plumber"]},
    )
    assert resp.status_code == 404
    assert repo.added == []


async def test_add_keywords_rejects_an_empty_batch(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/keyword-research/keywords", json={"keywords": []})
    assert resp.status_code == 422  # min_length=1


async def test_research_enqueues_and_returns_202(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None],
    enqueued: list[tuple[str, str | None, str | None]]
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager")
    resp = await client.post(
        "/api/v1/keyword-research/research",
        json={"seed": "roof repair", "geo": "us", "clientId": "cl-1"},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"seed": "roof repair", "queued": True}
    assert enqueued == [("roof repair", "us", "cl-1")]  # the worker got the job


async def test_research_unknown_client_is_404_and_never_enqueues(
    client: httpx.AsyncClient, wire: Callable[..., None],
    enqueued: list[tuple[str, str | None, str | None]]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/keyword-research/research", json={"seed": "x", "clientId": "cl-nope"}
    )
    assert resp.status_code == 404
    assert enqueued == []  # the paid run is validated BEFORE it is queued


async def test_research_rejects_an_empty_seed(
    client: httpx.AsyncClient, wire: Callable[..., None], enqueued: list[Any]
) -> None:
    wire("manager")
    assert (await client.post(
        "/api/v1/keyword-research/research", json={"seed": ""}
    )).status_code == 422
    assert enqueued == []


async def test_patch_sets_target_url(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"targetUrl": "/new-page"}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("KW-00001", {"target_url": "/new-page"})]


async def test_patch_intent_override_stamps_manual_source_and_full_confidence(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"intent": "Local"}
    )
    assert resp.status_code == 200, resp.text
    _code, changes = repo.updates[0]
    # A human override is authoritative: it must out-rank a later provider pull.
    assert changes == {"intent": "Local", "intent_source": "manual", "intent_confidence": 1.0}


async def test_patch_reassign_resnapshots_the_client_name(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    repo.client_names = {"cl-2": "Lumen Realty"}
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"clientId": "cl-2"}
    )
    assert resp.status_code == 200, resp.text
    _code, changes = repo.updates[0]
    assert changes == {"client_id": "cl-2", "client_name": "Lumen Realty"}
    assert resp.json()["client"] == "Lumen Realty"


async def test_patch_null_client_returns_the_keyword_to_the_bank(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"clientId": None}
    )
    assert resp.status_code == 200, resp.text
    _code, changes = repo.updates[0]
    # An explicit null UNASSIGNS (and clears the snapshot) - it is not "no change".
    assert changes == {"client_id": None, "client_name": ""}


async def test_patch_unknown_client_is_404(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"clientId": "cl-nope"}
    )
    assert resp.status_code == 404
    assert repo.updates == []


async def test_patch_unknown_code_is_404(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-NOPE", json={"targetUrl": "/x"}
    )
    assert resp.status_code == 404
    assert repo.updates == []


async def test_patch_with_no_fields_is_400(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch("/api/v1/keyword-research/keywords/KW-00001", json={})
    assert resp.status_code == 400
    assert repo.updates == []


async def test_patch_rejects_an_off_enum_intent(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"intent": "Bogus"}
    )
    assert resp.status_code == 422


async def test_patch_replaces_the_tag_set(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"tags": ["sprint-1", "money"]}
    )
    assert resp.status_code == 200, resp.text
    assert repo.updates == [("KW-00001", {"tags": ["sprint-1", "money"]})]


async def test_patch_null_target_url_and_tags_normalise_to_empty(
    client: httpx.AsyncClient, repo: FakeKeywordRepo, wire: Callable[..., None]
) -> None:
    repo.by_code["KW-00001"] = _keyword_row()
    wire("manager")
    resp = await client.patch(
        "/api/v1/keyword-research/keywords/KW-00001", json={"targetUrl": None, "tags": None}
    )
    assert resp.status_code == 200, resp.text
    # The columns are NOT NULL with '' / '{}' defaults, so a null clears rather than
    # writing NULL.
    assert repo.updates == [("KW-00001", {"target_url": "", "tags": []})]
