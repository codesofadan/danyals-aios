"""SERP-research seam (P7A-2): the ONLY door to keyword/SERP intelligence.

The content pipeline (later chunks) mines the live SERP for a topic - organic
competitors, People-Also-Ask questions, related searches - and a keyword's volume
+ difficulty, to ground the brief before drafting. That intelligence is reachable
exclusively through the ``SerpResearcher`` Protocol so a later chunk can wrap it in
a cost-gated wrapper; nothing else calls the provider directly.

Two impls satisfy the Protocol, mirroring the context seams exactly:

* ``SerperResearcher`` - real, backed by Serper.dev (Google SERP as JSON). Shares
  the sync ``HttpProviderClient`` (retry/backoff, never logs the key - auth is the
  ``X-API-KEY`` header). Key-gated on ``SERPER_API_KEY``; absent key ->
  ``ProviderNotConfiguredError`` naming the fix. Serper's ``/search`` has no true
  keyword-volume endpoint, so ``keyword_metrics`` derives a self-consistent
  order-of-magnitude estimate + a 0-100 difficulty from the result set (documented
  on the method); a later provider swap can supply planner-grade numbers.
* ``FakeSerpResearcher`` - deterministic, network-free: stable outputs derived from
  a sha256 of the keyword, so the same keyword always yields the same SERP + metrics
  and different keywords differ. Unit tests + degraded runs use it with zero keys.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

_INSTALL_HINT = "set SERPER_API_KEY (Serper.dev) to enable live SERP research"
_SERPER_BASE = "https://google.serper.dev"


@dataclass(frozen=True)
class OrganicResult:
    """One organic SERP listing: rank position, title, link, optional snippet."""

    position: int
    title: str
    link: str
    snippet: str | None = None


@dataclass(frozen=True)
class SerpResult:
    """A SERP snapshot for one keyword: the organic listings plus the two idea
    surfaces the brief mines (People-Also-Ask questions and related searches)."""

    keyword: str
    geo: str | None
    organic: list[OrganicResult] = field(default_factory=list)
    people_also_ask: list[str] = field(default_factory=list)
    related_searches: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KeywordMetrics:
    """A keyword's demand + competition: monthly ``volume`` and a 0-100
    ``difficulty`` (higher = harder to rank)."""

    keyword: str
    volume: int
    difficulty: float


@runtime_checkable
class SerpResearcher(Protocol):
    """Fetch a SERP snapshot for a keyword, and that keyword's demand metrics.

    ``geo`` is an optional country/locale hint (e.g. ``"us"``, ``"gb"``) that biases
    the organic results; ``None`` uses the provider's default locale.
    """

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult: ...
    def keyword_metrics(self, keyword: str) -> KeywordMetrics: ...


class SerperResearcher(HttpProviderClient):
    """Real ``SerpResearcher`` backed by Serper.dev; shares the sync HTTP base.

    The key rides in the ``X-API-KEY`` header (never a URL, never a log line).
    ``gl`` carries the geo/country when the caller passes one.
    """

    provider = "serper"

    def __init__(self, *, api_key: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Serper researcher unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_SERPER_BASE,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        body: dict[str, object] = {"q": keyword}
        if geo:
            body["gl"] = geo
        data = self.request_json("POST", "/search", json_body=body)
        organic = [
            OrganicResult(
                position=int(item.get("position") or index + 1),
                title=str(item.get("title") or ""),
                link=str(item.get("link") or ""),
                snippet=item.get("snippet"),
            )
            for index, item in enumerate(data.get("organic") or [])
        ]
        paa = [
            str(entry.get("question") or "")
            for entry in (data.get("peopleAlsoAsk") or [])
            if entry.get("question")
        ]
        related = [
            str(entry.get("query") or "")
            for entry in (data.get("relatedSearches") or [])
            if entry.get("query")
        ]
        return SerpResult(
            keyword=keyword,
            geo=geo,
            organic=organic,
            people_also_ask=paa,
            related_searches=related,
        )

    def keyword_metrics(self, keyword: str) -> KeywordMetrics:
        """Demand + competition for ``keyword``.

        Serper's ``/search`` exposes no keyword-planner volume, so this derives a
        self-consistent estimate from ``searchInformation.totalResults`` (indexed
        breadth): a log-scaled 0-100 ``difficulty`` and an order-of-magnitude
        ``volume`` proxy. A later provider swap can return planner-grade figures
        without changing this seam's shape.
        """
        data = self.request_json("POST", "/search", json_body={"q": keyword})
        info = data.get("searchInformation") or {}
        try:
            total = int(info.get("totalResults") or 0)
        except (TypeError, ValueError):
            total = 0
        return KeywordMetrics(
            keyword=keyword,
            volume=_volume_from_total(total),
            difficulty=_difficulty_from_total(total),
        )


def _difficulty_from_total(total_results: int) -> float:
    """Log-scale an indexed-result count into a 0-100 difficulty."""
    if total_results <= 1:
        return 0.0
    return round(min(100.0, math.log10(total_results) * 8.0), 1)


def _volume_from_total(total_results: int) -> int:
    """A crude order-of-magnitude monthly-volume proxy from indexed breadth."""
    if total_results <= 0:
        return 0
    return int(min(500_000, 10 ** (math.log10(max(total_results, 1)) / 2)))


class FakeSerpResearcher:
    """Deterministic, offline ``SerpResearcher`` - sha256(keyword) -> stable SERP.

    Same keyword => identical ``SerpResult`` + ``KeywordMetrics`` every run;
    different keywords differ. No network, so content-pipeline tests + degraded runs
    are reproducible with zero keys.
    """

    def __init__(self, *, base_url: str = "https://example.test") -> None:
        self._base_url = base_url.rstrip("/")

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        digest = self._digest(keyword)
        n_organic = 3 + int(digest[0:2], 16) % 5  # 3..7 listings
        organic = [
            OrganicResult(
                position=i + 1,
                title=f"{keyword.title()} - result {i + 1}",
                link=f"{self._base_url}/{digest[i * 4 : i * 4 + 8]}",
                snippet=f"A stable snippet about {keyword} (#{i + 1}).",
            )
            for i in range(n_organic)
        ]
        n_paa = 2 + int(digest[2:4], 16) % 3  # 2..4 questions
        paa = [f"What is {keyword} #{i + 1}?" for i in range(n_paa)]
        n_related = 2 + int(digest[4:6], 16) % 3  # 2..4 related
        suffixes = ("guide", "cost", "near me", "tips")[:n_related]
        related = [f"{keyword} {suffix}" for suffix in suffixes]
        return SerpResult(
            keyword=keyword,
            geo=geo,
            organic=organic,
            people_also_ask=paa,
            related_searches=related,
        )

    def keyword_metrics(self, keyword: str) -> KeywordMetrics:
        digest = self._digest(keyword)
        return KeywordMetrics(
            keyword=keyword,
            volume=int(digest[6:11], 16) % 50_000,  # 0..49_999, stable per keyword
            difficulty=float(int(digest[11:13], 16) % 101),  # 0..100
        )
