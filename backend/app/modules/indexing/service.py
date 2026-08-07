"""Indexing fan-out service - the pure core the endpoint + the publish worker share.

:func:`submit_urls` takes already-resolved seams (an ``IndexNow`` client or ``None``, a
``GoogleIndexing`` client or ``None``, a shared ``httpx.AsyncClient``, a recorder store)
and fans a set of URLs out across the requested engines, appending ONE
``index_submissions`` row per attempt and returning the recorded rows + a tally. It is
fully unit-testable with fakes: no DB, no network, no broker.

DEGRADE-NOT-CRASH is the whole contract:

* an unconfigured engine (client is ``None``) records a ``skipped`` row ("not
  configured") - never an error, never an exception.
* a provider that fails (transport/HTTP) comes back as ``ok=False`` from the seam (the
  seams are non-raising) and records an ``error`` row.
* a bad URL / no host records a ``skipped`` row and is otherwise ignored.

Engines fired, in order: IndexNow (batched per host), Google Indexing (per URL),
sitemap ping (best-effort GET per unique host). Grouping keeps IndexNow to one call per
host (its ``urlList`` is a batch) and the sitemap ping to one GET per host.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

import httpx

from app.logging_setup import get_logger
from integrations.indexnow import indexnow_key_for_host, key_location

if TYPE_CHECKING:
    from app.config import Settings
    from integrations.google_indexing import GoogleIndexing
    from integrations.indexnow import IndexNow

logger = get_logger("modules.indexing.service")

# The default engine set when the caller names none: attempt all three (each degrades
# on its own if unconfigured).
DEFAULT_ENGINES: tuple[str, ...] = ("indexnow", "google", "sitemap")
_SITEMAP_TIMEOUT = 15.0


class IndexRecorder(Protocol):
    """The append surface :func:`submit_urls` writes each attempt through (the real
    ``ServiceIndexingStore`` or an in-memory fake in tests)."""

    def record(
        self, *, client_id: str | None, url: str, engine: str, status: str, detail: str
    ) -> dict[str, Any]: ...


@dataclass
class FanOutSummary:
    """The rows recorded by one fan-out + a small tally."""

    rows: list[dict[str, Any]]
    ok: int
    skipped: int
    errors: int


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").strip().lower()
    except ValueError:
        return ""


def _group_by_host(urls: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        host = _host_of(url)
        if host:
            grouped[host].append(url)
    return grouped


async def submit_urls(
    store: IndexRecorder,
    *,
    http: httpx.AsyncClient,
    indexnow: IndexNow | None,
    google: GoogleIndexing | None,
    settings: Settings,
    urls: list[str],
    engines: list[str] | None = None,
    client_id: str | None = None,
) -> FanOutSummary:
    """Fan ``urls`` out across ``engines`` (default: all three), recording one row per
    attempt. Never raises: the seams are non-raising and any URL/host problem records a
    ``skipped`` row. Returns the recorded rows + a tally."""
    wanted = list(engines) if engines else list(DEFAULT_ENGINES)
    by_host = _group_by_host(urls)
    rows: list[dict[str, Any]] = []

    async def _rec(url: str, engine: str, status: str, detail: str) -> None:
        # psycopg is sync; offload the insert so an async caller never blocks the loop
        # (invariant #2). A sync worker path runs the same thread hop harmlessly.
        row = await asyncio.to_thread(
            store.record, client_id=client_id, url=url, engine=engine, status=status, detail=detail
        )
        rows.append(row)

    # A URL with no resolvable host cannot be submitted to any engine - record it once.
    for url in urls:
        if not _host_of(url):
            await _rec(url, "sitemap", "skipped", "no host in url")

    if "indexnow" in wanted:
        await _fan_indexnow(http, indexnow, settings, by_host, _rec)
    if "google" in wanted:
        await _fan_google(http, google, urls, _rec)
    if "sitemap" in wanted:
        await _fan_sitemap(http, by_host, _rec)

    ok = sum(1 for r in rows if r.get("status") == "ok")
    skipped = sum(1 for r in rows if r.get("status") == "skipped")
    errors = sum(1 for r in rows if r.get("status") == "error")
    return FanOutSummary(rows=rows, ok=ok, skipped=skipped, errors=errors)


_Rec = Callable[[str, str, str, str], Awaitable[None]]


async def _fan_indexnow(
    http: httpx.AsyncClient,
    indexnow: IndexNow | None,
    settings: Settings,
    by_host: dict[str, list[str]],
    rec: _Rec,
) -> None:
    if indexnow is None:
        for host_urls in by_host.values():
            for url in host_urls:
                await rec(url, "indexnow", "skipped", "not configured")
        return
    salt = settings.indexnow_key_salt.get_secret_value() if settings.indexnow_key_salt else ""
    for host, host_urls in by_host.items():
        key = indexnow_key_for_host(host, salt=salt)
        result = await indexnow.submit(
            http, host=host, key=key, key_location=key_location(host, key), urls=host_urls
        )
        status = "ok" if result.ok else "error"
        for url in host_urls:  # record per URL for a per-page audit trail
            await rec(url, "indexnow", status, result.detail)


async def _fan_google(
    http: httpx.AsyncClient, google: GoogleIndexing | None, urls: list[str], rec: _Rec
) -> None:
    if google is None:
        for url in urls:
            if _host_of(url):
                await rec(url, "google", "skipped", "not configured")
        return
    for url in urls:
        if not _host_of(url):
            continue
        result = await google.publish(http, url=url)
        await rec(url, "google", "ok" if result.ok else "error", result.detail)


async def _fan_sitemap(http: httpx.AsyncClient, by_host: dict[str, list[str]], rec: _Rec) -> None:
    """Best-effort sitemap ping: GET ``https://{host}/sitemap.xml`` once per host."""
    for host in by_host:
        sitemap_url = f"https://{host}/sitemap.xml"
        try:
            resp = await http.get(sitemap_url, timeout=_SITEMAP_TIMEOUT, follow_redirects=True)
        except Exception:
            logger.info("sitemap_ping_degraded", host=host, reason="transport_error")
            await rec(sitemap_url, "sitemap", "error", "transport error")
            continue
        if resp.status_code == 200:
            await rec(sitemap_url, "sitemap", "ok", "200 ok")
        else:
            await rec(sitemap_url, "sitemap", "error", f"http {resp.status_code}")
