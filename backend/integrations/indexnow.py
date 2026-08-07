"""IndexNow submission seam - the ONLY door to the IndexNow protocol.

IndexNow (https://www.indexnow.org) is a FREE, keyless-to-the-caller protocol: you
POST a small JSON body to ``https://api.indexnow.org/indexnow`` telling participating
search engines (Bing, Yandex, Seznam, ...) that a set of URLs on a host changed. The
body is ``{host, key, keyLocation, urlList}``. The ``key`` is a random per-DOMAIN token
you own, and a ``<key>.txt`` file carrying that same token MUST be hosted at the domain
root - that file is how the engine proves you control the domain. Hosting that file is
a MANUAL, one-time setup step per client domain (see ``docs`` / the module README); this
seam only mints the stable key + submits.

Two impls satisfy the async ``IndexNow`` Protocol, mirroring every other provider seam
(``firecrawl`` / ``resend``):

* ``IndexNowClient`` - real, over the SHARED async ``httpx.AsyncClient`` the app opens
  in its lifespan (async, like ``firecrawl``). It carries no API key of its own (the
  protocol has none); it is GATED on ``INDEXNOW_ENABLED`` at the factory. NON-RAISING:
  any transport / HTTP failure returns an ``IndexNowResult(ok=False, ...)`` - never an
  exception (the caller records the failure + moves on).
* ``FakeIndexNow`` - deterministic, offline: records every submission + returns a fixed
  ok/failed result, so the service + endpoint tests run with zero network.

THE PER-DOMAIN KEY (``indexnow_key_for_host``): derived DETERMINISTICALLY as
``sha256(salt : host)`` hex, so the key for a host is STABLE across restarts with no
storage table (the hosted ``<key>.txt`` stays valid forever) yet unguessable without
the salt. ``INDEXNOW_KEY_SALT`` seeds it; a blank salt falls back to a fixed dev salt so
tests are reproducible. ``key_location(host)`` is ``https://{host}/{key}.txt`` - the
file the operator must upload once.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

from app.logging_setup import get_logger

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.indexnow")

_ENDPOINT = "https://api.indexnow.org/indexnow"
_TIMEOUT = 15.0
# Fallback salt so a keyless dev/test deploy still mints a stable, deterministic key.
# Prod SHOULD set INDEXNOW_KEY_SALT so the key is not derivable from open-source code.
_DEFAULT_SALT = "aios-indexnow-default-salt"


def indexnow_key_for_host(host: str, *, salt: str = "") -> str:
    """The stable per-domain IndexNow key for ``host`` = ``sha256(salt : host)`` hex.

    Deterministic (no storage needed - the hosted ``<key>.txt`` never has to change)
    and unguessable without the salt. 64 hex chars, well within IndexNow's 8-128 range.
    """
    seed = f"{salt or _DEFAULT_SALT}:{host.strip().lower()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def key_location(host: str, key: str) -> str:
    """The URL where the ``<key>.txt`` verification file must be hosted (root of host)."""
    return f"https://{host.strip().lower()}/{key}.txt"


@dataclass(frozen=True)
class IndexNowResult:
    """The verdict of one IndexNow submission: ``ok`` + a short ``detail`` line.

    NON-RAISING by contract - a transport/HTTP failure comes back as
    ``ok=False`` with a sanitized detail, never an exception.
    """

    ok: bool
    detail: str = ""


@runtime_checkable
class IndexNow(Protocol):
    async def submit(
        self, http: httpx.AsyncClient, *, host: str, key: str, key_location: str, urls: list[str]
    ) -> IndexNowResult: ...


async def indexnow_submit(
    http: httpx.AsyncClient, *, host: str, key: str, key_location: str, urls: list[str]
) -> IndexNowResult:
    """POST the IndexNow body and return an :class:`IndexNowResult` (never raises).

    IndexNow treats 200/202 as accepted; a 4xx is a config/key problem (surfaced as
    ``ok=False`` with the status). The key rides in the JSON body (never a URL); nothing
    secret is logged - only the status.
    """
    body = {"host": host, "key": key, "keyLocation": key_location, "urlList": urls}
    try:
        resp = await http.post(_ENDPOINT, json=body, timeout=_TIMEOUT)
    except Exception:
        logger.info("indexnow_degraded", reason="transport_error", host=host)
        return IndexNowResult(ok=False, detail="transport error")
    if resp.status_code in (200, 202):
        return IndexNowResult(ok=True, detail=f"{resp.status_code} accepted")
    logger.info("indexnow_rejected", host=host, status=resp.status_code)
    return IndexNowResult(ok=False, detail=f"http {resp.status_code}")


class IndexNowClient:
    """Real async ``IndexNow`` over the shared ``httpx.AsyncClient``. Carries no key of
    its own (the protocol has none) - it is gated purely by the settings factory."""

    provider = "indexnow"

    async def submit(
        self, http: httpx.AsyncClient, *, host: str, key: str, key_location: str, urls: list[str]
    ) -> IndexNowResult:
        return await indexnow_submit(
            http, host=host, key=key, key_location=key_location, urls=urls
        )


@dataclass
class SubmittedBatch:
    """One captured IndexNow submission (FakeIndexNow), for test assertions."""

    host: str
    key: str
    key_location: str
    urls: list[str]


@dataclass
class FakeIndexNow:
    """Deterministic, offline ``IndexNow`` for the service + endpoint unit tests.

    Records every submission into ``submissions`` and returns ``result`` (default ok),
    so a test can prove the engine fired + with what, with zero network."""

    result: IndexNowResult = field(default_factory=lambda: IndexNowResult(ok=True, detail="202 accepted"))
    submissions: list[SubmittedBatch] = field(default_factory=list)

    async def submit(
        self, http: httpx.AsyncClient, *, host: str, key: str, key_location: str, urls: list[str]
    ) -> IndexNowResult:
        self.submissions.append(
            SubmittedBatch(host=host, key=key, key_location=key_location, urls=list(urls))
        )
        return self.result


def indexnow_from_settings(settings: Settings) -> IndexNow | None:
    """A real ``IndexNowClient`` when ``INDEXNOW_ENABLED`` is on, else ``None``.

    Degrades to ``None`` (never raises) when disabled - the indexing service then
    records the ``indexnow`` engine as ``skipped`` (not configured), never a crash.
    """
    if not settings.indexnow_enabled:
        logger.info("indexnow_degraded", reason="disabled")
        return None
    return IndexNowClient()
