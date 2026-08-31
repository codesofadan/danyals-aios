"""Unit tests for the Off-page module (7B): the response/request models (contract
shapes + §3 enum fidelity, esp. Web2Platform includes 'Medium'), the provider seams
(deterministic fakes, the KEYLESS CSV-import path, key-gating), and the /offpage
endpoints with a faked repo (no DB, no network).

The frontend contract (``lib/offpage.ts``) is the source of truth: every union is
pinned verbatim and the internal ``client_id`` never leaks.
"""

from __future__ import annotations

import json
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
_CITATION_KEYS = {
    "id", "client", "directory", "nap", "action", "note", "submitStatus", "proofUrl",
    "handoffUrl",
}
_WEB2_KEYS = {
    "id", "client", "platform", "postUrl", "anchor", "verified", "published", "status",
}
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
    # 7B-4 grew this from 4 to 17 platforms, then Webflow/HubSpot CMS/Drupal/Joomla
    # grew it again to 21, then a third pass of 19 more grew it to 40, then a fourth
    # pass of 10 more grew it to 50, then a fifth pass of 3 headless CMSs grew it to 53
    # (integrations/web2_publishers.py); the ORIGINAL four must still all be present,
    # and Medium specifically - the one that is easy to drop since it is draft-only
    # (no live publisher exists for it).
    assert {"WordPress.com", "Blogger", "Tumblr", "Medium"} <= platforms
    assert len(platforms) == 54
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
        self.web2_by_id: dict[str, dict[str, Any]] = {}
        self.client_names: dict[str, str] = {}
        self.created_web2: list[dict[str, Any]] = []
        # --- campaigns ---
        self.campaigns: dict[str, dict[str, Any]] = {}
        self.client_scope = "agnostic"
        self.catalog_rows: list[dict[str, Any]] = [
            {
                "name": "Blogger", "platform_enum": "Blogger", "ownership_tier": "per_client",
                "topical_scope": "agnostic", "automation_ready": True,
                "authority_tier": "high", "terms_position": "",
            },
            {
                "name": "WordPress.com", "platform_enum": "WordPress.com",
                "ownership_tier": "per_client", "topical_scope": "agnostic",
                "automation_ready": True, "authority_tier": "high", "terms_position": "",
            },
            {
                "name": "dev.to", "platform_enum": "dev.to", "ownership_tier": "per_client",
                "topical_scope": "developer", "automation_ready": True,
                "authority_tier": "medium",
                "terms_position": "Content Policy bans promotional posts.",
            },
        ]
        self.attached: list[tuple[str, str]] = []
        # Platforms where the client has a usable account. Defaults to "all catalogued
        # platforms are connected" so campaign tests exercise campaign mechanics rather
        # than re-testing connectivity; the tests that are ABOUT connectivity set this
        # explicitly, including to the empty set.
        self.accounts: dict[str, dict[str, Any]] = {}
        self.connected: set[str] = {
            str(r["platform_enum"]) for r in self.catalog_rows if r.get("platform_enum")
        }

    # --- campaign surface ---
    def eligible_catalog(self) -> list[dict[str, Any]]:
        return list(self.catalog_rows)

    def client_web2_scope(self, client_id: str) -> str:
        return self.client_scope

    def connected_platforms_for(self, client_id: str) -> set[str]:
        return set(self.connected)

    def get_web2_account(self, account_id: str) -> dict[str, Any] | None:
        return self.accounts.get(account_id)

    def pacing_caps_row(self) -> dict[str, Any] | None:
        # Jitter off and the campaign cap lifted so these tests assert the ROUTER's
        # contract rather than re-testing the pacing service.
        return {"publish_jitter_max_hours": 0, "max_properties_per_client_campaign": 0}

    def client_publish_history(self, client_id: str, *, days: int = 120) -> list[dict[str, Any]]:
        return []

    def create_campaign(self, **kw: Any) -> dict[str, Any]:
        row = {
            "id": f"cmp-{len(self.campaigns) + 1}", "status": "planning",
            "spent_usd": 0.0, **kw,
        }
        self.campaigns[str(row["id"])] = row
        return row

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return self.campaigns.get(campaign_id)

    def list_campaigns(self, *, client_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = list(self.campaigns.values())
        if client_id:
            rows = [r for r in rows if r.get("client_id") == client_id]
        return rows

    def campaign_properties(self, campaign_id: str) -> list[dict[str, Any]]:
        return [r for r in self.created_web2 if r.get("campaign_id") == campaign_id]

    def campaign_placements(self, campaign_id: str) -> list[dict[str, Any]]:
        return [
            {**r, "account_handle": "aios-house-devto", "account_ownership": "house"}
            for r in self.created_web2 if r.get("campaign_id") == campaign_id
        ]

    def client_placements(self, client_id: str | None = None, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.created_web2
        if client_id:
            rows = [r for r in rows if r.get("client_id") == client_id]
        return [{**r, "account_handle": "", "account_ownership": ""} for r in rows]

    def update_campaign(self, campaign_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        row = self.campaigns.get(campaign_id)
        if row is None:
            return None
        row.update(fields)
        return row

    def attach_property_to_campaign(self, web2_id: str, campaign_id: str, scheduled_for: Any) -> None:
        self.attached.append((web2_id, campaign_id))
        for row in self.created_web2:
            if str(row.get("id")) == web2_id:
                row["campaign_id"] = campaign_id
                row["scheduled_for"] = scheduled_for

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

    def client_name_for(self, client_id: str) -> str | None:
        return self.client_names.get(client_id)

    def create_web2(
        self, *, client_id: str, client_name: str, platform: str, anchor: str,
        target_url: str, topic: str, page_type: str, framework: str,
        source_pack: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": f"w2-{len(self.web2_by_id) + 1}", "client_id": client_id,
            "client_name": client_name, "platform": platform, "anchor": anchor,
            "target_url": target_url, "topic": topic, "page_type": page_type,
            "framework": framework, "source_pack": source_pack or {}, "status": "draft",
            "post_url": "", "verified": "pending", "published_at": None,
        }
        self.web2_by_id[row["id"]] = row
        self.created_web2.append(row)
        return row

    def get_web2(self, web2_id: str) -> dict[str, Any] | None:
        return self.web2_by_id.get(web2_id)

    def update_web2_status(
        self, web2_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self.web2_by_id.get(web2_id)
        if row is None:
            return None
        row.update(changes)
        return row


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


# --- web 2.0 publish endpoints (7B-3) -----------------------------------------


@pytest.fixture
def web2_enqueues(app: FastAPI) -> tuple[list[str], list[str]]:
    """Override the two Web 2.0 enqueuer deps with recorders (no Celery).

    Also stubs the similarity re-check to "clean". These tests exercise the ROUTER's
    contract, not the gate; the real re-check needs the privileged store and a corpus,
    and is covered directly in ``tests/test_web2_gate.py``. Stubbing it to ``""`` means
    a test that wants a gate verdict must say so explicitly (see ``web2_sim_code``),
    which keeps the gate's effect visible in the test that relies on it.
    """
    from app.routers.offpage import (
        get_web2_publish_enqueuer,
        get_web2_similarity_rechecker,
        get_web2_write_enqueuer,
    )

    writes: list[str] = []
    publishes: list[str] = []
    app.dependency_overrides[get_web2_write_enqueuer] = lambda: writes.append
    app.dependency_overrides[get_web2_publish_enqueuer] = lambda: publishes.append
    app.dependency_overrides[get_web2_similarity_rechecker] = lambda: (lambda _id: "")
    return writes, publishes


@pytest.fixture
def web2_sim_code(app: FastAPI) -> Callable[[str], None]:
    """Make the approval-time similarity re-check return a chosen code."""
    from app.routers.offpage import get_web2_similarity_rechecker

    def _set(code: str) -> None:
        app.dependency_overrides[get_web2_similarity_rechecker] = lambda: (lambda _id: code)

    return _set


def _plan_body(**over: Any) -> dict[str, Any]:
    # A BRAND anchor, not "roof repair" -> /roof-repair. The old fixture used the exact
    # money phrase, which R2-14 forbids outright; it passed only because this route ran
    # no anchor check. Leaving it would have re-encoded the defect in the fixture.
    body: dict[str, Any] = {
        "clientId": "cl-1", "platform": "WordPress.com", "anchor": "Acme Roofing",
        "targetUrl": "https://acme.example/roof-repair",
    }
    body.update(over)
    return body


async def test_the_single_property_route_refuses_an_exact_match_anchor(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """The campaign planner has always refused these; this route did not, and it spends
    the same money. An anchor that is exactly the phrase the destination ranks for has no
    editorial justification, and catching it at review means discarding a paid article
    instead of never writing it."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    writes, _ = web2_enqueues
    wire("manager", "u-lead")

    resp = await client.post(
        "/api/v1/offpage/web2/plan",
        json=_plan_body(anchor="roof repair", targetUrl="https://acme.example/roof-repair"),
    )

    assert resp.status_code == 422, resp.text
    assert repo.created_web2 == [], "nothing may be created"
    assert writes == [], "and nothing may be queued to spend on"


async def test_the_single_property_route_refuses_a_platform_with_no_account(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """Two doors into one table must enforce one set of rules. This route created a
    property against any platform at all - unconnected, or ineligible for the client -
    and the failure only surfaced at publish, after the drafting spend."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    repo.connected = set()  # no accounts anywhere
    writes, _ = web2_enqueues
    wire("manager", "u-lead")

    resp = await client.post("/api/v1/offpage/web2/plan", json=_plan_body())

    assert resp.status_code == 422, resp.text
    assert "no account is connected" in resp.text.lower()
    assert repo.created_web2 == []
    assert writes == []


async def test_web2_plan_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    wire("specialist")  # holds view_reports but is not a lead
    resp = await client.post("/api/v1/offpage/web2/plan", json=_plan_body())
    assert resp.status_code == 403


async def test_web2_plan_creates_draft_and_enqueues_write(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    writes, _publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/plan", json=_plan_body())
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == _WEB2_KEYS  # only the 7 contract keys; no client_id/status leak
    assert body["client"] == "Acme Roofing"
    assert body["platform"] == "WordPress.com"
    assert body["verified"] == "pending"
    assert repo.created_web2 and repo.created_web2[0]["status"] == "draft"
    assert writes == [repo.created_web2[0]["id"]]  # the write worker was enqueued


async def test_web2_plan_seeds_source_pack_from_proof(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    # First-hand proof supplied at plan time is seeded into the property's source_pack
    # so the write worker grounds the draft (no [NEEDS:] hold). Blanks are dropped.
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/plan", json=_plan_body(
        proofPoints=["Rebuilt 40 storm-damaged roofs in 2025", "  "],
        testimonials=["'They saved our home' - J. Doe"],
        uniqueData=["2025 study of 500 roofs: 30% needed only spot repair"],
        services=["Roof repair", "Roof replacement"],
    ))
    assert resp.status_code == 201
    pack = repo.created_web2[0]["source_pack"]
    assert pack["client_name"] == "Acme Roofing"
    assert pack["proof_points"] == ["Rebuilt 40 storm-damaged roofs in 2025"]  # blank dropped
    assert pack["testimonials"] == ["'They saved our home' - J. Doe"]
    assert pack["unique_data"] == ["2025 study of 500 roofs: 30% needed only spot repair"]
    assert pack["services"] == ["Roof repair", "Roof replacement"]


async def test_web2_plan_unknown_client_is_404(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    wire("manager", "u-lead")  # no client_names registered -> unknown
    resp = await client.post("/api/v1/offpage/web2/plan", json=_plan_body())
    assert resp.status_code == 404


async def test_web2_approve_transitions_to_publishing_and_enqueues(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.web2_by_id = {
        "w2-1": _web2_row(id="w2-1", client_id="cl-1", platform="Blogger", status="needs_review")
    }
    _writes, publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={"action": "approve"})
    assert resp.status_code == 200
    assert repo.web2_by_id["w2-1"]["status"] == "publishing"
    assert publishes == ["w2-1"]  # the publish worker was enqueued


# --- web 2.0 CAMPAIGNS ---------------------------------------------------------


def _campaign_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "clientId": "cl-1",
        "title": "Autumn push",
        "articleCount": 3,
        "topics": ["drain unblocking", "gutter cleaning", "cctv drain survey"],
        "platforms": ["Blogger", "WordPress.com"],
        "anchors": ["Leeds Drainage", "the team"],
        "targetUrl": "https://leedsdrainage.co.uk/drains",
        "pacing": "drip",
    }
    body.update(over)
    return body


async def test_the_estimate_prices_and_schedules_without_creating_anything(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """The screen where an operator sees the real cost and the real timeline BEFORE
    committing. Nothing may be queued and nothing spent."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    writes, _publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/campaigns/estimate", json=_campaign_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert data["estimatedCostUsd"] > 0
    # No completion DATE any more: an approved campaign publishes on approval, so there
    # is no future timeline to project. Asserting a date here would re-encode the drip.
    assert not data.get("projectedCompletion")
    assert len(data["properties"]) == 3
    # Nothing was created and no drafting was queued.
    assert repo.created_web2 == []
    assert repo.campaigns == {}
    assert writes == []


async def test_a_campaign_reusing_one_topic_is_refused_before_any_spend(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """Measured: one topic across N platforms produces N byte-identical articles. The
    refusal has to land here, not after N metered drafting runs."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    writes, _publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/campaigns",
        json=_campaign_body(articleCount=3, topics=["drain unblocking"]),
    )
    assert resp.status_code == 422
    # The app wraps errors in its own envelope ({"error": {...}}), not FastAPI's `detail`.
    assert "distinct topics" in resp.json()["error"]["message"]
    assert repo.created_web2 == []
    assert writes == []


async def test_creating_a_campaign_fans_out_properties_and_starts_drafting(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """ONE operator request becomes N properties, each on the existing pipeline."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    writes, publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    assert resp.status_code == 201
    data = resp.json()
    assert data["total"] == 3
    assert data["published"] == 0
    assert len(repo.created_web2) == 3
    assert len(writes) == 3  # every property queued for DRAFTING
    assert publishes == []  # and NOTHING queued to publish
    assert {t for _w, t in repo.attached} == {data["id"]}


async def test_each_campaign_property_gets_a_distinct_topic_and_no_schedule(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """Distinct topics (one article each, never one fanned out) and NO drip slot."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    topics = [r["topic"] for r in repo.created_web2]
    assert len(set(topics)) == 3
    assert not any(r.get("scheduled_for") for r in repo.created_web2), (
        "a scheduled property waits on a release tick that has no caller"
    )


async def test_approving_a_campaign_enqueues_a_publish_for_every_property(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """THE defect this guards: 1 of N properties published, N were paid for.

    The planner used to stamp a future ``scheduled_for`` on properties 2..N. Approve
    moved every property to ``publishing`` but only enqueued the ones not scheduled
    later, handing the rest to ``web2_release_due`` - a task with no caller in this
    deployment (celery beat is empty). So properties 2..N sat in ``publishing`` forever
    while the API reported the campaign ``scheduled`` and the ledger said "publishing
    now". Every one of them had already been drafted and charged for.
    """
    repo.client_names["cl-1"] = "Leeds Drainage"
    _writes, publishes = web2_enqueues
    wire("manager", "u-lead")

    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    rows = repo.campaign_properties(campaign_id)
    assert len(rows) == 3
    for row in rows:
        row["status"] = "needs_review"
    publishes.clear()

    resp = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve", json={"action": "approve"},
    )

    assert resp.status_code == 200, resp.text
    assert len(publishes) == 3, (
        f"every approved property must be enqueued to publish, got {len(publishes)} of 3"
    )
    assert {str(r["id"]) for r in rows} == set(publishes)


async def test_an_ineligible_platform_is_dropped_and_the_reason_is_reported(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """A selection quietly shrunk is a lie the operator discovers weeks later. dev.to is
    developer-scope, so a local-business client may not use it - and is told why."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/campaigns/estimate",
        json=_campaign_body(platforms=["Blogger", "dev.to"]),
    )
    assert resp.status_code == 200
    notes = " ".join(resp.json()["notes"])
    assert "dev.to" in notes
    assert "developer" in notes
    assert all(p["platform"] != "dev.to" for p in resp.json()["properties"])


async def test_campaign_creation_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("specialist", "u-staff")
    resp = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    assert resp.status_code == 403
    assert repo.created_web2 == []


async def test_an_unknown_client_is_404_not_an_empty_campaign(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    assert resp.status_code == 404


async def test_the_campaign_board_reports_degraded_when_not_everything_published(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """A campaign that claimed three and delivered two is DEGRADED, never completed -
    the same rule the content dispatcher enforces."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    rows = repo.campaign_properties(campaign_id)
    rows[0]["status"] = "published"
    rows[1]["status"] = "published"
    rows[2]["status"] = "failed"

    resp = await client.get(f"/api/v1/offpage/web2/campaigns/{campaign_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["published"] == 2


async def test_the_campaign_board_reports_completed_only_when_all_published(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    for row in repo.campaign_properties(campaign_id):
        row["status"] = "published"
    resp = await client.get(f"/api/v1/offpage/web2/campaigns/{campaign_id}")
    assert resp.json()["status"] == "completed"


async def test_the_platform_board_shows_every_row_with_a_reason(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """Nothing is hidden: the full catalogue is visible and the excluded rows carry the
    platform's own policy. That is what makes offering 50+ platforms honest."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("specialist", "u-staff")  # a read, so any staff may see it
    repo.connected = {"Blogger"}  # one real account; WordPress.com has none
    resp = await client.get("/api/v1/offpage/web2/platform-board?clientId=cl-1")
    assert resp.status_code == 200
    board = resp.json()
    assert len(board) == 3
    devto = next(r for r in board if r["name"] == "dev.to")
    assert devto["status"] == "not_eligible"
    assert "developer" in devto["reason"]
    assert next(r for r in board if r["name"] == "Blogger")["status"] == "eligible"


async def test_a_campaign_is_refused_for_a_platform_with_no_connected_account(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """No account, no campaign - and the refusal must arrive BEFORE any drafting spend.

    The planner previously passed the operator's own selection in as the connected set,
    which declared every requested platform connected by construction. A campaign could
    then be created, its properties drafted and PAID FOR, and only fail at publish time
    when no credential could be resolved. Refusing up front is the difference between a
    clear message and a bill for articles that can never go live.
    """
    repo.client_names["cl-1"] = "Leeds Drainage"
    repo.connected = set()  # no accounts anywhere
    wire("manager", "u-lead")

    resp = await client.post("/api/v1/offpage/web2/campaigns/estimate", json=_campaign_body())

    assert resp.status_code in (200, 422), resp.text
    body = resp.json()
    blob = json.dumps(body).lower()
    assert "no account is connected" in blob, (
        f"the operator must be told the account is missing, got: {blob[:400]}"
    )
    assert body.get("count", 0) == 0 or body.get("estimatedCostUsd", 0) == 0, (
        "nothing may be priced for a platform that cannot publish"
    )


async def test_the_platform_board_never_calls_a_platform_connected_without_an_account(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """A platform with NO account is ``not_connected``, never ``eligible``.

    Deriving the connected set from the catalogue makes every mapped platform look
    connected, so `not_connected` becomes unreachable and the operator is shown a green
    light for a platform the pipeline holds no credential for. The distinction is the
    whole point of the three-state board: a missing credential is a ten-minute fix, and
    it must be named as one.
    """
    repo.client_names["cl-1"] = "Leeds Drainage"
    repo.connected = set()  # a fresh workspace: nothing is connected
    wire("specialist", "u-staff")
    board = (await client.get("/api/v1/offpage/web2/platform-board?clientId=cl-1")).json()

    assert [r["status"] for r in board if r["name"] == "Blogger"] == ["not_connected"]
    assert not [r for r in board if r["status"] == "eligible"], (
        "no account exists, so nothing may report as eligible"
    )
    reason = next(r for r in board if r["name"] == "Blogger")["reason"]
    assert "no account is connected" in reason.lower()


async def test_web2_approve_refuses_when_the_similarity_gate_could_not_run(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]], web2_sim_code: Callable[[str], None],
) -> None:
    """FAIL-CLOSED at approval, the mirror of run_write's fail-open.

    A draft parks at review whether the gate passed or could not run, so drafting stays
    unblocked during an outage. This endpoint is the last step before the article goes
    LIVE under a client's name, and 'we could not check' is not 'it is fine' - approving
    on it publishes something that may duplicate another property.
    """
    repo.web2_by_id = {
        "w2-1": _web2_row(
            id="w2-1", client_id="cl-1", platform="Blogger", status="needs_review",
        )
    }
    web2_sim_code("sim_unavailable:error")
    _writes, publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={"action": "approve"})
    assert resp.status_code == 409
    assert repo.web2_by_id["w2-1"]["status"] == "needs_review"  # unchanged
    assert publishes == []  # nothing was queued to publish


async def test_web2_approve_needs_an_explicit_acknowledgement_after_a_warn(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]], web2_sim_code: Callable[[str], None],
) -> None:
    """A plain approve must NOT carry the acknowledgement. If it did, the gate would
    decay into a click-through and an operator would pass collisions by habit."""
    repo.web2_by_id = {
        "w2-1": _web2_row(
            id="w2-1", client_id="cl-1", platform="Blogger", status="needs_review",
        )
    }
    web2_sim_code("sim_warn:body_resemblance:client:w2-9")
    _writes, publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={"action": "approve"})
    assert resp.status_code == 409
    assert publishes == []

    ok = await client.post(
        "/api/v1/offpage/web2/w2-1/approve",
        json={"action": "approve", "acknowledgeSimilarity": True},
    )
    assert ok.status_code == 200
    assert repo.web2_by_id["w2-1"]["status"] == "publishing"
    assert publishes == ["w2-1"]


def _force_enforcement(monkeypatch: pytest.MonkeyPatch, *, enforce: bool) -> None:
    """Pin `web2_similarity_enforce` for one test, whatever the deployment default is."""
    from app.config import Settings, get_settings

    base = get_settings()
    patched = Settings(
        _env_file=None,
        **{**base.model_dump(), "web2_similarity_enforce": enforce},
    )
    monkeypatch.setattr("app.routers.offpage.get_settings", lambda: patched)


async def test_a_similarity_block_is_acknowledgeable_while_enforcement_is_off(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]], web2_sim_code: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warn-only posture, which is still reachable by config.

    This test used to rely on the GLOBAL default being False. That made it a test of the
    deployment's current setting rather than of the behaviour, so arming the gate broke
    it for the wrong reason. It now pins enforcement off for itself, and its armed
    counterpart below pins the other side.
    """
    _force_enforcement(monkeypatch, enforce=False)
    repo.web2_by_id = {
        "w2-1": _web2_row(
            id="w2-1", client_id="cl-1", platform="Blogger", status="needs_review",
        )
    }
    web2_sim_code("sim_block:heading_skeleton:client:w2-9")
    _writes, publishes = web2_enqueues
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/w2-1/approve",
        json={"action": "approve", "acknowledgeSimilarity": True},
    )
    assert resp.status_code == 200
    assert publishes == ["w2-1"]


async def test_an_armed_similarity_block_cannot_be_acknowledged_away(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]], web2_sim_code: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARMED 2026-08-30, once the golden set showed 0 false blocks in 96 distinct pairs.

    With enforcement on, a block is not a warning with a confirm button - the article is
    the same article, and the only honest fix is to redraft it. An acknowledgement that
    could wave this through would be the override that switches the gate off in practice.
    """
    _force_enforcement(monkeypatch, enforce=True)
    repo.web2_by_id = {
        "w2-1": _web2_row(
            id="w2-1", client_id="cl-1", platform="Blogger", status="needs_review",
        )
    }
    web2_sim_code("sim_block:heading_skeleton:client:w2-9")
    _writes, publishes = web2_enqueues
    wire("manager", "u-lead")

    resp = await client.post(
        "/api/v1/offpage/web2/w2-1/approve",
        json={"action": "approve", "acknowledgeSimilarity": True},
    )

    assert resp.status_code == 409, resp.text
    assert "cannot be approved" in resp.text
    assert publishes == [], "an armed block must not publish, acknowledged or not"


async def test_a_reject_never_needs_a_similarity_acknowledgement(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]], web2_sim_code: Callable[[str], None],
) -> None:
    """Rejecting a flagged draft is the SAFE action; gating it behind an extra field
    would push operators toward approving instead."""
    repo.web2_by_id = {
        "w2-1": _web2_row(
            id="w2-1", client_id="cl-1", platform="Blogger", status="needs_review",
        )
    }
    web2_sim_code("sim_block:body_sha256:client:w2-9")
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={"action": "reject"})
    assert resp.status_code == 200
    assert repo.web2_by_id["w2-1"]["status"] == "rejected"


async def test_web2_approve_reject_does_not_publish(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.web2_by_id = {"w2-1": _web2_row(id="w2-1", status="needs_review")}
    _writes, publishes = web2_enqueues
    wire("admin", "u-admin")
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={"action": "reject"})
    assert resp.status_code == 200
    assert repo.web2_by_id["w2-1"]["status"] == "rejected"
    assert publishes == []  # a rejected draft is never published


async def test_web2_approve_conflicts_when_not_needs_review(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.web2_by_id = {"w2-1": _web2_row(id="w2-1", status="draft")}
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={})
    assert resp.status_code == 409  # only a needs_review draft may be approved


async def test_web2_approve_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.web2_by_id = {"w2-1": _web2_row(id="w2-1", status="needs_review")}
    wire("analyst")  # not a lead
    resp = await client.post("/api/v1/offpage/web2/w2-1/approve", json={})
    assert resp.status_code == 403


async def test_web2_approve_missing_is_404(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/offpage/web2/nope/approve", json={})
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Campaign approval: ONE operator decision, still one transition per property.
#
# The distinction these tests defend: reviewing thirty drafts individually is the
# workflow the campaign layer exists to remove, but a BATCH write is not the answer -
# Tumblr's API License requires a per-post human action before an application posts on
# an account holder's behalf. So the route iterates and re-checks each row; what it must
# never become is a single UPDATE that waves thirty rows past the gate at once.
# --------------------------------------------------------------------------- #
async def test_one_approval_publishes_every_property_in_the_campaign(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    props = repo.campaign_properties(campaign_id)
    for row in props:
        row["status"] = "needs_review"
    repo.campaigns[campaign_id]["status"] = "needs_approval"

    resp = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve", json={"action": "approve"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] == len(props)
    assert body["held"] == []
    assert body["status"] == "scheduled"
    # Every property transitioned individually - none left behind at review.
    assert all(r["status"] == "publishing" for r in repo.campaign_properties(campaign_id))


async def test_a_property_the_gate_blocks_is_held_not_waved_through_with_the_batch(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
    web2_sim_code: Callable[[str], None],
) -> None:
    """The whole value of the gate is that a bulk action cannot bypass it. A blocked
    property stays at needs_review and is named in `held`, so the operator can redraft
    that one and approve the rest rather than being told 'something failed'."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    for row in repo.campaign_properties(campaign_id):
        row["status"] = "needs_review"
    repo.campaigns[campaign_id]["status"] = "needs_approval"
    web2_sim_code("sim_block:body_sha256:client:w2-other")

    resp = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve", json={"action": "approve"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] == 0
    assert len(body["held"]) == len(repo.campaign_properties(campaign_id))
    assert body["held"][0]["web2Id"]
    assert "sim_block" in body["held"][0]["reason"] or body["held"][0]["reason"]
    # A campaign with holds is NOT reported as scheduled - that would be the
    # partial-delivery-as-success defect.
    assert body["status"] == "needs_approval"
    assert all(r["status"] == "needs_review" for r in repo.campaign_properties(campaign_id))


async def test_rejecting_a_campaign_rejects_its_properties_and_publishes_nothing(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    for row in repo.campaign_properties(campaign_id):
        row["status"] = "needs_review"
    repo.campaigns[campaign_id]["status"] = "needs_approval"
    _, publishes = web2_enqueues

    resp = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve", json={"action": "reject"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert all(r["status"] == "rejected" for r in repo.campaign_properties(campaign_id))
    assert publishes == []


async def test_campaign_approval_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    repo.campaigns["cmp-x"] = {
        "id": "cmp-x", "status": "needs_approval", "client_id": "cl-1",
        "client_name": "Leeds Drainage", "article_count": 1, "platforms": [], "pacing": "drip",
    }
    wire("specialist", "u-staff")
    resp = await client.post(
        "/api/v1/offpage/web2/campaigns/cmp-x/approve", json={"action": "approve"}
    )
    assert resp.status_code == 403


async def test_approving_a_campaign_twice_is_a_409_not_a_second_publish(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    for row in repo.campaign_properties(campaign_id):
        row["status"] = "needs_review"
    repo.campaigns[campaign_id]["status"] = "needs_approval"
    first = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve", json={"action": "approve"}
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve", json={"action": "approve"}
    )
    assert second.status_code == 409


async def test_approving_an_unknown_campaign_is_404(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/campaigns/nope/approve", json={"action": "approve"}
    )
    assert resp.status_code == 404


async def test_a_campaign_level_acknowledgement_cannot_wave_a_collision_through(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
    web2_sim_code: Callable[[str], None],
) -> None:
    """One checkbox must not acknowledge every collision in a campaign sight-unseen.

    The named acknowledgement exists to stop the gate degrading into a click-through: an
    operator who must state they read THIS collision cannot approve past it by habit.
    A campaign-level acknowledgement would hand that guarantee back, so the campaign
    route hands the per-property guard a request carrying no acknowledgement at all -
    a collision is acknowledged on the property it belongs to, or not at all.
    """
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    for row in repo.campaign_properties(campaign_id):
        row["status"] = "needs_review"
    repo.campaigns[campaign_id]["status"] = "needs_approval"
    web2_sim_code("sim_block:body_sha256:client:w2-other")

    resp = await client.post(
        f"/api/v1/offpage/web2/campaigns/{campaign_id}/approve",
        json={"action": "approve", "acknowledgeSimilarity": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] == 0, "a campaign-level acknowledgement must not pass a block"
    assert len(body["held"]) == len(repo.campaign_properties(campaign_id))
    assert all(r["status"] == "needs_review" for r in repo.campaign_properties(campaign_id))


# --------------------------------------------------------------------------- #
# The placement report — the "where are my links?" answer.
#
# Every fact here was already stored on the row and none of it was reachable, so a
# finished campaign could not be shown to anyone. These pin the two things that make
# the report trustworthy: it carries the whole record, and it never claims a link is
# live when nobody has looked.
# --------------------------------------------------------------------------- #
async def test_the_placement_report_carries_the_whole_record(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]
    row = repo.campaign_properties(campaign_id)[0]
    row.update({"post_url": "https://x.example/p/1", "status": "published",
                "link_rel": "", "link_found": True, "target_url": "https://leeds.example/drains"})

    resp = await client.get(f"/api/v1/offpage/web2/campaigns/{campaign_id}/placements")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(repo.campaign_properties(campaign_id))
    live = next(p for p in body if p["postUrl"])
    # The facts an operator needs to answer a client, all present.
    assert live["topic"] and live["platform"] and live["anchor"]
    assert live["targetUrl"] == "https://leeds.example/drains"
    assert live["postUrl"] == "https://x.example/p/1"
    assert live["linkFound"] is True
    assert live["account"] == "aios-house-devto"
    assert live["accountOwnership"] == "house"
    # and the internal tenant id is still not on the wire
    assert "client_id" not in live and "clientId" not in live


async def test_an_unchecked_link_is_null_not_false(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """`null` (nobody looked) and `false` (we looked and it was gone) are different
    facts. Collapsing them would let a placement nobody has verified render with the
    same confidence as one that was measured — which is how an agency invoices for a
    link a platform quietly stripped."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    created = await client.post("/api/v1/offpage/web2/campaigns", json=_campaign_body())
    campaign_id = created.json()["id"]

    resp = await client.get(f"/api/v1/offpage/web2/campaigns/{campaign_id}/placements")
    assert all(p["linkFound"] is None for p in resp.json())

    repo.campaign_properties(campaign_id)[0]["link_found"] = False
    again = await client.get(f"/api/v1/offpage/web2/campaigns/{campaign_id}/placements")
    assert any(p["linkFound"] is False for p in again.json())


async def test_the_report_for_an_unknown_campaign_is_404(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    wire("manager", "u-lead")
    resp = await client.get("/api/v1/offpage/web2/campaigns/nope/placements")
    assert resp.status_code == 404


async def test_the_cross_campaign_ledger_includes_properties_with_no_campaign(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """A client's Web 2.0 history is not one campaign — the single-property builds that
    predate campaigns are part of the record and a campaign-scoped view would hide them."""
    repo.client_names["cl-1"] = "Leeds Drainage"
    wire("manager", "u-lead")
    repo.created_web2.append({
        "id": "w2-legacy", "client_id": "cl-1", "client_name": "Leeds Drainage",
        "platform": "Tumblr", "topic": "older one-off build", "anchor": "a",
        "status": "published", "post_url": "https://old.example/p", "verified": "verified",
        "campaign_id": None,
    })
    resp = await client.get("/api/v1/offpage/web2/placements?clientId=cl-1")
    assert resp.status_code == 200
    assert any(p["topic"] == "older one-off build" for p in resp.json())


async def test_the_placement_report_is_readable_by_any_staff_not_just_leads(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """Reporting is a read. A specialist assembling a client update must not need the
    lead permission that exists to gate SPENDING and PUBLISHING."""
    wire("specialist", "u-staff")
    resp = await client.get("/api/v1/offpage/web2/placements")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Registering an account from the portal (the board promised it; nothing did it)
# --------------------------------------------------------------------------- #
def _account_body(**over: Any) -> dict[str, Any]:
    body = {
        "platform": "Blogger", "ownership": "per_client", "clientId": "cl-1",
        "handle": "leedsdrainage", "email": "hello@leedsdrainage.example",
        "maxProperties": 5, "credential": {"oauth_token": "SECRET-TOKEN", "blog_id": "42"},
    }
    body.update(over)
    return body


async def test_registering_an_account_seals_the_credential_and_never_returns_it(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The board's empty state told the operator to "register it here" while no endpoint
    existed. It exists now - and the secret it seals must never come back out."""
    sealed: dict[str, Any] = {}

    def fake_insert(spec: Any) -> str:
        repo.accounts["acct-1"] = {
            "id": "acct-1", "platform": spec.platform, "ownership": spec.ownership,
            "client_id": spec.client_id, "handle": spec.handle,
            "registration_email": spec.registration_email, "property_url": "",
            "health": "unverified", "health_checked_at": None, "property_count": 0,
            "max_properties": spec.max_properties, "client_name": "Leeds Drainage",
            "vault_provider": "web2:Blogger", "vault_label": "acct-1",
        }
        return "acct-1"

    monkeypatch.setattr("app.cli.web2_accounts.insert_account", fake_insert)
    monkeypatch.setattr(
        "app.services.vault.add_key",
        lambda **kw: sealed.update(kw),
    )
    wire("manager", "u-lead")

    resp = await client.post("/api/v1/offpage/web2/accounts", json=_account_body())

    assert resp.status_code == 201, resp.text
    blob = resp.text
    assert "SECRET-TOKEN" not in blob, "the credential must never be returned"
    assert resp.json()["handle"] == "leedsdrainage"
    # It really was sealed, under the ACCOUNT id (what the publish worker reads).
    assert sealed.get("label") == "acct-1"
    assert "SECRET-TOKEN" in str(sealed.get("secret"))


async def test_a_footprint_handle_is_refused_with_the_rule_not_the_value(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """The endpoint calls the SAME `build_spec` the CLI calls, so R2-08 identity hygiene
    cannot drift between the two doors into the same table. And the refusal explains the
    rule without ever echoing the secret back."""
    wire("manager", "u-lead")

    resp = await client.post(
        "/api/v1/offpage/web2/accounts",
        json=_account_body(handle="blogger-a1b2c3d4e5"),  # platform slug + hex run
    )

    assert resp.status_code == 422, resp.text
    assert "SECRET-TOKEN" not in resp.text


# --------------------------------------------------------------------------- #
# The free anchor pre-check (QA 19)
# --------------------------------------------------------------------------- #
# `plan_web2` already refused an exact-match commercial anchor - but at submission,
# as a 422 the Single Property modal swallowed, so the operator was shown a queued
# property that did not exist. This lets the form ask BEFORE anything is created.


async def test_anchor_check_refuses_an_exact_match_commercial_anchor(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/anchor-check",
        json={
            "clientId": "cl-1", "anchor": "roof repair",
            "targetUrl": "https://acme.example/roof-repair",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is False
    assert body["reason"], "a refusal must say why"


async def test_anchor_check_allows_the_brand_on_the_same_url(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """The subtle half: a client called "Leeds Drain Unblocking" cannot be forbidden
    from using its own name, even though it contains the money words. The rule needs
    the client name from the DATABASE - which is exactly why this check is a server
    route and not a TypeScript copy that would drift from the write path."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/anchor-check",
        json={
            "clientId": "cl-1", "anchor": "Acme Roofing",
            "targetUrl": "https://acme.example/roof-repair",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed"] is True


async def test_anchor_check_creates_nothing_and_spends_nothing(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
    web2_enqueues: tuple[list[str], list[str]],
) -> None:
    """The whole point of asking first is that asking is free."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    writes, _ = web2_enqueues
    wire("manager", "u-lead")
    await client.post(
        "/api/v1/offpage/web2/anchor-check",
        json={"clientId": "cl-1", "anchor": "roof repair", "targetUrl": "https://a.example/x"},
    )
    assert repo.created_web2 == []
    assert writes == []


async def test_anchor_check_is_readable_by_a_specialist(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    """Deliberately NOT lead-only: asking whether a string is a good anchor is not a
    privileged act, and gating it behind the write role would stop a specialist
    drafting a brief."""
    repo.client_names = {"cl-1": "Acme Roofing"}
    wire("specialist", "u-spec")
    resp = await client.post(
        "/api/v1/offpage/web2/anchor-check",
        json={"clientId": "cl-1", "anchor": "the roofing team", "targetUrl": "https://a.example/x"},
    )
    assert resp.status_code == 200, resp.text


async def test_anchor_check_404s_on_an_unknown_client(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    repo.client_names = {}
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/offpage/web2/anchor-check",
        json={"clientId": "nope", "anchor": "x y", "targetUrl": "https://a.example/x"},
    )
    assert resp.status_code == 404
