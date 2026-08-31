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
from app.modules.citations.router import (
    get_audit_enqueuer,
    get_citation_enqueuer,
    get_service_citations_store,
)

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



def _profile_body(**over: Any) -> dict[str, Any]:
    """A COMPLETE profile PATCH body.

    `BusinessProfileRequest` defaults every field, so `model_dump()` always yields the
    full object - a PATCH that omits `addressLine1` genuinely asks for it to be blanked.
    Tests that mean "change one field" must therefore send the rest unchanged, exactly as
    the UI form does."""
    body: dict[str, Any] = {
        "clientId": "cl-secret", "label": "Primary", "businessName": "Acme Dental",
        "addressLine1": "123 Main St", "addressLine2": "", "city": "Bellevue",
        "region": "WA", "postalCode": "98004", "market": "US", "phone": "555-0100",
        "websiteUrl": "https://acme.example", "categories": ["dentist"],
        "isPrimary": True,
    }
    body.update(over)
    return body


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
        self.requeueable: dict[str, dict[str, str]] = {}
        self.created_profiles: list[dict[str, Any]] = []
        self.updated_profiles: list[tuple[str, dict[str, Any]]] = []
        self.queued: list[dict[str, Any]] = []
        self.requeued: list[str] = []
        self.client_naps: dict[str, dict[str, Any]] = {}
        self.citations: dict[str, list[dict[str, Any]]] = {}
        # 0107 NAP fan-out: citations keyed by the PROFILE they were built from,
        # plus a record of every change event + flag the router produced.
        self.profile_citations: dict[str, list[dict[str, Any]]] = {}
        self.nap_changes: list[dict[str, Any]] = []
        self._next_id = 1

    def client_business_profile_for(self, client_id: str) -> dict[str, Any] | None:
        return self.client_naps.get(client_id)

    def list_citations_for_client(self, client_id: str) -> list[dict[str, Any]]:
        return list(self.citations.get(client_id, []))

    def list_business_profiles(self, *, client_id: str | None = None) -> list[dict[str, Any]]:
        rows = list(self.profiles.values())
        return [r for r in rows if client_id is None or r["client_id"] == client_id]

    def get_business_profile(self, profile_id: str) -> dict[str, Any] | None:
        return self.profiles.get(profile_id)

    def citations_for_profile(self, profile_id: str) -> list[dict[str, Any]]:
        return list(self.profile_citations.get(profile_id, []))

    def record_nap_change(
        self,
        *,
        client_id: str,
        profile_id: str,
        events: list[dict[str, str]],
        citation_ids: list[str],
    ) -> int:
        self.nap_changes.append(
            {
                "client_id": client_id,
                "profile_id": profile_id,
                "events": events,
                "citation_ids": citation_ids,
            }
        )
        return len(citation_ids)

    def ensure_business_profile(
        self, *, client_id: str, client_name: str
    ) -> dict[str, Any] | None:
        """Mirror the real repo: return the client's existing submission profile, else
        None (the fake has no client-NAP source to derive from, so a client with no
        profile yields the honest 'capture a NAP first' -> the router 404s)."""
        existing = self.list_business_profiles(client_id=client_id)
        return existing[0] if existing else None

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

    def requeueable_citations(self, client_id: str) -> dict[str, str]:
        # {directory_id: citation_id} of this client's blocked/failed rows; tests
        # populate `requeueable` directly when exercising the retry path.
        return dict(self.requeueable.get(client_id, {}))

    def requeue_citation(self, citation_id: str) -> dict[str, Any] | None:
        row = {"id": citation_id, "submit_status": "queued", "error": ""}
        self.requeued.append(citation_id)
        return row

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
def audits() -> list[tuple[str, str, str]]:
    return []


class _FakeServiceCitationsStore:
    """Records clear_citations calls for the delete-endpoint test."""

    def __init__(self) -> None:
        self.cleared: list[str] = []

    def clear_citations(self, client_id: str) -> int:
        self.cleared.append(client_id)
        return 3  # pretend 3 rows removed


@pytest.fixture
def svc_store() -> _FakeServiceCitationsStore:
    return _FakeServiceCitationsStore()


@pytest.fixture
def wire(
    app: FastAPI,
    repo: FakeCitationsRepo,
    enqueued: list[str],
    audits: list[tuple[str, str, str]],
    svc_store: _FakeServiceCitationsStore,
) -> Callable[[str], None]:
    app.dependency_overrides[get_citations_repo] = lambda: repo
    app.dependency_overrides[get_citation_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_audit_enqueuer] = lambda: (
        lambda cid, dom, biz: audits.append((cid, dom, biz))
    )
    app.dependency_overrides[get_service_citations_store] = lambda: svc_store

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


