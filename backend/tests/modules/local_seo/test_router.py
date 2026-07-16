"""Local-SEO endpoints: the access gates + the wire contract.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``, the enqueuers are recorders, and the feature-grant lookup
(the one DB read inside ``require_feature``) is monkeypatched.

Three gates stack on every route, and each is pinned INDEPENDENTLY here - a test that
only ever checks the happy path would not notice one of them vanishing:

1. auth        - swept for the whole app by ``tests/test_route_auth_guard.py``;
                 re-pinned for this module's 13 routes below.
2. local_seo FEATURE grant - every route.
3. view_reports (reads) / a LEAD role (every mutation), mirroring the 0039 RLS
   insert/update policies byte-for-byte.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.core.auth import CurrentUser, get_current_user
from app.core.deps import get_redis
from app.modules.local_seo.repo import get_local_repo
from app.modules.local_seo.router import get_gbp_sync_enqueuer, get_rank_refresh_enqueuer

pytestmark = pytest.mark.unit


class _NoThrottleRedis:
    """A redis stand-in whose counter never exceeds 1, so the ``/refresh`` limiter is
    a no-op in these unit tests (the limiter itself is covered in test_ratelimit).

    Without this the dep would reach for a LIVE Redis: the limiter fails open, but
    only after the connect attempt - so the suite would hang on the connect timeout
    of a machine with no Redis. Mirrors ``tests/test_public_endpoints``.
    """

    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        return None

_RANKING_KEYS = {
    "id", "location", "client", "keyword", "geo", "rank", "previousRank", "change",
    "inMapPack", "foundUrl", "topCompetitors", "provider", "isActive", "lastCheckedAt",
}
_PROFILE_KEYS = {
    "id", "client", "location", "placeId", "primaryCategory", "secondaryCategories",
    "napName", "napAddress", "napPhone", "website", "hours", "reviewCount", "avgRating",
    "completeness", "oauthConnected", "lastSyncedAt",
}

# (method, path) for every route the module publishes.
_READ_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/local-seo/rankings"),
    ("GET", "/api/v1/local-seo/stats"),
    ("GET", "/api/v1/local-seo/workspace"),
    ("GET", "/api/v1/local-seo/rankings/rk-1/history"),
    ("GET", "/api/v1/local-seo/profiles"),
    ("GET", "/api/v1/local-seo/profiles/gp-1"),
    ("GET", "/api/v1/local-seo/profiles/gp-1/audit"),
    ("GET", "/api/v1/local-seo/profiles/gp-1/nap-alignment"),
]
_WRITE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/local-seo/rankings", {"profileId": "gp-1", "keyword": "cafe"}),
    ("PATCH", "/api/v1/local-seo/rankings/rk-1", {"isActive": False}),
    ("POST", "/api/v1/local-seo/rankings/rk-1/refresh", {}),
    ("POST", "/api/v1/local-seo/profiles",
     {"clientId": "cl-secret", "locationLabel": "Karachi"}),
    ("PATCH", "/api/v1/local-seo/profiles/gp-1", {"primaryCategory": "Cafe"}),
    ("POST", "/api/v1/local-seo/profiles/gp-1/sync", {}),
]
_ALL_ROUTES = [(m, p) for m, p in _READ_ROUTES] + [(m, p) for m, p, _b in _WRITE_ROUTES]

# The staff roles that may WRITE (mirrors the 0039 RLS insert/update policies).
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]

# A body that satisfies every write route at once (each model ignores the rest).
_ANY_BODY: dict[str, Any] = {
    "profileId": "gp-1", "keyword": "cafe", "isActive": False,
    "clientId": "cl-secret", "locationLabel": "Karachi", "primaryCategory": "Cafe",
}


def _message(resp: httpx.Response) -> str:
    """The rejection reason out of the app's global error envelope.

    Every raised ``HTTPException`` is rendered by ``install_error_handlers`` as
    ``{"error": {"type", "message", "request_id"}}`` (invariant #5) - there is no
    top-level ``detail`` key on this app, so read the message from the envelope.
    """
    return str(resp.json()["error"]["message"])


def _ranking_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "rk-1", "client_id": "cl-secret", "client_name": "Verde Cafe",
        "location_label": "Karachi", "keyword": "cafe near me", "geo": "Karachi, PK",
        "rank": 2, "previous_rank": 4, "rank_change": 2, "in_map_pack": True,
        "found_url": "https://verde.example", "top_competitors": ["Bean There"],
        "provider": "serper_places", "is_active": True, "last_checked_at": None,
    }
    row.update(over)
    return row


def _profile_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "gp-1", "client_id": "cl-secret", "client_name": "Verde Cafe",
        "location_label": "Karachi", "google_location_id": "locations/1",
        "place_id": "ChIJ-place", "primary_category": "Cafe",
        "secondary_categories": ["Coffee shop", "Bakery"], "nap_name": "Verde Cafe",
        "nap_address": "123 Main Street", "nap_phone": "+1 555 010 9999",
        "website_uri": "https://verde.example", "regular_hours": {"mon": "9-5"},
        "review_count": 214, "avg_rating": 4.6, "completeness_score": 86,
        "audit": {}, "oauth_connected": True,
        "oauth_vault_ref": "vault-key-DO-NOT-LEAK", "last_synced_at": None,
    }
    row.update(over)
    return row


class FakeLocalRepo:
    """In-memory stand-in for the RLS-scoped LocalRepo."""

    def __init__(self) -> None:
        self.rankings: list[dict[str, Any]] = []
        self.profiles: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.profiles_by_id: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.citations: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {"gbp_profiles": 0, "avg_map_rank": 0, "citations": 0}
        self.client_names: dict[str, str] = {}
        self.list_kwargs: dict[str, Any] | None = None
        self.profiles_kwargs: dict[str, Any] | None = None
        self.history_kwargs: dict[str, Any] | None = None
        self.citations_for: list[str] = []
        self.added_rankings: list[dict[str, Any]] = []
        self.added_profiles: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.active_calls: list[tuple[str, bool]] = []

    def list_rankings(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return list(self.rankings)

    def get_ranking(self, ranking_id: str) -> dict[str, Any] | None:
        return self.by_id.get(ranking_id)

    def local_stats(self) -> dict[str, Any]:
        return dict(self.stats)

    def rank_history(self, ranking_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.history_kwargs = {"ranking_id": ranking_id, **kwargs}
        return list(self.history)

    def list_profiles(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.profiles_kwargs = kwargs
        return list(self.profiles)

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        return self.profiles_by_id.get(profile_id)

    def citations_for_client(self, client_id: str) -> list[dict[str, Any]]:
        self.citations_for.append(client_id)
        return list(self.citations)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def add_ranking(self, **kwargs: Any) -> dict[str, Any] | None:
        self.added_rankings.append(kwargs)
        return _ranking_row(keyword=kwargs["keyword"], geo=kwargs["geo"],
                            client_name=kwargs["client_name"])

    def set_ranking_active(self, ranking_id: str, *, is_active: bool) -> dict[str, Any] | None:
        self.active_calls.append((ranking_id, is_active))
        row = self.by_id.get(ranking_id)
        return None if row is None else {**row, "is_active": is_active}

    def add_profile(self, values: dict[str, Any]) -> dict[str, Any] | None:
        self.added_profiles.append(values)
        return _profile_row(**{k: v for k, v in values.items() if k in _profile_row()})

    def update_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        self.updates.append((profile_id, changes))
        row = self.profiles_by_id.get(profile_id)
        return None if row is None else {**row, **changes}


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture
def repo() -> FakeLocalRepo:
    return FakeLocalRepo()


@pytest.fixture
def enqueued(app: FastAPI) -> dict[str, list[Any]]:
    """Recorders for both enqueuer deps (never touch Celery's broker)."""
    calls: dict[str, list[Any]] = {"refresh": [], "sync": []}
    app.dependency_overrides[get_rank_refresh_enqueuer] = lambda: (
        lambda: calls["refresh"].append(True)
    )
    app.dependency_overrides[get_gbp_sync_enqueuer] = lambda: (
        lambda pid: calls["sync"].append(pid)
    )
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeLocalRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Wire the fake repo + an identity + the caller's feature grants.

    ``require_feature`` loads grants from the DB; the loader is patched to an
    in-memory dict so the REAL ``feature_allows`` logic still runs, unstubbed.
    """
    app.dependency_overrides[get_local_repo] = lambda: repo
    # The /refresh route carries a rate-limit dep; pin it to a non-throttling redis so
    # these tests never touch a live one (see _NoThrottleRedis).
    app.dependency_overrides[get_redis] = lambda: _NoThrottleRedis()
    grants: dict[str, str] = {}
    monkeypatch.setattr("app.core.auth._load_feature_grants", lambda _uid: dict(grants))

    def _as(role: str, *, feature: bool = True) -> None:
        grants.clear()
        if feature:
            grants["local_seo"] = "full"
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.fixture
def seeded(repo: FakeLocalRepo) -> FakeLocalRepo:
    """A repo with one of everything, so a route under test can reach its handler."""
    repo.rankings = [_ranking_row()]
    repo.by_id["rk-1"] = _ranking_row()
    repo.profiles = [_profile_row()]
    repo.profiles_by_id["gp-1"] = _profile_row()
    repo.client_names = {"cl-secret": "Verde Cafe"}
    repo.stats = {"gbp_profiles": 9, "avg_map_rank": 3.2, "citations": 210}
    repo.history = [
        {"rank": 2, "in_map_pack": True, "provider": "serper_places", "checked_at": None}
    ]
    repo.citations = [{"directory": "Yelp", "nap_status": "consistent", "note": ""}]
    return repo


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
# 2. Gate 2 - the local_seo FEATURE grant.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_every_route_requires_the_local_seo_feature(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]], method: str, path: str
) -> None:
    # A manager holds BOTH view_reports and the lead role, so an ungranted feature is
    # the only thing that can reject here.
    wire("manager", feature=False)
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code == 403, resp.text
    assert "local_seo" in _message(resp)


@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_owner_is_all_on_without_any_grant_row(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]], method: str, path: str
) -> None:
    # Owner short-circuits require_feature (no grant lookup at all).
    wire("owner", feature=False)
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code != 403, resp.text


async def test_a_view_only_grant_does_not_satisfy_a_full_feature_requirement(
    app: FastAPI, client: httpx.AsyncClient, repo: FakeLocalRepo,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_local_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: _user("manager")
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda _uid: {"local_seo": "view"}
    )
    resp = await client.get("/api/v1/local-seo/rankings")
    assert resp.status_code == 403  # require_feature defaults to level="full"


# --------------------------------------------------------------------------- #
# 3. Gate 3 - view_reports on reads, a LEAD role on every mutation.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_require_view_reports(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    method: str, path: str
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
async def test_mutations_require_a_lead_role(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]], role: str, method: str, path: str,
    body: dict[str, Any]
) -> None:
    """Every local mutation is LEADS-only.

    This mirrors the 0039 RLS insert/update policies
    (``current_app_role() in ('owner','admin','manager')``) exactly: a role that
    passed this gate but failed RLS would get an opaque database error instead of a
    clean 403.
    """
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, f"{role} must not {method} {path}: {resp.text}"
    assert enqueued["refresh"] == [] and enqueued["sync"] == []  # no paid work queued
    assert seeded.added_rankings == [] and seeded.added_profiles == []
    assert seeded.updates == [] and seeded.active_calls == []  # nothing was written


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_non_lead_staff_may_still_read_the_board(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo, role: str
) -> None:
    # The lead gate covers the WRITES only - a specialist/analyst/viewer keeps the
    # read surface (RLS likewise lets any staff select).
    wire(role)
    assert (await client.get("/api/v1/local-seo/rankings")).status_code == 200


@pytest.mark.parametrize("role", _LEADS)
@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_leads_may_mutate(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]], role: str, method: str, path: str,
    body: dict[str, Any]
) -> None:
    wire(role)
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201, 202), f"{role} must {method} {path}: {resp.text}"


# --------------------------------------------------------------------------- #
# 4. The internal client_id + the vault ref must NEVER surface.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _ALL_ROUTES)
async def test_client_id_never_appears_in_any_response_body(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]], method: str, path: str
) -> None:
    """Every fixture row carries the secret tenant id; no route may echo it back."""
    wire("owner")
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code in (200, 201, 202), resp.text
    raw = resp.text
    assert "client_id" not in raw and "clientId" not in raw
    assert "cl-secret" not in raw  # not the key NOR the value


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/local-seo/profiles"),
        ("GET", "/api/v1/local-seo/profiles/gp-1"),
        ("PATCH", "/api/v1/local-seo/profiles/gp-1"),
        ("POST", "/api/v1/local-seo/profiles"),
    ],
)
async def test_the_oauth_vault_ref_never_appears_in_any_profile_response(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    method: str, path: str
) -> None:
    """The vault ref points at an AES-GCM sealed Google refresh token: leaking it
    hands an attacker the coordinates of the secret."""
    wire("owner")
    resp = await client.request(method, path, json=_ANY_BODY)
    assert resp.status_code in (200, 201), resp.text
    assert "vault-key-DO-NOT-LEAK" not in resp.text
    assert "oauth_vault_ref" not in resp.text and "oauthVaultRef" not in resp.text


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/local-seo/rankings", None),
        ("GET", "/api/v1/local-seo/profiles", None),
        ("POST", "/api/v1/local-seo/rankings", {"profileId": "gp-1", "keyword": "cafe"}),
    ],
)
async def test_the_client_snapshot_name_is_what_replaces_the_hidden_id(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    """The other half of the contract: hiding ``client_id`` must not mean showing
    NOTHING - every route whose model carries ``client`` emits the display snapshot."""
    wire("owner")
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201), resp.text
    payload = resp.json()
    row = payload[0] if isinstance(payload, list) else payload
    assert row["client"] == "Verde Cafe"


async def test_list_rankings_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/rankings")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == _RANKING_KEYS
    assert row["location"] == "Karachi"  # the joined profile label
    assert row["client"] == "Verde Cafe"  # the snapshot, not the id


async def test_list_profiles_emits_exactly_the_frozen_key_set(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/profiles")
    assert resp.status_code == 200
    assert set(resp.json()[0]) == _PROFILE_KEYS


# --------------------------------------------------------------------------- #
# 5. Reads: filters, pagination, shapes.
# --------------------------------------------------------------------------- #
async def test_list_honors_the_page_dep(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/rankings", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 5 and repo.list_kwargs["offset"] == 10


async def test_list_defaults_to_the_capped_page(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("viewer")
    await client.get("/api/v1/local-seo/rankings")
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["limit"] == 50 and repo.list_kwargs["offset"] == 0


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_list_rejects_an_out_of_range_page(
    client: httpx.AsyncClient, wire: Callable[..., None], params: dict[str, int]
) -> None:
    # The hard caps are enforced at the edge - no handler can ask for an unbounded page.
    wire("viewer")
    assert (await client.get("/api/v1/local-seo/rankings", params=params)).status_code == 422


async def test_list_passes_every_filter_through_to_the_repo(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/rankings", params={
        "clientId": "cl-1", "profileId": "gp-1", "keyword": "cafe",
        "geo": "Karachi, PK", "inMapPack": "true", "isActive": "false",
    })
    assert resp.status_code == 200
    assert repo.list_kwargs is not None
    assert repo.list_kwargs["client_id"] == "cl-1"
    assert repo.list_kwargs["profile_id"] == "gp-1"
    assert repo.list_kwargs["keyword"] == "cafe"
    assert repo.list_kwargs["geo"] == "Karachi, PK"
    assert repo.list_kwargs["in_map_pack"] is True
    assert repo.list_kwargs["is_active"] is False


async def test_list_filters_default_to_none_not_a_silent_narrowing(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("viewer")
    await client.get("/api/v1/local-seo/rankings")
    assert repo.list_kwargs is not None
    for key in ("client_id", "profile_id", "keyword", "geo", "in_map_pack", "is_active"):
        assert repo.list_kwargs[key] is None


async def test_stats_shape(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("analyst")
    resp = await client.get("/api/v1/local-seo/stats")
    assert resp.status_code == 200
    assert resp.json() == {"gbpProfiles": 9, "avgMapRank": 3.2, "citations": 210}


async def test_workspace_returns_the_tool_extra_shape(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"kpis", "table", "primary", "bullets"}
    assert body["table"]["cols"] == ["Location", "Client", "Keyword", "Rank"]
    assert [k["label"] for k in body["kpis"]] == ["GBP profiles", "Avg. map rank", "Citations"]
    assert body["primary"] == {"label": "Run local audit", "icon": "storefront"}


async def test_workspace_asks_the_repo_for_only_the_top_eight(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("viewer")
    await client.get("/api/v1/local-seo/workspace")
    assert repo.list_kwargs == {"limit": 8, "offset": 0}


async def test_history_is_bounded_by_the_page_dep(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get(
        "/api/v1/local-seo/rankings/rk-1/history", params={"limit": 30}
    )
    assert resp.status_code == 200
    assert seeded.history_kwargs == {"ranking_id": "rk-1", "limit": 30}
    assert set(resp.json()[0]) == {"rank", "inMapPack", "provider", "checkedAt"}


async def test_history_of_an_unknown_ranking_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("viewer")
    assert (
        await client.get("/api/v1/local-seo/rankings/rk-nope/history")
    ).status_code == 404


async def test_the_audit_route_recomputes_the_completeness_score(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    # The stored column says 86; the profile fixture is complete, so the live
    # recompute must say 100 (an operator sees their PATCH immediately).
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/profiles/gp-1/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["completeness"] == 100
    assert body["missing"] == []
    assert body["secondaryCategories"] == ["Coffee shop", "Bakery"]


async def test_the_nap_alignment_route_reads_the_clients_citation_ledger(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/profiles/gp-1/nap-alignment")
    assert resp.status_code == 200
    # The client is resolved from the PROFILE, never from the caller.
    assert seeded.citations_for == ["cl-secret"]
    assert resp.json()["aligned"] is True


async def test_the_nap_alignment_route_normalizes_cosmetic_drift(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    """End-to-end at the route: the profile's canonical address is "123 Main Street";
    a directory flagged inconsistent showing "123 Main St." is the SAME address."""
    seeded.citations = [
        {"directory": "Yelp", "nap_status": "inconsistent", "note": "123 Main St."}
    ]
    wire("viewer")
    resp = await client.get("/api/v1/local-seo/profiles/gp-1/nap-alignment")
    assert resp.status_code == 200
    body = resp.json()
    assert body["inconsistent"] == 0 and body["cosmeticOnly"] == 1
    assert body["directories"][0]["cosmeticOnly"] is True
    assert body["aligned"] is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/local-seo/profiles/gp-nope",
        "/api/v1/local-seo/profiles/gp-nope/audit",
        "/api/v1/local-seo/profiles/gp-nope/nap-alignment",
    ],
)
async def test_an_unknown_profile_is_404_on_every_profile_read(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo, path: str
) -> None:
    wire("viewer")
    assert (await client.get(path)).status_code == 404


# --------------------------------------------------------------------------- #
# 6. Mutations.
# --------------------------------------------------------------------------- #
async def test_add_ranking_takes_its_client_from_the_profile_not_the_caller(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    """A ranking's tenant is decided by the PROFILE it tracks. Accepting a clientId
    from the body would let a caller mis-attribute a ranking to another tenant."""
    wire("manager")
    resp = await client.post(
        "/api/v1/local-seo/rankings",
        json={"profileId": "gp-1", "keyword": "cafe near me", "geo": "Karachi, PK",
              "clientId": "cl-someone-else"},
    )
    assert resp.status_code == 201, resp.text
    added = seeded.added_rankings[0]
    assert added["client_id"] == "cl-secret"  # from the profile
    assert added["client_name"] == "Verde Cafe"  # snapshotted server-side
    assert added["profile_id"] == "gp-1" and added["geo"] == "Karachi, PK"


async def test_add_ranking_unknown_profile_is_404_and_writes_nothing(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/local-seo/rankings", json={"profileId": "gp-nope", "keyword": "cafe"}
    )
    assert resp.status_code == 404
    assert repo.added_rankings == []


async def test_add_ranking_allows_a_geo_less_row(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/local-seo/rankings", json={"profileId": "gp-1", "keyword": "cafe"}
    )
    assert resp.status_code == 201, resp.text
    assert seeded.added_rankings[0]["geo"] is None


@pytest.mark.parametrize(
    "body",
    [{"profileId": "gp-1", "keyword": ""}, {"keyword": "cafe"}, {"profileId": "gp-1"}],
)
async def test_add_ranking_rejects_a_bad_body(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    body: dict[str, Any]
) -> None:
    wire("manager")
    assert (await client.post("/api/v1/local-seo/rankings", json=body)).status_code == 422


async def test_patch_deactivates_a_ranking_without_deleting_its_history(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.patch("/api/v1/local-seo/rankings/rk-1", json={"isActive": False})
    assert resp.status_code == 200, resp.text
    assert seeded.active_calls == [("rk-1", False)]
    assert resp.json()["isActive"] is False


async def test_patch_reactivates_a_ranking(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.patch("/api/v1/local-seo/rankings/rk-1", json={"isActive": True})
    assert resp.status_code == 200, resp.text
    assert seeded.active_calls == [("rk-1", True)]


async def test_patch_unknown_ranking_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("manager")
    assert (
        await client.patch("/api/v1/local-seo/rankings/rk-nope", json={"isActive": False})
    ).status_code == 404


async def test_refresh_enqueues_and_returns_202(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/local-seo/rankings/rk-1/refresh")
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"id": "rk-1", "queued": True, "held": False, "reason": ""}
    assert enqueued["refresh"] == [True]  # the worker got the job


async def test_refresh_of_an_unknown_ranking_is_404_and_never_enqueues(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo,
    enqueued: dict[str, list[Any]]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/local-seo/rankings/rk-nope/refresh")
    assert resp.status_code == 404
    assert enqueued["refresh"] == []  # the paid run is validated BEFORE it is queued


async def test_add_profile_snapshots_the_client_name_and_derives_the_score(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/local-seo/profiles",
        json={"clientId": "cl-secret", "locationLabel": "Karachi",
              "primaryCategory": "Cafe", "napName": "Verde Cafe"},
    )
    assert resp.status_code == 201, resp.text
    values = seeded.added_profiles[0]
    assert values["client_name"] == "Verde Cafe"  # resolved server-side
    assert values["client_id"] == "cl-secret"
    # The score is DERIVED, never accepted: a partial profile cannot claim 100.
    assert 0 < values["completeness_score"] < 100
    assert "audit" in values


async def test_add_profile_unknown_client_is_404_and_writes_nothing(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("manager")  # no client_names registered -> invisible/unknown
    resp = await client.post(
        "/api/v1/local-seo/profiles", json={"clientId": "cl-nope", "locationLabel": "X"}
    )
    assert resp.status_code == 404
    assert repo.added_profiles == []


@pytest.mark.parametrize(
    "body", [{"clientId": "cl-secret"}, {"locationLabel": "Karachi"}, {}]
)
async def test_add_profile_requires_a_client_and_a_location(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    body: dict[str, Any]
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/local-seo/profiles", json=body)
    assert resp.status_code == 400
    assert seeded.added_profiles == []


async def test_a_caller_cannot_set_the_completeness_score_or_the_vault_ref(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    """The derived columns + the secret pointer are server-owned: a caller that names
    them in the body must not have them written."""
    wire("manager")
    resp = await client.post(
        "/api/v1/local-seo/profiles",
        json={"clientId": "cl-secret", "locationLabel": "Karachi",
              "completenessScore": 100, "completeness_score": 100,
              "oauthVaultRef": "pwn", "oauth_vault_ref": "pwn", "oauthConnected": True},
    )
    assert resp.status_code == 201, resp.text
    values = seeded.added_profiles[0]
    assert values["completeness_score"] != 100  # derived from the (empty) fields
    assert "oauth_vault_ref" not in values
    assert "oauth_connected" not in values


async def test_patch_profile_rescores_the_merged_profile(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    """A PATCH that fills one field must re-score the WHOLE profile, or the stored
    score would disagree with the fields it describes."""
    seeded.profiles_by_id["gp-1"] = _profile_row(website_uri="")  # one gap
    wire("manager")
    resp = await client.patch(
        "/api/v1/local-seo/profiles/gp-1", json={"websiteUri": "https://verde.example"}
    )
    assert resp.status_code == 200, resp.text
    _pid, changes = seeded.updates[0]
    assert changes["website_uri"] == "https://verde.example"
    assert changes["completeness_score"] == 100  # the gap is closed -> full score
    assert "audit" in changes


async def test_patch_profile_cannot_reassign_the_client(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    """A profile's rankings + history are already attributed to its client; moving the
    profile would silently re-attribute them."""
    wire("manager")
    resp = await client.patch(
        "/api/v1/local-seo/profiles/gp-1", json={"clientId": "cl-other", "napPhone": "555"}
    )
    assert resp.status_code == 200, resp.text
    _pid, changes = seeded.updates[0]
    assert "client_id" not in changes and "client_name" not in changes


async def test_patch_profile_with_no_fields_is_400(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.patch("/api/v1/local-seo/profiles/gp-1", json={})
    assert resp.status_code == 400
    assert seeded.updates == []


async def test_patch_unknown_profile_is_404(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo
) -> None:
    wire("manager")
    resp = await client.patch(
        "/api/v1/local-seo/profiles/gp-nope", json={"primaryCategory": "Cafe"}
    )
    assert resp.status_code == 404
    assert repo.updates == []


# --------------------------------------------------------------------------- #
# 7. The GBP sync route - the approval-gated HOLD.
# --------------------------------------------------------------------------- #
async def test_the_sync_route_holds_honestly_when_no_gbp_oauth_is_configured(
    client: httpx.AsyncClient, wire: Callable[..., None], seeded: FakeLocalRepo,
    enqueued: dict[str, list[Any]]
) -> None:
    """The CURRENT deployed reality: the GBP API is approval-gated, so a token-less
    deploy answers 202 + held rather than queueing a job that cannot run - and rather
    than 500ing. The rest of the module stays fully usable."""
    wire("manager")
    resp = await client.post("/api/v1/local-seo/profiles/gp-1/sync")
    assert resp.status_code == 202, resp.text
    assert resp.json() == {
        "id": "gp-1", "queued": False, "held": True, "reason": "no_oauth_client"
    }
    assert enqueued["sync"] == []  # nothing was queued


async def test_the_sync_route_enqueues_once_an_oauth_client_is_configured(
    app: FastAPI, client: httpx.AsyncClient, wire: Callable[..., None],
    seeded: FakeLocalRepo, enqueued: dict[str, list[Any]]
) -> None:
    # The approval gate is read through the settings DEP, so activating GBP in a test
    # is the same one-line settings change it will be in production.
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, app_env="dev",
        gbp_oauth_client_id="id", gbp_oauth_client_secret="secret",
    )
    wire("manager")
    resp = await client.post("/api/v1/local-seo/profiles/gp-1/sync")
    assert resp.status_code == 202, resp.text
    assert resp.json()["queued"] is True and resp.json()["held"] is False
    assert enqueued["sync"] == ["gp-1"]


async def test_the_sync_route_404s_an_unknown_profile_before_holding(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeLocalRepo,
    enqueued: dict[str, list[Any]]
) -> None:
    wire("manager")
    assert (
        await client.post("/api/v1/local-seo/profiles/gp-nope/sync")
    ).status_code == 404
    assert enqueued["sync"] == []


# --------------------------------------------------------------------------- #
# 8. The SCOPE GUARD at the route surface.
# --------------------------------------------------------------------------- #
def test_the_module_publishes_no_gbp_posting_or_review_reply_route(app: FastAPI) -> None:
    """GBP posting + auto review-replies are NOT in the contract. GBP here is profile
    management + NAP, READ-ONLY - so no such route may exist at all."""
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    local = [p for p in paths if "local-seo" in p]
    for banned in ("post", "posts", "review", "reviews", "reply", "replies"):
        assert not any(f"/{banned}" in p for p in local), f"out-of-scope route: {banned}"


def test_the_module_publishes_no_geo_grid_route(app: FastAPI) -> None:
    """Map-pack rank is a SINGLE position per (profile, keyword, geo) at one
    representative locale - there is no grid/heatmap surface."""
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    local = [p for p in paths if "local-seo" in p]
    for banned in ("grid", "heatmap", "geogrid"):
        assert not any(banned in p for p in local), f"out-of-scope route: {banned}"
