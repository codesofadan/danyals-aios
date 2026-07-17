"""Keyword-data seam (Part 8): the ONLY door to keyword volume / difficulty / CPC /
competition + provider-side intent.

Unlike the rest of the SEO surface (which mines the live SERP through Serper), a
keyword's PLANNER-GRADE demand + competition numbers are not something Serper's
``/search`` can supply, so the keyword-research + competitor-intel modules use
DataForSEO's Labs keyword endpoints. This is the DELIBERATE provider exception; it
is reachable exclusively through the ``KeywordDataProvider`` Protocol so the module
service can wrap it in the cost gate and swap it for a deterministic fake in tests.

Two impls satisfy the Protocol, mirroring the offpage/context seams:

* ``DataForSeoProvider`` - real, backed by DataForSEO Labs (HTTP Basic login +
  password, handed to httpx per request and NEVER logged). Key-gated: an empty
  login/password -> ``ProviderNotConfiguredError`` naming the fix.
* ``FakeKeywordDataProvider`` - deterministic, network-free: every field is derived
  from a sha256 of the keyword, so the same keyword always yields the same metrics
  and different keywords differ. Unit tests + a keyless deploy use it with zero keys.

``keyword_data_provider_from_settings`` returns the REAL provider when the
credential pair is present, else the FAKE (so the module works offline / keyless
with plausible deterministic data - it degrades to a fake, never to ``None``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.keyword_data")

_INSTALL_HINT = (
    "set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD to enable live keyword metrics "
    "(volume / difficulty / CPC); without them the deterministic fake is used"
)
_DFS_BASE = "https://api.dataforseo.com"

# The five capitalised search-intent display labels (= the DB search_intent enum =
# the exact cell the tool workspace renders). The provider maps its own signal to
# one of these; the service falls back to the content engine's classifier.
INTENT_LABELS: tuple[str, ...] = (
    "Informational",
    "Commercial",
    "Transactional",
    "Navigational",
    "Local",
)


@dataclass(frozen=True)
class KeywordMetric:
    """One keyword's demand + competition from any source.

    ``volume`` is the monthly search volume; ``difficulty`` is a 0-100 ranking
    difficulty (higher = harder); ``cpc`` is the average cost-per-click (USD);
    ``competition`` is a 0-1 paid-competition index. ``low_confidence`` marks a pull
    the provider itself flagged as thin (drives ``metrics_confidence='low'``).
    """

    keyword: str
    volume: int = 0
    difficulty: float = 0.0
    cpc: float = 0.0
    competition: float = 0.0
    low_confidence: bool = False


@dataclass(frozen=True)
class RankedKeyword:
    """One keyword a DOMAIN currently ranks for, with the demand behind it.

    The competitor-intel gap analysis's raw material (Part 8 Phase 2C). This is the
    one question the house Serper seam genuinely cannot answer: ``/search`` reads ONE
    SERP for ONE keyword, whereas a gap analysis needs the whole set of terms a rival
    ranks for - which is a domain-indexed query only a keyword-database vendor holds.
    Hence it lives on THIS seam (the DataForSEO exception) rather than in a second
    SERP provider.

    ``position`` is the domain's rank for the term. Unlike a rank-tracker reading it
    is never ``None``: the provider only returns keywords the domain DOES rank for,
    so a term's absence from this list is what "does not rank" looks like here.
    """

    keyword: str
    position: int
    volume: int = 0
    difficulty: float = 0.0
    intent: str | None = None


@runtime_checkable
class KeywordDataProvider(Protocol):
    """Keyword ideas + demand metrics + a provider-side intent + a domain's ranked set.

    ``geo`` is an optional country/locale hint (e.g. ``"us"``, ``"gb"``); ``None``
    uses the provider default. Implementations MUST be deterministic given the same
    inputs so a research run is reproducible.
    """

    def keyword_ideas(self, seed: str, *, geo: str | None = None, limit: int = 50) -> list[KeywordMetric]: ...
    def related_keywords(self, keyword: str, *, geo: str | None = None, limit: int = 50) -> list[KeywordMetric]: ...
    def keyword_metrics_bulk(self, keywords: list[str], *, geo: str | None = None) -> list[KeywordMetric]: ...
    def search_intent(self, keyword: str) -> str | None: ...
    def ranked_keywords(self, domain: str, *, geo: str | None = None, limit: int = 100) -> list[RankedKeyword]: ...


def _to_int(value: Any, *, lo: int = 0) -> int:
    try:
        return max(lo, round(float(value)))
    except (TypeError, ValueError):
        return lo


def _to_float(value: Any, *, lo: float = 0.0, hi: float | None = None) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return lo
    n = max(lo, n)
    return min(hi, n) if hi is not None else n


def normalize_intent(raw: str | None) -> str | None:
    """Map a provider/free-text intent onto one of the five capitalised labels, or
    ``None`` when it does not resolve (so the service can fall back to the SERP
    heuristic). Case-insensitive; ``"commercial investigation"`` -> ``"Commercial"``."""
    if not raw:
        return None
    text = str(raw).strip().lower()
    for label in INTENT_LABELS:
        if text.startswith(label.lower()):
            return label
    # DataForSEO's search_intent uses 'commercial'/'navigational'/'transactional'/
    # 'informational'; anything local-ish maps to Local.
    if "local" in text or "near" in text:
        return "Local"
    return None


class DataForSeoProvider(HttpProviderClient):
    """Real ``KeywordDataProvider`` over the DataForSEO Labs keyword API.

    Auth is HTTP Basic (``login`` + ``password``), handed to httpx per request and
    NEVER logged. The caller (the factory / service layer) supplies the credential;
    an empty pair raises ``ProviderNotConfiguredError`` naming the fix.
    """

    provider = "dataforseo_keywords"

    def __init__(self, *, login: str, password: str, timeout: float = 30.0) -> None:
        if not login or not password:
            raise ProviderNotConfiguredError(f"DataForSEO keyword data unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_DFS_BASE,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        self._auth = (login, password)

    def keyword_ideas(self, seed: str, *, geo: str | None = None, limit: int = 50) -> list[KeywordMetric]:
        body = [_dfs_request_body([seed], geo, limit)]
        data = self.request_json(
            "POST", "/v3/dataforseo_labs/google/keyword_ideas/live", json_body=body, auth=self._auth
        )
        return [_metric_from_dfs(item) for item in _dfs_items(data)]

    def related_keywords(self, keyword: str, *, geo: str | None = None, limit: int = 50) -> list[KeywordMetric]:
        body = [_dfs_request_body([keyword], geo, limit)]
        data = self.request_json(
            "POST", "/v3/dataforseo_labs/google/related_keywords/live", json_body=body, auth=self._auth
        )
        return [_metric_from_dfs(item) for item in _dfs_items(data)]

    def keyword_metrics_bulk(self, keywords: list[str], *, geo: str | None = None) -> list[KeywordMetric]:
        if not keywords:
            return []
        body = [_dfs_request_body(keywords, geo, len(keywords))]
        data = self.request_json(
            "POST", "/v3/dataforseo_labs/google/keyword_overview/live", json_body=body, auth=self._auth
        )
        return [_metric_from_dfs(item) for item in _dfs_items(data)]

    def search_intent(self, keyword: str) -> str | None:
        body = [{"keywords": [keyword]}]
        data = self.request_json(
            "POST", "/v3/dataforseo_labs/google/search_intent/live", json_body=body, auth=self._auth
        )
        for item in _dfs_items(data):
            info = item.get("keyword_intent") or {}
            label = normalize_intent(info.get("label") if isinstance(info, dict) else None)
            if label is not None:
                return label
        return None

    def ranked_keywords(self, domain: str, *, geo: str | None = None, limit: int = 100) -> list[RankedKeyword]:
        """Every keyword ``domain`` ranks for, with position + demand.

        ``target`` is a bare host (no scheme) per the Labs API contract - the caller
        normalises it. Items missing a keyword or a usable position are dropped rather
        than defaulted: a fabricated position would become a fabricated gap verdict.
        """
        if not domain:
            return []
        body: dict[str, Any] = {"target": domain, "limit": max(1, min(limit, 1000))}
        if geo:
            body["location_name"] = geo
        data = self.request_json(
            "POST", "/v3/dataforseo_labs/google/ranked_keywords/live", json_body=[body], auth=self._auth
        )
        out: list[RankedKeyword] = []
        for item in _dfs_items(data):
            ranked = _ranked_from_dfs(item)
            if ranked is not None:
                out.append(ranked)
        return out


def _dfs_request_body(keywords: list[str], geo: str | None, limit: int) -> dict[str, Any]:
    """One DataForSEO Labs task body (keywords + optional geo + a bounded limit)."""
    body: dict[str, Any] = {"keywords": keywords, "limit": max(1, min(limit, 1000))}
    if geo:
        body["location_name"] = geo
    return body


def _dfs_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull ``tasks[].result[].items[]`` out of a DataForSEO envelope defensively."""
    items: list[dict[str, Any]] = []
    for task in data.get("tasks") or []:
        for result in (task or {}).get("result") or []:
            for item in (result or {}).get("items") or []:
                if isinstance(item, dict):
                    items.append(item)
    return items