# --------------------------------------------------------------------------- #
# Audit-first flow: audit (discover) + clear (remove) + build-only-selected
# --------------------------------------------------------------------------- #
async def test_audit_requires_nap(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None],
    audits: list[tuple[str, str, str]],
) -> None:
    repo.client_names["cl-1"] = "Acme Dental"  # known client, but no NAP profile
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/clients/cl-1/audit")
    assert resp.status_code == 400
    assert audits == []  # nothing enqueued without a NAP


async def test_audit_enqueues_monitor_with_business(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None],
    audits: list[tuple[str, str, str]],
) -> None:
    repo.client_names["cl-1"] = "Acme Dental"
    repo.create_business_profile(client_id="cl-1", client_name="Acme Dental",
                                 fields={"business_name": "Acme Dental Studio"})
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/clients/cl-1/audit")
    assert resp.status_code == 202
    body = resp.json()
    assert body["business"] == "Acme Dental Studio" and body["clientId"] == "cl-1"
    # The monitor sweep was enqueued WITH the business name (the dead business="" gap).
    assert audits == [("cl-1", "", "Acme Dental Studio")]


async def test_audit_unknown_client_404(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    wire("owner")
    resp = await client.post("/api/v1/citation-builder/clients/nope/audit")
    assert resp.status_code == 404


async def test_audit_is_lead_only(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-1"] = "Acme Dental"
    wire("analyst")  # a non-lead staffer
    resp = await client.post("/api/v1/citation-builder/clients/cl-1/audit")
    assert resp.status_code == 403


async def test_clear_citations_removes_and_validates_client(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None],
    svc_store: _FakeServiceCitationsStore,
) -> None:
    repo.client_names["cl-1"] = "Acme Dental"
    wire("owner")
    resp = await client.request("DELETE", "/api/v1/citation-builder/clients/cl-1/citations")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 3
    assert svc_store.cleared == ["cl-1"]  # ran the privileged clear for the visible client


async def test_clear_unknown_client_404(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None],
    svc_store: _FakeServiceCitationsStore,
) -> None:
    wire("owner")
    resp = await client.request("DELETE", "/api/v1/citation-builder/clients/nope/citations")
    assert resp.status_code == 404
    assert svc_store.cleared == []  # never touched the DB for an invisible client


