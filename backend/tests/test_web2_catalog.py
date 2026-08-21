"""Unit tests for the Web 2.0 platform CATALOG (0062/0063 + the read surface).

Covers three things:
  * the response models' shape + ``from_row`` mapping (no DB);
  * the ``GET /offpage/web2/catalog`` endpoint with a faked repo (no DB, no network) -
    staff see the rollup, a portal client is 403'd, filters pass through;
  * the SEED itself (0063): exactly 50 real platforms with exactly the 17 that have a
    real Web2Publisher flagged ``automation_ready`` (== integrations.web2_publishers.
    WEB2_PLATFORMS), every auth_type/authority_tier/market a valid catalog value, and
    the 0062 table protected with ENABLE + FORCE RLS + the staff/lead policies.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.offpage_repo import get_offpage_repo
from app.schemas.offpage import Web2CatalogResponse, Web2PlatformCatalogResponse
from integrations.web2_publishers import (
    PLATFORM_BLUESKY,
    PLATFORM_CODEBERG_PAGES,
    PLATFORM_DISQUS,
    PLATFORM_DPASTE,
    PLATFORM_DRUPAL,
    PLATFORM_FC2,
    PLATFORM_FIGSHARE,
    PLATFORM_GITHUB_GIST,
    PLATFORM_GITLAB_SNIPPETS,
    PLATFORM_GRAVATAR,
    PLATFORM_HACKMD,
    PLATFORM_HUBSPOT,
    PLATFORM_INTERNET_ARCHIVE,
    PLATFORM_JOOMLA,
    PLATFORM_LEMMY,
    PLATFORM_LIVEDOOR,
    PLATFORM_MINDS,
    PLATFORM_MISSKEY,
    PLATFORM_NEOCITIES,
    PLATFORM_NETLIFY,
    PLATFORM_NOTION,
    PLATFORM_OSF,
    PLATFORM_PASTE_EE,
    PLATFORM_PASTEBIN,
    PLATFORM_PIXELFED,
    PLATFORM_PLURK,
    PLATFORM_RENTRY,
    PLATFORM_SEESAA,
    PLATFORM_SOURCEHUT_PAGES,
    PLATFORM_WARPCAST,
    PLATFORM_WEBFLOW,
    PLATFORM_WHITEWIND,
    PLATFORM_ZENODO,
    WEB2_PLATFORMS,
)

# Every platform whose automation_ready=true flip lives OUTSIDE the frozen 0063 seed
# (0068's 4 newest CMS/site-builder adapters, 0070's 19-platform third pass, and
# 0072's 10-platform fourth pass).
_POST_SEED_READY_PLATFORMS = frozenset(
    {
        PLATFORM_WEBFLOW, PLATFORM_HUBSPOT, PLATFORM_DRUPAL, PLATFORM_JOOMLA,
        PLATFORM_HACKMD, PLATFORM_GITHUB_GIST, PLATFORM_GITLAB_SNIPPETS, PLATFORM_PASTE_EE,
        PLATFORM_PASTEBIN, PLATFORM_NETLIFY, PLATFORM_NEOCITIES, PLATFORM_RENTRY,
        PLATFORM_DPASTE, PLATFORM_MISSKEY, PLATFORM_LEMMY, PLATFORM_BLUESKY,
        PLATFORM_WHITEWIND, PLATFORM_DISQUS, PLATFORM_PLURK, PLATFORM_PIXELFED,
        PLATFORM_NOTION, PLATFORM_GRAVATAR, PLATFORM_MINDS,
        PLATFORM_ZENODO, PLATFORM_INTERNET_ARCHIVE, PLATFORM_OSF, PLATFORM_FIGSHARE,
        PLATFORM_CODEBERG_PAGES, PLATFORM_LIVEDOOR, PLATFORM_FC2, PLATFORM_SEESAA,
        PLATFORM_WARPCAST, PLATFORM_SOURCEHUT_PAGES,
    }
)

pytestmark = pytest.mark.unit

_CATALOG_ITEM_KEYS = {
    "id", "name", "homepageUrl", "signupUrl", "publishMethod", "authType",
    "authorityTier", "market", "automationReady", "notes",
}
_CATALOG_KEYS = {"total", "automationReady", "byAuthType", "platforms"}

_VALID_AUTH_TYPES = {"api", "oauth", "automation", "anonymous"}
_VALID_TIERS = {"high", "medium", "low"}
_VALID_MARKETS = {"global", "us", "uk", "ca", "au", "jp"}

# Repo root: backend/tests/ -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = _REPO_ROOT / "db" / "migrations"
_SEED = _MIGRATIONS / "0063_web2_platforms_seed.sql"
_TABLE = _MIGRATIONS / "0062_web2_platforms.sql"


def _emitted(model: type[Any]) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --- schema shape / from_row --------------------------------------------------


def test_catalog_models_emit_exactly_the_contract_keys() -> None:
    assert _emitted(Web2PlatformCatalogResponse) == _CATALOG_ITEM_KEYS
    assert _emitted(Web2CatalogResponse) == _CATALOG_KEYS


def _platform_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "w2-uuid",
        "name": "WordPress.com",
        "homepage_url": "wordpress.com",
        "signup_url": "wordpress.com/start",
        "publish_url_or_method": "api:public-api.wordpress.com/rest/v1.1 (OAuth2)",
        "auth_type": "oauth",
        "authority_tier": "high",
        "market": "global",
        "automation_ready": True,
        "notes": "Real WordPressComClient.",
    }
    row.update(over)
    return row


def test_from_row_maps_and_aliases() -> None:
    dumped = Web2PlatformCatalogResponse.from_row(_platform_row()).model_dump(by_alias=True)
    assert set(dumped) == _CATALOG_ITEM_KEYS
    assert dumped["homepageUrl"] == "wordpress.com"
    assert dumped["publishMethod"].startswith("api:")
    assert dumped["authType"] == "oauth"
    assert dumped["automationReady"] is True


def test_from_row_unknown_enum_values_fall_back() -> None:
    item = Web2PlatformCatalogResponse.from_row(
        _platform_row(auth_type="bogus", authority_tier="huge", market=None)
    )
    assert item.auth_type == "automation"  # unknown -> the safe default
    assert item.authority_tier == "medium"
    assert item.market == "global"


# --- endpoint (faked repo) ----------------------------------------------------


class FakeCatalogRepo:
    """Minimal fake: the catalog route only calls ``list_web2_platforms``."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.kwargs: dict[str, Any] | None = None

    def list_web2_platforms(
        self,
        *,
        auth_type: str | None = None,
        authority_tier: str | None = None,
        automation_ready: bool | None = None,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        self.kwargs = {
            "auth_type": auth_type,
            "authority_tier": authority_tier,
            "automation_ready": automation_ready,
            "market": market,
        }
        return self._rows


def _fifty_rows() -> list[dict[str, Any]]:
    """17 automation_ready + 33 not = 50, with a known auth_type spread."""
    rows: list[dict[str, Any]] = []
    for i in range(17):
        rows.append(
            _platform_row(
                id=f"ready-{i}",
                name=f"Ready{i}",
                auth_type="oauth" if i < 5 else "api",
                automation_ready=True,
            )
        )
    for i in range(33):
        rows.append(
            _platform_row(
                id=f"target-{i}",
                name=f"Target{i}",
                auth_type="automation",
                authority_tier="medium",
                automation_ready=False,
            )
        )
    return rows


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeCatalogRepo:
    return FakeCatalogRepo(_fifty_rows())


@pytest.fixture
def wire(app: FastAPI, repo: FakeCatalogRepo) -> Callable[..., None]:
    app.dependency_overrides[get_offpage_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_catalog_returns_fifty_with_seventeen_automation_ready(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/offpage/web2/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _CATALOG_KEYS
    assert body["total"] == 50
    assert body["automationReady"] == 17
    # Rollup is exact over the returned rows: 5 oauth + 12 api (ready) + 33 automation.
    assert body["byAuthType"] == {"oauth": 5, "api": 12, "automation": 33}
    assert len(body["platforms"]) == 50
    assert set(body["platforms"][0]) == _CATALOG_ITEM_KEYS
    # Every row carries a valid, honest classification.
    assert all(p["authType"] in _VALID_AUTH_TYPES for p in body["platforms"])


async def test_catalog_forbidden_for_portal_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    resp = await client.get("/api/v1/offpage/web2/catalog")
    assert resp.status_code == 403


async def test_catalog_filters_pass_through_to_repo(
    client: httpx.AsyncClient, repo: FakeCatalogRepo, wire: Callable[..., None]
) -> None:
    wire("analyst")
    resp = await client.get(
        "/api/v1/offpage/web2/catalog",
        params={"authType": "oauth", "authorityTier": "high", "automationReady": "true"},
    )
    assert resp.status_code == 200
    assert repo.kwargs == {
        "auth_type": "oauth",
        "authority_tier": "high",
        "automation_ready": True,
        "market": None,
    }


async def test_catalog_rejects_bad_auth_type(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/offpage/web2/catalog", params={"authType": "bogus"})
    assert resp.status_code == 422  # not a Web2AuthType


# --- the SEED (0063) + table (0062) -------------------------------------------


def _seed_rows() -> list[tuple[str, str, str, str, bool]]:
    """Parse (name, auth_type, authority_tier, market, automation_ready) from 0063.

    Each row is one line; the three consecutive pure-lowercase quoted tokens
    immediately before the unquoted boolean are auth_type/authority_tier/market, and
    the boolean is automation_ready (the only unquoted true/false literal per row)."""
    text = _SEED.read_text(encoding="utf-8")
    body = text.split("values", 1)[1]
    rows: list[tuple[str, str, str, str, bool]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("('"):
            continue
        name = re.match(r"\('([^']+)'", line)
        cls = re.search(r"'([a-z]+)',\s*'([a-z]+)',\s*'([a-z]+)',\s*(true|false),\s*'", line)
        assert name is not None and cls is not None, f"unparsed seed row: {line[:60]}"
        rows.append((name.group(1), cls.group(1), cls.group(2), cls.group(3), cls.group(4) == "true"))
    return rows


def test_seed_has_exactly_fifty_unique_platforms() -> None:
    rows = _seed_rows()
    assert len(rows) == 50
    names = [r[0] for r in rows]
    assert len(set(names)) == 50  # `name` is UNIQUE in 0062


def test_seed_flags_exactly_the_seventeen_real_publishers() -> None:
    rows = _seed_rows()
    ready = {name for name, _at, _t, _m, is_ready in rows if is_ready}
    assert len(ready) == 17
    # 0063 is FROZEN history (applied, never edited) at the original 17 automation_ready
    # platforms. WEB2_PLATFORMS has since grown to 40 - the 4 newest (Webflow/HubSpot
    # CMS/Drupal/Joomla, 0068) plus the 19-platform third pass (0070) all live in later
    # catalog upserts instead, so exclude every one of them here.
    assert ready == set(WEB2_PLATFORMS) - _POST_SEED_READY_PLATFORMS


def test_seed_classifications_are_all_valid() -> None:
    rows = _seed_rows()
    for name, auth_type, tier, market, _ready in rows:
        assert auth_type in _VALID_AUTH_TYPES, f"{name}: bad auth_type {auth_type}"
        assert tier in _VALID_TIERS, f"{name}: bad authority_tier {tier}"
        assert market in _VALID_MARKETS, f"{name}: bad market {market}"


def test_table_migration_has_force_rls_and_policies() -> None:
    sql = _TABLE.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.web2_platforms" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql  # the load-bearing coverage-gate line
    assert "create type public.web2_auth_type as enum" in sql
    # staff read; leads (owner/admin/manager) maintain - mirrors public.directories.
    assert "web2_platforms_select" in sql and "is_staff()" in sql
    assert "web2_platforms_insert" in sql and "web2_platforms_update" in sql
    assert "unique (name)" in sql  # catalog name is the natural key


def test_0068_migration_grows_the_enum_and_flips_the_new_adapters_ready() -> None:
    matches = list(_MIGRATIONS.glob("00[6-9]*_web2_platforms_new_adapters.sql"))
    assert len(matches) == 1, "expected exactly one 006x-009x web2_platforms_new_adapters migration"
    sql = matches[0].read_text(encoding="utf-8").lower()
    for name in ("webflow", "hubspot cms", "drupal", "joomla"):
        assert f"alter type public.web2_platform add value if not exists '{name}'" in sql
    assert "automation_ready" in sql
    assert "on conflict (name) do update" in sql


def test_batch3_migration_grows_the_enum_and_flips_the_third_pass_ready() -> None:
    matches = list(_MIGRATIONS.glob("0[0-9][0-9][0-9]_web2_platforms_batch3.sql"))
    assert len(matches) == 1, "expected exactly one web2_platforms_batch3 migration"
    sql = matches[0].read_text(encoding="utf-8").lower()
    for name in (
        "hackmd", "github gist", "gitlab snippets", "paste.ee", "pastebin.com",
        "netlify", "neocities", "rentry.co", "dpaste.org", "misskey", "lemmy",
        "bluesky", "whitewind", "disqus", "plurk", "pixelfed", "notion", "gravatar", "minds",
    ):
        assert f"alter type public.web2_platform add value if not exists '{name}'" in sql
    assert "automation_ready" in sql
    assert "on conflict (name) do update" in sql


def test_batch4_migration_grows_the_enum_and_adds_the_fourth_pass() -> None:
    matches = list(_MIGRATIONS.glob("0[0-9][0-9][0-9]_web2_platforms_batch4.sql"))
    assert len(matches) == 1, "expected exactly one web2_platforms_batch4 migration"
    sql = matches[0].read_text(encoding="utf-8").lower()
    for name in (
        "zenodo", "internet archive", "osf", "figshare", "codeberg pages",
        "livedoor blog", "fc2 blog", "seesaa blog", "warpcast", "sourcehut pages",
    ):
        assert f"alter type public.web2_platform add value if not exists '{name}'" in sql
    assert "automation_ready" in sql
    assert "on conflict (name) do update" in sql
    # The deliberately-skipped platforms are documented, not silently dropped.
    for skipped in ("codesandbox", "gitbook", "read the docs", "hive", "steemit"):
        assert skipped in sql