def _metric_from_dfs(item: dict[str, Any]) -> KeywordMetric:
    """Map one DataForSEO Labs item to a ``KeywordMetric`` (defensive; nested info
    blocks are read best-effort)."""
    info = item.get("keyword_info") or {}
    props = item.get("keyword_properties") or {}
    if not isinstance(info, dict):
        info = {}
    if not isinstance(props, dict):
        props = {}
    return KeywordMetric(
        keyword=str(item.get("keyword") or ""),
        volume=_to_int(info.get("search_volume")),
        difficulty=_to_float(props.get("keyword_difficulty"), hi=100.0),
        cpc=_to_float(info.get("cpc")),
        competition=_to_float(info.get("competition"), hi=1.0),
        low_confidence=info.get("search_volume") in (None, 0),
    )


def _ranked_from_dfs(item: dict[str, Any]) -> RankedKeyword | None:
    """Map one DataForSEO Labs ``ranked_keywords`` item to a ``RankedKeyword``.

    The Labs payload nests the term under ``keyword_data`` (the same block
    ``_metric_from_dfs`` reads) and the POSITION under
    ``ranked_serp_element.serp_item.rank_absolute``. ``rank_absolute`` is the
    position counting EVERY SERP element, which is what a human sees on the page;
    ``rank_group`` collapses a domain's stacked results to one number, so it is the
    fallback rather than the primary.

    Returns ``None`` - never a defaulted row - when the keyword or the position is
    unreadable. A position defaulted to 0/1 here would silently become a "the
    competitor ranks #1" gap verdict conjured out of a malformed payload.
    """
    kw_data = item.get("keyword_data")
    if not isinstance(kw_data, dict):
        return None
    keyword = str(kw_data.get("keyword") or "").strip()
    if not keyword:
        return None

    element = item.get("ranked_serp_element")
    serp_item = element.get("serp_item") if isinstance(element, dict) else None
    if not isinstance(serp_item, dict):
        return None
    raw_position = serp_item.get("rank_absolute")
    if raw_position is None:
        raw_position = serp_item.get("rank_group")
    try:
        position = int(raw_position)  # type: ignore[arg-type]  # guarded by the except
    except (TypeError, ValueError):
        return None
    if position < 1:
        return None

    metric = _metric_from_dfs(kw_data)
    intent_block = kw_data.get("search_intent_info")
    intent = None
    if isinstance(intent_block, dict):
        intent = normalize_intent(intent_block.get("main_intent"))
    return RankedKeyword(
        keyword=keyword,
        position=position,
        volume=metric.volume,
        difficulty=metric.difficulty,
        intent=intent,
    )


