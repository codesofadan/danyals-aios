"""Wave 4 gate: the client business-profile (NAP) persistence path - the Add-Client
wizard writing a NAP at creation, the GET/PUT endpoints, and the honest-state guard in
the citation-submit worker that BLOCKS (never force-fails) a listing with no NAP.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo
from app.modules.citations.tasks import execute_citation_submit

pytestmark = pytest.mark.unit


class FakeRepo:
    """In-memory clients repo covering the NAP path (mirrors tests/test_clients.py)."""

    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.profiles: dict[str, dict[str, Any]] = {}  # client_id -> NAP row
        self._seq = 0

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def seed_client(self, **over: Any) -> dict[str, Any]:
        row: dict[str, Any] = {"id": over.get("id", self._id("cl")), "name": "NorthPeak"}
        row.update(over)
        self.clients[row["id"]] = row
        return row

    def insert_client(self, row: dict[str, Any]) -> dict[str, Any]:
        cid = self._id("cl")
        record = {"id": cid, **row}
        self.clients[cid] = record
        return record

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self.clients.get(client_id)

    def site_counts(self) -> dict[str, int]:
        return {}

    def get_business_profile(self, client_id: str) -> dict[str, Any] | None:
        return self.profiles.get(client_id)

    def upsert_business_profile(
        self, *, client_id: str, client_name: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        row = {"id": self._id("bp"), "client_id": client_id, "client_name": client_name, **fields}
        self.profiles[client_id] = row
        return row


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeRepo) -> Callable[[str], None]:
    app.dependency_overrides[get_clients_repo] = lambda: repo

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


# --------------------------------------------------------------------------- #
# NAP persisted at client creation
# --------------------------------------------------------------------------- #
async def test_create_client_persists_the_nap(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/clients",
        json={
            "cn": "Acme Dental", "industry": "Healthcare",
            "business": {
                "businessName": "Acme Dental", "addressLine1": "123 Main St",
                "city": "Bellevue", "phone": "555-0100", "primaryCategory": "Dentist",
            },
        },
    )
    assert resp.status_code == 201
    created_id = resp.json()["id"]
    assert created_id in repo.profiles
    assert repo.profiles[created_id]["business_name"] == "Acme Dental"
    assert repo.profiles[created_id]["primary_category"] == "Dentist"


async def test_create_client_skips_an_empty_nap(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/clients",
        json={"cn": "No NAP Co", "business": {"businessName": "   ", "city": ""}},
    )
    assert resp.status_code == 201
    # a wholly empty profile is not written
    assert resp.json()["id"] not in repo.profiles


# --------------------------------------------------------------------------- #
# GET / PUT the client business profile
# --------------------------------------------------------------------------- #
async def test_get_business_profile_404_without_one(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    wire("viewer")
    resp = await client.get(f"/api/v1/clients/{cl['id']}/business-profile")
    assert resp.status_code == 404


async def test_put_then_get_business_profile_roundtrips(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    wire("admin")
    put = await client.put(
        f"/api/v1/clients/{cl['id']}/business-profile",
        json={"businessName": "Acme", "city": "Bellevue", "extraCategories": ["Dentist"]},
    )
    assert put.status_code == 200
    assert put.json()["businessName"] == "Acme"
    assert put.json()["extraCategories"] == ["Dentist"]

    got = await client.get(f"/api/v1/clients/{cl['id']}/business-profile")
    assert got.status_code == 200
    assert got.json()["city"] == "Bellevue"


async def test_put_business_profile_requires_manage_clients(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None]
) -> None:
    cl = repo.seed_client()
    wire("viewer")  # no manage_clients
    resp = await client.put(
        f"/api/v1/clients/{cl['id']}/business-profile", json={"businessName": "X"}
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Worker honest-state guard: no NAP -> blocked (never a force-failed listing)
# --------------------------------------------------------------------------- #
class _FakeStore:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.updates: list[dict[str, Any]] = []

    def load_citation_with_directory(self, citation_id: str) -> dict[str, Any] | None:
        return dict(self.row)

    def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        self.row.update(fields)


def test_citation_submit_blocks_when_nap_is_missing() -> None:
    store = _FakeStore(
        {"submit_status": "queued", "bp_business_name": "", "directory_tier": "api",
         "client_id": "cl-1", "client_name": "Acme"}
    )
    settings = Settings(_env_file=None, app_env="dev")  # type: ignore[call-arg]
    result = execute_citation_submit(store, settings, "c-1")  # type: ignore[arg-type]
    assert result["state"] == "blocked"
    assert result["reason"] == "no business profile / NAP"
    # the row is marked blocked with an honest reason - nothing was dispatched/spent
    assert store.updates and store.updates[-1]["submit_status"] == "blocked"
    assert "no business profile" in store.updates[-1]["error"]


# --------------------------------------------------------------------------- #
# Keyword bank seeded at client creation (2026-09-17)
# --------------------------------------------------------------------------- #
# The content module targets terms from the client's bank. Onboarding has always
# had a "Build keyword seed list" STEP, but it was a checklist tickbox with no data
# behind it, so every client started with an empty bank and each content run
# invented its own targets - which is how content and rank tracking end up chasing
# different terms for the same client.
class _FakeKeywordRepo:
    """Captures what the create endpoint writes to the bank."""

    calls: list[dict[str, Any]] = []

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def add_keywords(
        self, *, client_id: str | None, client_name: str, geo: str | None,
        keywords: list[str], created_by: str,
    ) -> list[dict[str, Any]]:
        _FakeKeywordRepo.calls.append({
            "client_id": client_id, "client_name": client_name, "geo": geo,
            "keywords": list(keywords), "created_by": created_by,
        })
        return [{"keyword": k} for k in keywords]


@pytest.fixture
def bank(monkeypatch: pytest.MonkeyPatch) -> type[_FakeKeywordRepo]:
    _FakeKeywordRepo.calls = []
    monkeypatch.setattr(
        "app.modules.keyword_research.repo.KeywordRepo", _FakeKeywordRepo, raising=True
    )
    return _FakeKeywordRepo


async def test_create_client_seeds_the_keyword_bank(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None],
    bank: type[_FakeKeywordRepo],
) -> None:
    """The wiring that makes onboarding feed content. Re-inject by deleting the
    `if body.keywords:` block in create_client and this fails."""
    wire("manager")
    resp = await client.post(
        "/api/v1/clients",
        json={
            "cn": "Acme Dental",
            "keywords": ["emergency dentist", "teeth whitening"],
            "keywordGeo": "Bellevue",
        },
    )
    assert resp.status_code == 201
    assert len(bank.calls) == 1
    call = bank.calls[0]
    assert call["client_id"] == resp.json()["id"]
    assert call["client_name"] == "Acme Dental"
    assert call["geo"] == "Bellevue"
    assert call["keywords"] == ["emergency dentist", "teeth whitening"]


async def test_create_client_without_keywords_touches_the_bank_not_at_all(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None],
    bank: type[_FakeKeywordRepo],
) -> None:
    wire("manager")
    resp = await client.post("/api/v1/clients", json={"cn": "No Keywords Co"})
    assert resp.status_code == 201
    assert bank.calls == []


async def test_a_blank_geo_is_sent_as_none_not_an_empty_string(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None],
    bank: type[_FakeKeywordRepo],
) -> None:
    """geo is part of the bank's uniqueness key (client, keyword, geo). An empty
    string and NULL are different keys, so a non-local client's terms must land as
    NULL or they dedupe against nothing."""
    wire("manager")
    resp = await client.post(
        "/api/v1/clients", json={"cn": "National Co", "keywords": ["seo software"]}
    )
    assert resp.status_code == 201
    assert bank.calls[0]["geo"] is None


async def test_a_bank_failure_never_fails_the_client_creation(
    client: httpx.AsyncClient, repo: FakeRepo, wire: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort, exactly like the NAP seed above: a client that already exists in
    the database must not 500 because a follow-on write hiccuped."""
    class _Boom:
        def __init__(self, user_id: str) -> None: ...
        def add_keywords(self, **kw: Any) -> list[dict[str, Any]]:
            raise RuntimeError("bank unavailable")

    monkeypatch.setattr(
        "app.modules.keyword_research.repo.KeywordRepo", _Boom, raising=True
    )
    wire("manager")
    resp = await client.post(
        "/api/v1/clients", json={"cn": "Resilient Co", "keywords": ["plumber"]}
    )
    assert resp.status_code == 201
    assert resp.json()["id"] in repo.clients
