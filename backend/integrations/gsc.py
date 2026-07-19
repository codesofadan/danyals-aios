"""Google Search Console read seam (7C): the ONLY door to a client's GSC data.

Reachable exclusively through the ``SearchConsoleProvider`` Protocol, mirroring
``CitationProvider``/``Web2Publisher``. ``SearchConsoleClient`` is real, backed by
the Search Console API (``webmasters/v3``) over a per-client OAuth2 bearer token
(never read here - the caller/service layer decrypts it from the vault and passes
it in). ``FakeSearchConsoleClient`` is the deterministic offline stand-in for
tests/degraded runs, mirroring ``FakeCitationProvider``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

_INSTALL_HINT = "pass a per-client OAuth bearer token (from the vault) to read Search Console"
_GSC_BASE = "https://www.googleapis.com/webmasters/v3"


@dataclass(frozen=True)
class SearchQuery:
    """One query row from the top-queries breakdown."""

    query: str
    clicks: int
    impressions: int


@dataclass(frozen=True)
class SearchConsoleSummary:
    """A trailing-window Search Console snapshot for one site: the aggregate
    totals + a top-10 query breakdown."""

    clicks: int
    impressions: int
    ctr: float
    avg_position: float
    top_queries: list[SearchQuery] = field(default_factory=list)


@runtime_checkable
class SearchConsoleProvider(Protocol):
    def fetch_summary(self, site_url: str, *, days: int = 28) -> SearchConsoleSummary: ...


class SearchConsoleClient(HttpProviderClient):
    """Real ``SearchConsoleProvider`` over the Search Console API v3.

    Two calls per fetch: an AGGREGATE query (no ``dimensions``) for the site-wide
    totals + average position, and a ``query``-dimensioned one for the top-10
    breakdown - Search Console does not return both shapes from one call.
    """

    provider = "search_console"

    def __init__(self, *, access_token: str, timeout: float = 20.0) -> None:
        if not access_token:
            raise ProviderNotConfiguredError(f"Search Console unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_GSC_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )

    def fetch_summary(self, site_url: str, *, days: int = 28) -> SearchConsoleSummary:
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days)
        window: dict[str, Any] = {"startDate": start.isoformat(), "endDate": end.isoformat()}
        endpoint = f"/sites/{quote(site_url, safe='')}/searchAnalytics/query"

        totals = self.request_json("POST", endpoint, json_body=dict(window, rowLimit=1))
        agg = ((totals.get("rows") or [{}]) or [{}])[0]
        clicks = int(agg.get("clicks", 0))
        impressions = int(agg.get("impressions", 0))
        ctr = float(agg.get("ctr", 0.0))
        avg_position = float(agg.get("position", 0.0))

        by_query = self.request_json(
            "POST", endpoint, json_body=dict(window, dimensions=["query"], rowLimit=10)
        )
        queries = [
            SearchQuery(
                query=str((row.get("keys") or [""])[0]),
                clicks=int(row.get("clicks", 0)),
                impressions=int(row.get("impressions", 0)),
            )
            for row in (by_query.get("rows") or [])
            if isinstance(row, dict)
        ]
        return SearchConsoleSummary(
            clicks=clicks, impressions=impressions, ctr=ctr,
            avg_position=avg_position, top_queries=queries,
        )


class FakeSearchConsoleClient:
    """Deterministic offline ``SearchConsoleProvider`` - sha256(site_url) -> stable
    clicks/impressions/ctr/position + a fixed top-query list, so tests + degraded
    runs are reproducible with zero keys."""

    def fetch_summary(self, site_url: str, *, days: int = 28) -> SearchConsoleSummary:
        digest = hashlib.sha256(site_url.encode()).hexdigest()
        clicks = int(digest[:4], 16) % 5000
        impressions = clicks * 12 + 100
        ctr = round(clicks / impressions, 4) if impressions else 0.0
        avg_position = round((int(digest[4:6], 16) % 30) + 1.0, 1)
        queries = [
            SearchQuery(
                query=f"query {i + 1}",
                clicks=max(clicks // (i + 2), 1),
                impressions=max(impressions // (i + 2), 1),
            )
            for i in range(3)
        ]
        return SearchConsoleSummary(
            clicks=clicks, impressions=impressions, ctr=ctr,
            avg_position=avg_position, top_queries=queries,
        )


def search_console_client_from_token(access_token: str) -> SearchConsoleProvider:
    """The real client for a decrypted per-client access token (never settings-
    gated here - the caller/service layer already resolved the vault-sealed
    refresh token and exchanged it for this short-lived access token)."""
    return SearchConsoleClient(access_token=access_token)