class FakeKeywordDataProvider:
    """Deterministic, offline ``KeywordDataProvider`` - sha256(keyword) -> stable
    metrics. Same keyword => identical numbers every run; different keywords differ.
    No network, so the module's unit tests + a keyless deploy are reproducible."""

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode()).hexdigest()

    def _metric(self, keyword: str) -> KeywordMetric:
        digest = self._digest(keyword)
        return KeywordMetric(
            keyword=keyword,
            volume=int(digest[0:5], 16) % 50_000,          # 0..49_999, stable
            difficulty=float(int(digest[5:7], 16) % 101),  # 0..100
            cpc=round((int(digest[7:10], 16) % 2000) / 100, 2),  # 0.00..19.99
            competition=round((int(digest[10:12], 16) % 101) / 100, 3),  # 0.000..1.000
            low_confidence=int(digest[12:13], 16) == 0,    # ~1/16 low-confidence
        )

    def keyword_ideas(self, seed: str, *, geo: str | None = None, limit: int = 50) -> list[KeywordMetric]:
        digest = self._digest(seed)
        n = 3 + int(digest[0:2], 16) % 6  # 3..8 ideas
        suffixes = ("services", "cost", "near me", "best", "guide", "for small business", "reviews", "company")
        out = [self._metric(seed)]
        for i in range(min(n, limit) - 1):
            out.append(self._metric(f"{seed} {suffixes[i % len(suffixes)]}"))
        return out[:limit]

    def related_keywords(self, keyword: str, *, geo: str | None = None, limit: int = 50) -> list[KeywordMetric]:
        digest = self._digest(keyword)
        n = 2 + int(digest[2:4], 16) % 5  # 2..6 related
        modifiers = ("how to", "vs", "alternative", "pricing", "top", "tips")
        out = [self._metric(f"{modifiers[i % len(modifiers)]} {keyword}") for i in range(n)]
        return out[:limit]

    def keyword_metrics_bulk(self, keywords: list[str], *, geo: str | None = None) -> list[KeywordMetric]:
        return [self._metric(kw) for kw in keywords]

    def search_intent(self, keyword: str) -> str | None:
        # Deterministic label off the digest, so the fake exercises the provider
        # branch of the intent cascade reproducibly.
        idx = int(self._digest(keyword)[13:15], 16) % len(INTENT_LABELS)
        return INTENT_LABELS[idx]

    def ranked_keywords(self, domain: str, *, geo: str | None = None, limit: int = 100) -> list[RankedKeyword]:
        """A stable ranked set for ``domain``, derived from sha256(domain).

        Deliberately built from a SHARED term pool plus a domain-specific tail: a gap
        analysis is only meaningful when two domains' sets partially INTERSECT, so a
        fake that gave every domain a disjoint set would make every overlap 0 and
        every gap total - i.e. it would exercise none of the classification the
        module exists to perform.
        """
        if not domain:
            return []
        digest = self._digest(domain)
        # The shared pool: every domain ranks for some prefix of these, so two fake
        # domains always intersect (and never identically - the prefix length varies).
        shared = (
            "seo services", "local seo", "seo agency", "keyword research",
            "link building", "technical seo", "content marketing", "seo audit",
        )
        n_shared = 3 + int(digest[0:2], 16) % (len(shared) - 2)  # 3..len(shared)
        terms = [*shared[:n_shared]]
        # The tail: terms only THIS domain ranks for (the other side's pure gaps).
        n_own = 2 + int(digest[2:4], 16) % 4  # 2..5
        terms += [f"{domain.split('.')[0]} {suffix}" for suffix in
                  ("reviews", "pricing", "alternative", "vs", "login")[:n_own]]

        out: list[RankedKeyword] = []
        for i, term in enumerate(terms[:limit]):
            metric = self._metric(term)
            # Position is domain-AND-term dependent, so two domains ranking for the
            # same shared term hold DIFFERENT positions - which is what makes the
            # weak/shared classification testable against the fake.
            position = 1 + int(self._digest(f"{domain}|{term}")[0:2], 16) % 30
            out.append(
                RankedKeyword(
                    keyword=term,
                    position=position,
                    volume=metric.volume,
                    difficulty=metric.difficulty,
                    intent=INTENT_LABELS[(i + int(digest[4:6], 16)) % len(INTENT_LABELS)],
                )
            )
        return out


def keyword_data_provider_from_settings(settings: Settings) -> KeywordDataProvider:
    """The real DataForSEO provider when the credential pair is present, else the
    deterministic fake (so the module runs offline / keyless). No secret is logged -
    the degraded path logs only the reason."""
    login = settings.dataforseo_login
    password = settings.dataforseo_password
    if login and password:
        return DataForSeoProvider(login=login, password=password.get_secret_value())
    logger.info("keyword_data_provider_degraded", reason="missing_credentials")
    return FakeKeywordDataProvider()
