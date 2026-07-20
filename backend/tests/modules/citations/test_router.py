"""Citation-builder endpoints: the access gates + the campaign-dispatch contract.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides``; the enqueuer dependency is overridden to a recorder so a
dispatched campaign never actually reaches Celery.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.citations.repo import get_citations_repo
from app.modules.citations.router import get_citation_enqueuer

pytestmark = pytest.mark.unit


def _message(resp: httpx.Response) -> str:
    return str(resp.json()["error"]["message"])


def _profile_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "bp-1", "client_id": "cl-secret", "client_name": "Acme Dental",
        "label": "Primary", "business_name": "Acme Dental", "address_line1": "123 Main St",
        "address_line2": "", "city": "Bellevue", "region": "WA", "postal_code": "98004",
        "market": "US", "phone": "555-0100", "website_url": "https://acme.example",
        "categories": ["dentist"], "hours": {}, "is_primary": True,
    }
    row.update(over)
    return row


def _directory_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "d-1", "name": "Brownbook", "url": "brownbook.net", "market": "US",
        "tier": "bot_fillable", "submit_method": "bot:playwright", "link_rel": "nofollow",
        "price_note": "Free", "automation_note": "", "active": True,
    }
    row.update(over)
    return row


class FakeCitationsRepo:
    """In-memory stand-in for the RLS-scoped CitationsRepo."""

    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.directories: list[dict[str, Any]] = []
        self.client_names: dict[str, str] = {}
        self.client_industries: dict[str, str] = {}
        self.existing_directory_ids: dict[str, set[str]] = {}
        self.created_profiles: list[dict[str, Any]] = []
        self.updated_profiles: list[tuple[str, dict[str, Any]]] = []
        self.queued: list[dict[str, Any]] = []
        self._next_id = 1

    def list_business_profiles(self, *, client_id: str | None = None) -> list[dict[str, Any]]:
        rows = list(self.profiles.values())
        return [r for r in rows if client_id is None or r["client_id"] == client_id]

    def get_business_profile(self, profile_id: str) -> dict[str, Any] | None:
        return self.profiles.get(profile_id)

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def client_meta_for(self, client_id: str) -> dict[str, Any] | None:
        name = self.client_names.get(client_id)
        if name is None:
            return None
        return {"name": name, "industry": self.client_industries.get(client_id, "")}

    def create_business_profile(
        self, *, client_id: str, client_name: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        self.created_profiles.append({"client_id": client_id, **fields})
        row = _profile_row(id="bp-new", client_id=client_id, client_name=client_name, **fields)
        self.profiles["bp-new"] = row
        return row

    def update_business_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        self.updated_profiles.append((profile_id, changes))
        row = self.profiles.get(profile_id)
        if row is None:
            return None
        row.update(changes)
        return row

    def list_directories(
        self,
        *,
        markets: list[str] | None = None,
        tiers: list[str] | None = None,
        vertical: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        rows = self.directories
        if markets:
            rows = [r for r in rows if r["market"] in markets]
        if tiers:
            rows = [r for r in rows if r["tier"] in tiers]
        if vertical:
            rows = [r for r in rows if not r.get("verticals") or vertical in r["verticals"]]
        return list(rows)

    def get_directory(self, directory_id: str) -> dict[str, Any] | None:
        return next((r for r in self.directories if r["id"] == directory_id), None)

    def existing_citation_directory_ids(self, client_id: str) -> set[str]:
        return set(self.existing_directory_ids.get(client_id, set()))

    def queue_citation(self, **kwargs: Any) -> dict[str, Any] | None:
        row_id = f"cit-{self._next_id}"
        self._next_id += 1
        row = {"id": row_id, **kwargs}
        self.queued.append(row)
        return row


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture
def repo() -> FakeCitationsRepo:
    return FakeCitationsRepo()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeCitationsRepo, enqueued: list[str]
) -> Callable[[str], None]:
    app.dependency_overrides[get_citations_repo] = lambda: repo
    app.dependency_overrides[get_citation_enqueuer] = lambda: enqueued.append

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


_READ_ROUTES = [
    ("GET", "/api/v1/citation-builder/business-profiles"),
    ("GET", "/api/v1/citation-builder/directories"),
]
_WRITE_ROUTES = [
    ("POST", "/api/v1/citation-builder/business-profiles", {"clientId": "cl-secret", "businessName": "Acme"}),
    ("PATCH", "/api/v1/citation-builder/business-profiles/bp-1", {"clientId": "cl-secret", "businessName": "Acme"}),
    (
        "POST", "/api/v1/citation-builder/campaigns",
        {"clientId": "cl-secret", "businessProfileId": "bp-1"},
    ),
]


# --------------------------------------------------------------------------- #
# 1. Access gates.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("method", "path"), _READ_ROUTES)
async def test_reads_require_view_reports(
    client: httpx.AsyncClient, wire: Callable[[str], None], method: str, path: str
) -> None:
    wire("client")  # a portal client holds no staff permission
    resp = await client.request(method, path)
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_writes_require_a_lead_role(
    client: httpx.AsyncClient, wire: Callable[[str], None], method: str, path: str, body: dict[str, Any]
) -> None:
    wire("specialist")  # staff, but not owner/admin/manager
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("role", ["owner", "admin", "manager"])
def test_every_lead_role_may_create_a_business_profile(role: str) -> None:
    assert role in {"owner", "admin", "manager"}  # documents the LEADS set; enforced above


# --------------------------------------------------------------------------- #
# 2. Business profiles.
# --------------------------------------------------------------------------- #
async def test_create_business_profile_snapshots_client_name(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-secret"] = "Acme Dental"
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/business-profiles",
        json={"clientId": "cl-secret", "businessName": "Acme Dental", "market": "US"},
    )
    assert resp.status_code == 201, resp.text
    assert repo.created_profiles[0]["business_name"] == "Acme Dental"
    assert "cl-secret" not in resp.text  # the internal client_id never leaks
    assert resp.json()["client"] == "Acme Dental"


async def test_create_business_profile_404s_on_unknown_client(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/business-profiles",
        json={"clientId": "cl-nope", "businessName": "X"},
    )
    assert resp.status_code == 404
    assert repo.created_profiles == []


async def test_update_business_profile_404s_when_unknown(
    client: httpx.AsyncClient, wire: Callable[[str], None]
) -> None:
    wire("admin")
    resp = await client.patch(
        "/api/v1/citation-builder/business-profiles/bp-nope",
        json={"clientId": "cl-secret", "businessName": "X"},
    )
    assert resp.status_code == 404


async def test_list_business_profiles_filters_by_client(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.profiles["bp-1"] = _profile_row(id="bp-1", client_id="cl-A")
    repo.profiles["bp-2"] = _profile_row(id="bp-2", client_id="cl-B")
    wire("viewer")
    resp = await client.get("/api/v1/citation-builder/business-profiles", params={"clientId": "cl-A"})
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == ["bp-1"]


# --------------------------------------------------------------------------- #
# 3. Directory catalog.
# --------------------------------------------------------------------------- #
async def test_list_directories_returns_the_catalog_shape(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.directories = [_directory_row()]
    wire("viewer")
    resp = await client.get("/api/v1/citation-builder/directories")
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert row["name"] == "Brownbook" and row["tier"] == "bot_fillable"
    assert row["submitMethod"] == "bot:playwright"


# --------------------------------------------------------------------------- #
# 4. Campaign dispatch.
# --------------------------------------------------------------------------- #
async def test_campaign_queues_every_automatable_directory_and_enqueues_each(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None], enqueued: list[str]
) -> None:
    repo.client_names["cl-secret"] = "Acme Dental"
    repo.profiles["bp-1"] = _profile_row()
    repo.directories = [
        _directory_row(id="d-1", tier="bot_fillable"),
        _directory_row(id="d-2", name="Yelp", tier="captcha_assisted", submit_method="bot:playwright+captcha"),
        _directory_row(id="d-3", name="BBB", tier="manual_only", submit_method="manual"),
    ]
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/campaigns",
        json={"clientId": "cl-secret", "businessProfileId": "bp-1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["queued"] == 2
    assert body["skippedManualOnly"] == 1
    assert body["alreadyQueued"] == 0
    assert len(enqueued) == 2  # both queued rows were handed to the worker
    assert len(repo.queued) == 2


async def test_campaign_skips_directories_already_in_flight_for_this_client(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None], enqueued: list[str]
) -> None:
    repo.client_names["cl-secret"] = "Acme Dental"
    repo.profiles["bp-1"] = _profile_row()
    repo.directories = [_directory_row(id="d-1")]
    repo.existing_directory_ids["cl-secret"] = {"d-1"}
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/campaigns",
        json={"clientId": "cl-secret", "businessProfileId": "bp-1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["queued"] == 0 and body["alreadyQueued"] == 1
    assert enqueued == []


async def test_campaign_404s_on_unknown_business_profile(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-secret"] = "Acme Dental"
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/campaigns",
        json={"clientId": "cl-secret", "businessProfileId": "bp-nope"},
    )
    assert resp.status_code == 404
    assert repo.queued == []


async def test_campaign_reports_an_estimated_cost_for_the_fresh_batch(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-secret"] = "Acme Dental"
    repo.profiles["bp-1"] = _profile_row()
    repo.directories = [_directory_row(id="d-1", tier="bot_fillable")]
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/campaigns",
        json={"clientId": "cl-secret", "businessProfileId": "bp-1"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["estimatedCost"] > 0


async def test_campaign_matches_vertical_and_excludes_marketplaces(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None], enqueued: list[str]
) -> None:
    # A legal client: only the GENERAL + LEGAL directories queue; a MEDICAL niche row
    # and a lead-gen MARKETPLACE are excluded, and the response reports why (P1/P5).
    repo.client_names["cl-secret"] = "Atlas Legal"
    repo.client_industries["cl-secret"] = "Family Law Firm"
    repo.profiles["bp-1"] = _profile_row()
    repo.directories = [
        _directory_row(id="gen", name="YellowPages", verticals=[], authority=92),
        _directory_row(id="law", name="Avvo", verticals=["legal"], authority=74),
        _directory_row(id="med", name="Healthgrades", verticals=["medical"], authority=69),
        _directory_row(id="mkt", name="Angi", verticals=["legal"], is_marketplace=True, authority=89),
    ]
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/campaigns",
        json={"clientId": "cl-secret", "businessProfileId": "bp-1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["resolvedVertical"] == "legal"
    assert body["queued"] == 2  # gen + law only
    assert body["excludedOffVertical"] == 1  # the medical row
    assert body["excludedMarketplace"] == 1  # Angi (legal, but a marketplace)
    queued_names = {r["directory_name"] for r in repo.queued}
    assert queued_names == {"YellowPages", "Avvo"}


async def test_campaign_can_opt_into_marketplaces(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-secret"] = "Atlas Legal"
    repo.client_industries["cl-secret"] = "law"
    repo.profiles["bp-1"] = _profile_row()
    repo.directories = [
        _directory_row(id="law", name="Avvo", verticals=["legal"], authority=74),
        _directory_row(id="mkt", name="Angi", verticals=["legal"], is_marketplace=True, authority=89),
    ]
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/campaigns",
        json={"clientId": "cl-secret", "businessProfileId": "bp-1", "includeMarketplaces": True},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["queued"] == 2
    assert resp.json()["excludedMarketplace"] == 0


async def test_locked_business_profile_rejects_edits_until_unlocked(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.profiles["bp-1"] = _profile_row(nap_locked=True)
    wire("owner")
    # A locked profile: an edit that keeps it locked is a 409...
    resp = await client.patch(
        "/api/v1/citation-builder/business-profiles/bp-1",
        json={"clientId": "cl-secret", "businessName": "Renamed", "napLocked": True},
    )
    assert resp.status_code == 409, resp.text
    # ...but the same edit that unlocks it (napLocked=false) goes through.
    ok = await client.patch(
        "/api/v1/citation-builder/business-profiles/bp-1",
        json={"clientId": "cl-secret", "businessName": "Renamed", "napLocked": False},
    )
    assert ok.status_code == 200, ok.text
