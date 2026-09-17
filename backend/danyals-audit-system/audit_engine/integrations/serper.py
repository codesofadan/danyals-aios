"""Serper.dev SERP API client.

Endpoint: https://google.serper.dev/search
Auth: X-API-KEY header.

Free tier: 2500 queries (lifetime sign-up bonus); paid tier ~$1/1000 queries at
scale. Graceful degrade if no key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

SERPER_BASE = "https://google.serper.dev"


@dataclass
class SERPResult:
    position: int
    title: str
    link: str
    snippet: str | None


@dataclass
class SERPResponse:
    keyword: str
    location: str | None
    organic: list[SERPResult] = field(default_factory=list)
    related_searches: list[str] = field(default_factory=list)
    people_also_ask: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    error: str | None = None


class SerperClient(BaseClient):
    provider_name = "serper"
    base_url = SERPER_BASE

    def __init__(self, *, api_key: str | None = None, timeout: float = 15.0) -> None:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-KEY"] = api_key
            self._enabled = True
        else:
            self._enabled = False
        super().__init__(timeout=timeout, max_retries=2, headers=headers)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def search(
        self,
        keyword: str,
        *,
        location: str | None = None,
        country: str = "us",
        language: str = "en",
        results: int = 10,
    ) -> SERPResponse:
        if not self._enabled:
            return SERPResponse(
                keyword=keyword,
                location=location,
                error="SERPER_API_KEY not set",
            )
        try:
            body: dict[str, Any] = {"q": keyword, "gl": country, "hl": language, "num": results}
            if location:
                body["location"] = location
            resp = await self.post("search", json_body=body)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.error("serper_search_failed", keyword=keyword, error=type(e).__name__)
            return SERPResponse(keyword=keyword, location=location, error=f"{type(e).__name__}: {e}")

        organic = [
            SERPResult(
                position=int(r.get("position") or i + 1),
                title=r.get("title") or "",
                link=r.get("link") or "",
                snippet=r.get("snippet"),
            )
            for i, r in enumerate(data.get("organic") or [])
        ]

        features: list[str] = []
        if "answerBox" in data:
            features.append("answerBox")
        if "knowledgeGraph" in data:
            features.append("knowledgeGraph")
        if "peopleAlsoAsk" in data:
            features.append("peopleAlsoAsk")
        if "relatedSearches" in data:
            features.append("relatedSearches")
        if "localResults" in data or "places" in data:
            features.append("local_pack")
        if data.get("ai_overview") or data.get("aiOverview"):
            features.append("ai_overview")

        return SERPResponse(
            keyword=keyword,
            location=location,
            organic=organic,
            related_searches=[r.get("query") or "" for r in (data.get("relatedSearches") or [])],
            people_also_ask=[q.get("question") or "" for q in (data.get("peopleAlsoAsk") or [])],
            features=features,
            raw=data,
        )

    async def rank_check(
        self,
        domain: str,
        keyword: str,
        *,
        location: str | None = None,
        results: int = 50,
    ) -> tuple[int | None, SERPResponse]:
        """Returns (position, full response). position=None if not in top `results`."""
        resp = await self.search(keyword, location=location, results=results)
        if resp.error:
            return (None, resp)
        domain_clean = domain.replace("https://", "").replace("http://", "").rstrip("/").lower()
        for r in resp.organic:
            host = r.link.replace("https://", "").replace("http://", "").split("/", 1)[0].lower()
            if host == domain_clean or host.endswith("." + domain_clean):
                return (r.position, resp)
        return (None, resp)