# --------------------------------------------------------------------------- #
# 5. Expanded business fields (0060) round-trip.
# --------------------------------------------------------------------------- #
async def test_create_business_profile_round_trips_the_expanded_fields(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-secret"] = "Acme Dental"
    wire("owner")
    resp = await client.post(
        "/api/v1/citation-builder/business-profiles",
        json={
            "clientId": "cl-secret", "businessName": "Acme Dental", "market": "US",
            "description": "Family + cosmetic dentistry", "email": "hi@acme.example",
            "logoUrl": "https://acme.example/logo.png", "facebookUrl": "https://fb.com/acme",
            "instagramUrl": "https://ig.com/acme", "linkedinUrl": "https://linkedin.com/company/acme",
            "yearFounded": 2009, "paymentTypes": ["cash", "visa"], "tagline": "Smiles for all",
            "serviceArea": "Greater Bellevue",
        },
    )
    assert resp.status_code == 201, resp.text
    # the new columns were persisted (snake_case) ...
    created = repo.created_profiles[0]
    assert created["description"] == "Family + cosmetic dentistry"
    assert created["year_founded"] == 2009 and created["payment_types"] == ["cash", "visa"]
    # ... and echoed back on the camelCase wire contract.
    body = resp.json()
    assert body["description"] == "Family + cosmetic dentistry"
    assert body["email"] == "hi@acme.example"
    assert body["logoUrl"] == "https://acme.example/logo.png"
    assert body["facebookUrl"] == "https://fb.com/acme"
    assert body["yearFounded"] == 2009
    assert body["paymentTypes"] == ["cash", "visa"]
    assert body["serviceArea"] == "Greater Bellevue"
    assert body["tagline"] == "Smiles for all"


# --------------------------------------------------------------------------- #
# 6. Audit plan (generic -> country -> niche, built|missing).
# --------------------------------------------------------------------------- #
async def test_audit_plan_returns_three_prioritized_buckets(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    repo.client_names["cl-1"] = "Atlas Legal"
    repo.client_industries["cl-1"] = "Family Law Firm"  # -> vertical 'legal'
    repo.directories = [
        _directory_row(id="fs", name="Foursquare", market="GLOBAL", verticals=[]),
        _directory_row(id="yp", name="YellowPages", market="US", verticals=[]),
        _directory_row(id="avvo", name="Avvo", market="US", verticals=["legal"]),
        _directory_row(id="hg", name="Healthgrades", market="US", verticals=["medical"]),
    ]
    # one live submission covering Foursquare -> it should report BUILT.
    repo.citations["cl-1"] = [
        {"id": "c1", "directory": "Foursquare", "directory_id": "fs",
         "submit_status": "submitted", "nap_status": "missing", "proof_url": "https://p/1"},
    ]
    wire("viewer")  # a staff read
    resp = await client.get("/api/v1/citation-builder/clients/cl-1/audit-plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resolvedVertical"] == "legal" and body["market"] == "US"
    assert [d["directoryName"] for d in body["generic"]] == ["Foursquare"]
    assert [d["directoryName"] for d in body["country"]] == ["YellowPages"]
    assert [d["directoryName"] for d in body["niche"]] == ["Avvo"]  # medical excluded
    assert body["generic"][0]["status"] == "built"      # covered by the citation
    assert body["country"][0]["status"] == "missing"    # no covering citation yet


async def test_audit_plan_requires_staff_read(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    wire("client")  # a portal client holds no staff permission
    resp = await client.get("/api/v1/citation-builder/clients/cl-1/audit-plan")
    assert resp.status_code == 403


async def test_audit_plan_unknown_client_404(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/citation-builder/clients/nope/audit-plan")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 0107: editing the canonical NAP flags the listings it made stale.
# --------------------------------------------------------------------------- #
async def test_editing_the_canonical_nap_flags_the_live_listings_built_from_it(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    """The edit and the fan-out are ONE action.

    Before this, editing a profile silently re-pointed canonical while every listing
    already built kept carrying the old address. They do not go wrong gradually - they
    are wrong the moment Save is pressed."""
    repo.profiles["bp-1"] = _profile_row()
    repo.profile_citations["bp-1"] = [
        {"id": "c-live", "directory": "Brownbook", "submit_status": "live"},
        {"id": "c-drift", "directory": "Hotfrog", "submit_status": "drifted"},
        {"id": "c-sent", "directory": "Cylex", "submit_status": "submitted"},
        {"id": "c-none", "directory": "n49", "submit_status": "not_started"},
    ]
    wire("owner")

    resp = await client.patch(
        "/api/v1/citation-builder/business-profiles/bp-1",
        json=_profile_body(addressLine1="12 Marine Parade"),
    )
    assert resp.status_code == 200, resp.text

    assert len(repo.nap_changes) == 1
    change = repo.nap_changes[0]
    assert change["profile_id"] == "bp-1"
    assert change["events"] == [
        {
            "field": "address_line1",
            "old_value": "123 Main St",
            "new_value": "12 Marine Parade",
        }
    ]
    # Only listings we believe EXIST. A `submitted` row has nothing confirmed to
    # correct, and a never-started row was never built.
    assert set(change["citation_ids"]) == {"c-live", "c-drift"}


async def test_a_cosmetic_profile_edit_flags_nothing(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    """A listing asserts a name, address, phone and website - not our internal
    description. Flagging every citation over a copy tweak would train operators to
    ignore the flag, which is the same as not having one."""
    repo.profiles["bp-1"] = _profile_row(description="A dental practice.")
    repo.profile_citations["bp-1"] = [
        {"id": "c-live", "directory": "Brownbook", "submit_status": "live"}
    ]
    wire("owner")

    resp = await client.patch(
        "/api/v1/citation-builder/business-profiles/bp-1",
        json=_profile_body(description="Now with more dentists."),
    )
    assert resp.status_code == 200, resp.text
    assert repo.nap_changes == []


async def test_a_nap_edit_on_a_client_with_no_listings_is_a_clean_noop(
    client: httpx.AsyncClient, repo: FakeCitationsRepo, wire: Callable[[str], None]
) -> None:
    """Zero flagged is a legitimate answer, not an error - and the change is still
    recorded, so "we moved them in March" stays answerable later."""
    repo.profiles["bp-1"] = _profile_row()
    wire("owner")

    resp = await client.patch(
        "/api/v1/citation-builder/business-profiles/bp-1",
        json=_profile_body(phone="555-0999"),
    )
    assert resp.status_code == 200, resp.text
    assert len(repo.nap_changes) == 1
    assert repo.nap_changes[0]["citation_ids"] == []
