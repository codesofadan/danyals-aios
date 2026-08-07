"""Indexing fan-out service: records per engine + degrades without keys.

NO DB, NO real network: the recorder store is in-memory, the IndexNow / Google seams
are the deterministic Fakes, and the sitemap ping runs against an ``httpx.MockTransport``
so ``GET /sitemap.xml`` is answered offline. Proves the whole contract:

* a fan-out records ONE row per (url, engine) attempt across all three engines;
* an UNCONFIGURED engine (client is ``None``) records ``skipped`` rows, never crashes;
* a provider FAILURE records ``error`` rows;
* the ``engines`` subset is honoured;
* a URL with no host is ``skipped``, never submitted.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.config import Settings
from app.modules.indexing.service import submit_urls
from integrations.google_indexing import FakeGoogleIndexing, GoogleIndexingResult
from integrations.indexnow import FakeIndexNow, IndexNowResult

pytestmark = pytest.mark.unit

_URLS = ["https://acme.example/a", "https://acme.example/b", "https://other.example/x"]


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev")


class FakeRecorder:
    """In-memory ``IndexRecorder``: every ``record`` is appended + echoed back so the
    service's tally + the caller see a real-shaped row (id/created_at synthesised)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(
        self, *, client_id: str | None, url: str, engine: str, status: str, detail: str
    ) -> dict[str, Any]:
        row = {
            "id": f"row-{len(self.rows)}",
            "client_id": client_id,
            "url": url,
            "engine": engine,
            "status": status,
            "detail": detail,
            "created_at": None,
        }
        self.rows.append(row)
        return row


def _sitemap_ok() -> httpx.AsyncClient:
    """A shared client whose ``GET`` (the sitemap ping) always answers 200, offline."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sitemap.xml"
        return httpx.Response(200, text="<urlset/>")

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _rows_for(rows: list[dict[str, Any]], engine: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["engine"] == engine]


async def test_full_fan_out_records_every_engine() -> None:
    store = FakeRecorder()
    indexnow = FakeIndexNow()
    google = FakeGoogleIndexing()
    async with _sitemap_ok() as http:
        summary = await submit_urls(
            store, http=http, indexnow=indexnow, google=google,
            settings=_settings(), urls=_URLS, client_id="cl-1",
        )

    # IndexNow: one row per URL (3), batched to ONE call per host (2 hosts).
    assert len(_rows_for(summary.rows, "indexnow")) == 3
    assert len(indexnow.submissions) == 2  # acme.example + other.example
    assert {s.host for s in indexnow.submissions} == {"acme.example", "other.example"}
    # Google: one publish + one row per URL (3).
    assert len(google.published) == 3
    assert len(_rows_for(summary.rows, "google")) == 3
    # Sitemap: one ping + one row per unique host (2).
    assert len(_rows_for(summary.rows, "sitemap")) == 2
    # Every row carried the client id, and all landed 'ok'.
    assert all(r["client_id"] == "cl-1" for r in summary.rows)
    assert summary.ok == len(summary.rows) == 8
    assert summary.skipped == 0 and summary.errors == 0


async def test_degrades_when_engines_unconfigured() -> None:
    """No IndexNow + no Google client -> those engines record 'skipped', never crash;
    the keyless sitemap ping still runs."""
    store = FakeRecorder()
    async with _sitemap_ok() as http:
        summary = await submit_urls(
            store, http=http, indexnow=None, google=None,
            settings=_settings(), urls=_URLS,
        )
    assert [r["status"] for r in _rows_for(summary.rows, "indexnow")] == ["skipped"] * 3
    assert [r["status"] for r in _rows_for(summary.rows, "google")] == ["skipped"] * 3
    assert all(r["detail"] == "not configured" for r in _rows_for(summary.rows, "indexnow"))
    # Sitemap is keyless -> still attempted + ok.
    assert [r["status"] for r in _rows_for(summary.rows, "sitemap")] == ["ok", "ok"]
    assert summary.skipped == 6 and summary.ok == 2 and summary.errors == 0


async def test_provider_failure_records_error() -> None:
    store = FakeRecorder()
    indexnow = FakeIndexNow(result=IndexNowResult(ok=False, detail="http 403"))
    google = FakeGoogleIndexing(result=GoogleIndexingResult(ok=False, detail="http 403"))
    async with _sitemap_ok() as http:
        summary = await submit_urls(
            store, http=http, indexnow=indexnow, google=google,
            settings=_settings(), urls=["https://acme.example/a"], engines=["indexnow", "google"],
        )
    assert [r["status"] for r in summary.rows] == ["error", "error"]
    assert summary.errors == 2 and summary.ok == 0


async def test_engines_subset_is_honoured() -> None:
    store = FakeRecorder()
    indexnow = FakeIndexNow()
    google = FakeGoogleIndexing()
    async with _sitemap_ok() as http:
        summary = await submit_urls(
            store, http=http, indexnow=indexnow, google=google,
            settings=_settings(), urls=["https://acme.example/a"], engines=["indexnow"],
        )
    assert {r["engine"] for r in summary.rows} == {"indexnow"}
    assert google.published == []  # google never fired


async def test_url_with_no_host_is_skipped_not_submitted() -> None:
    store = FakeRecorder()
    indexnow = FakeIndexNow()
    google = FakeGoogleIndexing()
    async with _sitemap_ok() as http:
        summary = await submit_urls(
            store, http=http, indexnow=indexnow, google=google,
            settings=_settings(), urls=["not-a-url"],
        )
    assert [r["status"] for r in summary.rows] == ["skipped"]
    assert summary.rows[0]["detail"] == "no host in url"
    assert indexnow.submissions == [] and google.published == []
