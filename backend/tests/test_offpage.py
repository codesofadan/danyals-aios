"""Unit tests for the Off-page module (7B): the response/request models (contract
shapes + §3 enum fidelity, esp. Web2Platform includes 'Medium'), the provider seams
(deterministic fakes, the KEYLESS CSV-import path, key-gating), and the /offpage
endpoints with a faked repo (no DB, no network).

The frontend contract (``lib/offpage.ts``) is the source of truth: every union is
pinned verbatim and the internal ``client_id`` never leaks.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.offpage_repo import get_offpage_repo
from app.schemas.offpage import (
    BacklinkResponse,
    CitationResponse,
    OffpageKpisResponse,
    Web2PropertyResponse,
    action_for,
)
from integrations.backlinks import (
    BacklinkProvider,
    BacklinkRecord,
    CsvBacklinkImporter,
    DataForSeoBacklinks,
    FakeBacklinkProvider,
    backlink_provider_from_settings,
    classify_backlink,
)
from integrations.citations import (
    BrightLocalCitations,
    CitationProvider,
    CitationRecord,
    FakeCitationProvider,
    citation_provider_from_settings,
    classify_citation,
)
from integrations.errors import ProviderNotConfiguredError

pytestmark = pytest.mark.unit

_BACKLINK_KEYS = {"id", "client", "refDomain", "anchor", "authority", "spam", "firstSeen", "status"}
_CITATION_KEYS = {"id", "client", "directory", "nap", "action", "note"}
_WEB2_KEYS = {"id", "client", "platform", "postUrl", "anchor", "verified", "published"}
_KPI_KEYS = {"referringDomains", "newLinks30d", "lostLinks30d", "toxicFlagged"}


def _emitted(model: type[Any]) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --- schema shape / enum fidelity --------------------------------------------


def test_response_models_emit_exactly_the_contract_keys() -> None:
    assert _emitted(BacklinkResponse) == _BACKLINK_KEYS
    assert _emitted(CitationResponse) == _CITATION_KEYS
    assert _emitted(Web2PropertyResponse) == _WEB2_KEYS
    assert _emitted(OffpageKpisResponse) == _KPI_KEYS


def test_web2_platform_union_includes_medium() -> None:
    import typing

    from app.schemas.offpage import Web2Platform

    platforms = set(typing.get_args(Web2Platform))
    assert platforms == {"WordPress.com", "Blogger", "Tumblr", "Medium"}
    assert "Medium" in platforms  # §3: the one that is easy to drop


def test_all_unions_are_pinned_verbatim() -> None:
    import typing

    from app.schemas.offpage import (
        BacklinkStatus,
        CitationAction,
        NapStatus,
        Web2Verified,
    )

    assert set(typing.get_args(BacklinkStatus)) == {"new", "lost", "toxic"}
    assert set(typing.get_args(NapStatus)) == {"consistent", "inconsistent", "missing"}
    assert set(typing.get_args(CitationAction)) == {"Submit", "Update"}
    assert set(typing.get_args(Web2Verified)) == {"verified", "pending"}


# --- from_row mapping ---------------------------------------------------------


def _backlink_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "bl-uuid", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "ref_domain": "healthgrades.com", "anchor": "family dentist", "authority": 88,
        "spam": 2, "first_seen": date(2026, 7, 8), "status": "new",
    }
    row.update(over)
    return row


def test_backlink_from_row_aliases_and_formats_without_leaking_client_id() -> None:
    dumped = BacklinkResponse.from_row(_backlink_row()).model_dump(by_alias=True)
    assert set(dumped) == _BACKLINK_KEYS
    assert "client_id" not in dumped
    assert dumped["refDomain"] == "healthgrades.com"
    assert dumped["client"] == "NorthPeak Dental"
    assert dumped["firstSeen"] == "Jul 08, 2026"  # calendar-formatted date


def test_backlink_from_row_unknown_status_and_missing_date_fall_back() -> None:
    resp = BacklinkResponse.from_row(_backlink_row(status="???", first_seen=None))
    assert resp.status == "new"
    assert resp.first_seen == "—"


def _citation_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "ct-uuid", "client_id": "cl-secret", "client_name": "Verde Cafe",
        "directory": "Yelp", "nap_status": "inconsistent", "action": "Update",
        "note": "Suite # differs",
    }
    row.update(over)
    return row


def test_citation_from_row_maps_and_hides_client_id() -> None:
    dumped = CitationResponse.from_row(_citation_row()).model_dump(by_alias=True)
    assert set(dumped) == _CITATION_KEYS
    assert "client_id" not in dumped
    assert dumped["nap"] == "inconsistent"
    assert dumped["action"] == "Update"


def test_citation_action_derives_when_not_stored() -> None:
    # A missing listing with no stored action derives Submit; anything else Update.
    missing = CitationResponse.from_row(
        _citation_row(nap_status="missing", action=None)
    )
    assert missing.action == "Submit"
    consistent = CitationResponse.from_row(
        _citation_row(nap_status="consistent", action=None)
    )
    assert consistent.action == "Update"


def test_action_for_rule() -> None:
    assert action_for("missing") == "Submit"
    assert action_for("consistent") == "Update"
    assert action_for("inconsistent") == "Update"


def _web2_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "w2-uuid", "client_id": "cl-secret", "client_name": "Lumen Realty",
        "platform": "Medium", "post_url": "medium.com/@lumen/guide",
        "anchor": "buyer guide", "verified": "verified",
        "published_at": date(2026, 7, 5),
    }
    row.update(over)
    return row


def test_web2_from_row_aliases_and_keeps_medium() -> None:
    dumped = Web2PropertyResponse.from_row(_web2_row()).model_dump(by_alias=True)
    assert set(dumped) == _WEB2_KEYS
    assert "client_id" not in dumped
    assert dumped["platform"] == "Medium"  # §3: Medium round-trips
    assert dumped["postUrl"] == "medium.com/@lumen/guide"
    assert dumped["published"] == "Jul 05, 2026"


def test_web2_from_row_unknown_platform_falls_back() -> None:
    resp = Web2PropertyResponse.from_row(_web2_row(platform="???", verified="???"))
    assert resp.platform == "WordPress.com"
    assert resp.verified == "pending"


# --- backlink provider seam ---------------------------------------------------


def test_classify_backlink_toxicity_wins() -> None:
    assert classify_backlink(94) == "toxic"
    assert classify_backlink(94, lost=True) == "toxic"  # toxic beats lost
    assert classify_backlink(4, lost=True) == "lost"
    assert classify_backlink(4) == "new"


def test_fake_backlink_deterministic_varies_and_spans_statuses() -> None:
    fake = FakeBacklinkProvider()
    a = fake.fetch_backlinks("northpeakdental.com")
    b = fake.fetch_backlinks("northpeakdental.com")
    assert a == b  # same target -> identical profile (stable golden tests)
    assert isinstance(a[0], BacklinkRecord)
    # First three are pinned one-per-status so every branch is exercised.
    statuses = {r.status for r in a}
    assert {"toxic", "lost", "new"} <= statuses
    assert all(0 <= r.spam <= 100 and 0 <= r.authority <= 100 for r in a)
    assert fake.fetch_backlinks("other.com") != a  # different target differs


def test_fake_backlink_satisfies_protocol() -> None:
    assert isinstance(FakeBacklinkProvider(), BacklinkProvider)
    # Construction is network-free; it only builds an httpx.Client.
    assert isinstance(DataForSeoBacklinks(login="u", password="p"), BacklinkProvider)


def test_csv_import_is_keyless_and_derives_status() -> None:
    csv_text = (
        "Referring Domain,Anchor,Domain Rating,Spam Score,First Seen,Lost\n"
        "healthgrades.com,family dentist,88,2,2026-07-08,\n"
        "cheap-seo-links.ru,buy links,8,94,2026-06-26,\n"
        "old-partner.com,partner,70,5,2026-06-01,true\n"
        ",orphan row,50,50,2026-01-01,\n"  # no referring domain -> skipped
    )
    records = CsvBacklinkImporter().parse(csv_text)  # NO key needed
    assert len(records) == 3  # the domain-less row is dropped
    assert [r.status for r in records] == ["new", "toxic", "lost"]
    assert records[0].ref_domain == "healthgrades.com"
    assert records[0].authority == 88
    assert records[0].first_seen == date(2026, 7, 8)
    assert records[2].lost is True


def test_dataforseo_requires_credentials() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="DATAFORSEO"):
        DataForSeoBacklinks(login="", password="")
    with pytest.raises(ProviderNotConfiguredError, match="DATAFORSEO"):
        DataForSeoBacklinks(login="u", password="")  # login but no password


def test_backlink_factory_degrades_without_credentials() -> None:
    assert backlink_provider_from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_backlink_factory_builds_real_with_credentials() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, dataforseo_login="acct", dataforseo_password="pw"
    )
    provider = backlink_provider_from_settings(settings)
    assert isinstance(provider, DataForSeoBacklinks)


# --- citation provider seam ---------------------------------------------------


def test_classify_citation_rule() -> None:
    assert classify_citation(found=False, nap_matches=False) == "missing"
    assert classify_citation(found=True, nap_matches=False) == "inconsistent"
    assert classify_citation(found=True, nap_matches=True) == "consistent"


def test_fake_citation_deterministic_and_spans_states() -> None:
    fake = FakeCitationProvider()
    a = fake.fetch_citations("Verde Cafe")
    b = fake.fetch_citations("Verde Cafe")
    assert a == b
    assert isinstance(a[0], CitationRecord)
    states = {r.nap_status for r in a}
    assert {"consistent", "inconsistent", "missing"} <= states
    assert fake.fetch_citations("Atlas Legal") != a


def test_fake_citation_satisfies_protocol() -> None:
    assert isinstance(FakeCitationProvider(), CitationProvider)
    assert isinstance(BrightLocalCitations(api_key="k"), CitationProvider)


def test_brightlocal_requires_a_key() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="BRIGHTLOCAL_API_KEY"):
        BrightLocalCitations(api_key="")


def test_citation_factory_degrades_without_key() -> None:
    assert citation_provider_from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_citation_factory_builds_real_with_key() -> None:
    settings = Settings(_env_file=None, brightlocal_api_key="bl")  # type: ignore[call-arg]
    provider = citation_provider_from_settings(settings)
    assert isinstance(provider, BrightLocalCitations)


# --- endpoints (faked repo) ---------------------------------------------------


class FakeOffpageRepo:
    def __init__(self) -> None:
        self.backlinks: list[dict[str, Any]] = []
        self.citations: dict[str, dict[str, Any]] = {}
        self.web2: list[dict[str, Any]] = []
        self.status_counts: dict[str, int] = {}
        self.referring = 0
        self.flagged: list[dict[str, Any]] = []
        self.list_backlinks_kwargs: dict[str, Any] | None = None
        self.bulk_ids: list[str] | None = None

    def list_backlinks(
        self, *, status: str | None = None, client_id: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.list_backlinks_kwargs = {"status": status, "client_id": client_id}
        rows = self.backlinks
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def backlink_status_counts(self) -> dict[str, int]:
        return self.status_counts

    def referring_domain_count(self) -> int:
        return self.referring

    def flag_toxic_backlinks(self, *, spam_threshold: int) -> list[dict[str, Any]]:
        return [r for r in self.flagged if r.get("spam", 0) >= spam_threshold]

    def list_citations(
        self, *, nap_status: str | None = None, client_id: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.citations.values())
        if nap_status is not None:
            rows = [r for r in rows if r.get("nap_status") == nap_status]
        return rows

    def get_citation(self, citation_id: str) -> dict[str, Any] | None:
        return self.citations.get(citation_id)

    def update_citation(
        self, citation_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self.citations.get(citation_id)
        if row is None:
            return None
        row.update(changes)
        return row

    def bulk_update_citations(
        self, ids: list[str], changes: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.bulk_ids = ids
        out: list[dict[str, Any]] = []
        for cid in ids:
            row = self.citations.get(cid)
            if row is not None:
                row.update(changes)
                out.append(row)
        return out

    def list_web2(
        self, *, client_id: str | None = None, platform: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.web2


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeOffpageRepo:
    return FakeOffpageRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeOffpageRepo) -> Callable[..., None]:
    app.dependency_overrides[get_offpage_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_client_forbidden_from_all_reads(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/offpage/backlinks")).status_code == 403
    assert (await client.get("/api/v1/offpage/citations")).status_code == 403
    assert (await client.get("/api/v1/offpage/web2")).status_code == 403
    assert (await client.get("/api/v1/offpage/kpis")).status_code == 403


async def test_backlinks_shape_and_status_filter(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.backlinks = [
        _backlink_row(id="bl-1", status="new"),
        _backlink_row(id="bl-2", status="toxic", spam=94),
    ]
    wire("viewer")
    resp = await client.get("/api/v1/offpage/backlinks", params={"status": "toxic"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == _BACKLINK_KEYS
    assert "client_id" not in body[0]
    assert repo.list_backlinks_kwargs == {"status": "toxic", "client_id": None}
    assert [b["status"] for b in body] == ["toxic"]


async def test_backlinks_rejects_bad_status(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/offpage/backlinks", params={"status": "bogus"})
    assert resp.status_code == 422  # not a BacklinkStatus


async def test_flag_toxic_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    wire("specialist")  # holds view_reports but is not a lead
    resp = await client.post("/api/v1/offpage/backlinks/flag-toxic", json={})
    assert resp.status_code == 403


async def test_flag_toxic_flags_and_counts(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.flagged = [
        _backlink_row(id="bl-1", spam=94, client_id="cl-1"),
        _backlink_row(id="bl-2", spam=30, client_id="cl-1"),
    ]
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/backlinks/flag-toxic", json={"spamThreshold": 60}
    )
    assert resp.status_code == 200
    assert resp.json() == {"flagged": 1}  # only the spam>=60 row


async def test_citations_shape_and_nap_filter(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.citations = {
        "ct-1": _citation_row(id="ct-1", nap_status="missing", action="Submit"),
        "ct-2": _citation_row(id="ct-2", nap_status="consistent", action="Update"),
    }
    wire("analyst")
    resp = await client.get("/api/v1/offpage/citations", params={"nap": "missing"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == _CITATION_KEYS
    assert [c["nap"] for c in body] == ["missing"]


async def test_citation_action_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.citations = {"ct-1": _citation_row(id="ct-1")}
    wire("specialist")
    resp = await client.post(
        "/api/v1/offpage/citations/ct-1/action", json={"action": "Update"}
    )
    assert resp.status_code == 403


async def test_citation_action_resolves_to_consistent(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.citations = {
        "ct-1": _citation_row(id="ct-1", nap_status="missing", action="Submit")
    }
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/citations/ct-1/action", json={"action": "Submit"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nap"] == "consistent"
    assert body["action"] == "Update"  # a resolved listing is an Update going forward


async def test_citation_action_missing_is_404(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/citations/nope/action", json={"action": "Update"}
    )
    assert resp.status_code == 404


async def test_bulk_update_marks_all_consistent(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.citations = {
        "ct-1": _citation_row(id="ct-1", nap_status="missing"),
        "ct-2": _citation_row(id="ct-2", nap_status="inconsistent"),
    }
    wire("admin", "u-admin")
    resp = await client.post(
        "/api/v1/offpage/citations/bulk", json={"ids": ["ct-1", "ct-2"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert repo.bulk_ids == ["ct-1", "ct-2"]
    assert all(c["nap"] == "consistent" for c in body)


async def test_bulk_update_requires_non_empty_ids(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/citations/bulk", json={"ids": []})
    assert resp.status_code == 422  # min_length=1


async def test_web2_read_shape(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.web2 = [_web2_row(id="w2-1")]
    wire("viewer")
    resp = await client.get("/api/v1/offpage/web2")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == _WEB2_KEYS
    assert body[0]["platform"] == "Medium"


async def test_kpis_assemble_from_counts(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None]
) -> None:
    repo.status_counts = {"new": 96, "lost": 23, "toxic": 8}
    repo.referring = 1284
    wire("viewer")
    resp = await client.get("/api/v1/offpage/kpis")
    assert resp.status_code == 200
    assert resp.json() == {
        "referringDomains": 1284,
        "newLinks30d": 96,
        "lostLinks30d": 23,
        "toxicFlagged": 8,
    }
