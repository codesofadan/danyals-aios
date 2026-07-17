"""Rank-check provider seam (Part 8 Phase 2B): the ONLY door to a live SERP lookup
for rank tracking.

This is MODULE-PRIVATE on purpose. ``integrations/keyword_data.py`` is the keyword
DEMAND seam (volume / difficulty / CPC from DataForSEO Labs) and answers a different
question; rank tracking needs POSITIONS out of a live SERP, so it owns its own
Protocol rather than bending that one.

The vendor is **TO-CONFIRM at kickoff**, so nothing here is hard-wired to one:
``rank_provider_from_settings`` dispatches on ``settings.rank_tracker_provider``
through ``_REGISTRY``. Swapping vendors is a config change, never a code change at any
call site - ``tasks.py`` only ever holds the ``RankProvider`` Protocol.

* ``SerperRankProvider`` - the DEFAULT. Serper.dev is the HOUSE SERP vendor (already
  used by ``integrations/content_research.py``), so rank tracking reuses the existing
  ``SERPER_API_KEY`` rather than onboarding a second bill. Shares the sync
  ``HttpProviderClient`` (retry/backoff, secret-safe error logging); the key rides in
  the ``X-API-KEY`` HEADER - never a URL, never a log line.
* ``DataForSeoRankProvider`` - the named fallback, over DataForSEO's SERP API. Auth is
  HTTP Basic on the login/password pair the off-page + keyword modules already use. It
  reuses ``integrations.keyword_data._dfs_items``, the envelope reader already
  exercised against real DataForSEO payloads, rather than a second divergent parser.
* ``FakeRankProvider`` - deterministic, network-free: every field derives from a
  sha256 of (keyword, engine, device, locale), so the same keyword always yields the
  same SERP and different keywords differ. Unit tests + a keyless deploy use it.

``enabled`` means "this provider makes LIVE, BILLABLE calls". The fake reports False,
so a degraded (keyless) deploy is legible to the worker and to ops instead of quietly
looking like real rank data.

``estimated_cost(depth)`` is what the cost gate pre-checks AND what the N-A monthly
projection multiplies out, so a vendor swap automatically re-prices both the per-check
gate and the subscription commitment.

FAILURE CONTRACT (this module's single most important rule): a failed fetch returns a
``SerpSnapshot`` with ``error`` set and an EMPTY ``organic`` list. It never raises and
never fabricates an empty-but-successful SERP - because "no organic hits" is
indistinguishable from "the client is unranked", and recording a vendor outage as
"unranked" would fabricate a phantom LOST RANKING and fire a false alert.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("modules.rank_tracker.provider")

_SERPER_BASE = "https://google.serper.dev"
_DFS_BASE = "https://api.dataforseo.com"

_SERPER_HINT = "set SERPER_API_KEY (Serper.dev) to enable live rank checks"
_DFS_HINT = (
    "set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD to enable live rank checks via DataForSEO"
)

# How deep the SERP is read. 100 is the industry-standard rank-tracking window: past it
# a position is not commercially meaningful, and every vendor prices by result page.
DEFAULT_DEPTH = 100

# The keys ``settings.rank_tracker_provider`` accepts. 'serper' is the default (the
# house vendor); 'dataforseo' is the contracted fallback; 'fake' forces the offline
# deterministic provider.
PROVIDER_KEYS: tuple[str, ...] = ("serper", "dataforseo", "fake")


@dataclass(frozen=True)
class OrganicHit:
    """One organic SERP listing: its rank position, URL and title."""

    position: int
    url: str
    title: str = ""


@dataclass(frozen=True)
class SerpSnapshot:
    """One SERP read for one keyword at one locale/device.

    ``organic`` is the ranked listing set (position-ascending); ``features`` are the
    SERP features present (``ai_overview``, ``local_pack``, ...).

    ``error`` is set ONLY on a failed fetch - and when it is set ``organic`` is empty
    and MUST NOT be read as "unranked" (see the module docstring's failure contract).
    Callers gate on :attr:`ok`, never on ``len(organic)``.
    """

    keyword: str
    organic: list[OrganicHit] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    provider: str = ""
    fetched_at: datetime | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this snapshot is a trustworthy read (no provider error)."""
        return self.error is None


@runtime_checkable
class RankProvider(Protocol):
    """Fetch a SERP snapshot for one keyword, and price one such fetch.

    ``enabled`` reports whether this provider makes LIVE, BILLABLE calls (the fake
    reports False). ``fetch_serp`` MUST NOT raise: a vendor failure comes back as a
    ``SerpSnapshot`` carrying ``error``.
    """

    provider: str
    enabled: bool

    def fetch_serp(
        self,
        keyword: str,
        *,
        location: str = "",
        device: str = "desktop",
        language: str = "en",
        country: str = "us",
        engine: str = "google",
        depth: int = DEFAULT_DEPTH,
    ) -> SerpSnapshot: ...

    def estimated_cost(self, depth: int = DEFAULT_DEPTH) -> float: ...


# --------------------------------------------------------------------------- #
# Pure helpers: find OUR domain in a snapshot.
# --------------------------------------------------------------------------- #
def _host(url: str) -> str:
    """The lowercased bare host of ``url`` (``www.`` stripped, port dropped).

    Accepts a BARE DOMAIN as well as a full URL: a ``sites.domain`` value is stored
    without a scheme, and ``urlsplit('example.com/x')`` would otherwise read the whole
    string as a path and yield an empty host (making every comparison silently false).
    """
    text = (url or "").strip().lower()
    if not text:
        return ""
    if "//" not in text:
        text = f"//{text}"
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:  # malformed URL (e.g. a bad IPv6 literal) - not our domain
        return ""
    return host[4:] if host.startswith("www.") else host


def _same_domain(hit_url: str, domain: str) -> bool:
    """Whether ``hit_url`` belongs to ``domain`` (exact host or any subdomain).

    Suffix matching is anchored on a leading dot, so ``notexample.com`` can never be
    counted as a hit for ``example.com``.
    """
    target = _host(domain)
    if not target:
        return False
    host = _host(hit_url)
    return host == target or host.endswith(f".{target}")


def find_all_positions(snapshot: SerpSnapshot, domain: str) -> list[OrganicHit]:
    """EVERY hit in ``snapshot`` belonging to ``domain``, best position first.

    More than one hit means the client's own pages are competing for the term
    (CANNIBALIZATION) - which is why the history keeps them all in ``own_urls``
    instead of only the winner. An errored snapshot yields ``[]`` (it holds no organic
    listings to search), which is exactly why callers must check ``snapshot.ok``.
    """
    hits = [h for h in snapshot.organic if _same_domain(h.url, domain)]
    return sorted(hits, key=lambda h: h.position)


def find_position(snapshot: SerpSnapshot, domain: str) -> OrganicHit | None:
    """``domain``'s BEST hit in ``snapshot``, or ``None`` when it does not appear.

    ``None`` means "not in the fetched window" and is meaningful ONLY for an OK
    snapshot. An errored snapshot also yields ``None`` - for an entirely different
    reason - so callers gate on ``snapshot.ok`` FIRST.
    """
    hits = find_all_positions(snapshot, domain)
    return hits[0] if hits else None


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Pricing - shared by the live providers AND the price-only path.
# --------------------------------------------------------------------------- #
# These are module-level so the N-A projection can price a vendor WITHOUT constructing
# it (see ``rank_pricing_from_settings``): the API edge needs a number, not a socket.
def _serper_cost(base: float, depth: int) -> float:
    """Serper bills per QUERY, but a result window past the default 10 costs an extra
    credit per additional page - so price by pages, rounded up."""
    pages = max(1, -(-max(depth, 1) // 10))
    return round(base * pages, 6)


def _dfs_cost(base: float, depth: int) -> float:
    """DataForSEO's live SERP endpoint prices per task, deeper reads costing more;
    priced per 100-result block, rounded up."""
    blocks = max(1, -(-max(depth, 1) // 100))
    return round(base * blocks, 6)


def _free(_base: float, _depth: int) -> float:
    """A simulated check bills nothing - so a degraded deploy logs an honest $0."""
    return 0.0


# --------------------------------------------------------------------------- #
# Serper (the house vendor; the default).
# --------------------------------------------------------------------------- #
class SerperRankProvider(HttpProviderClient):
    """Real ``RankProvider`` over Serper.dev - the platform's existing SERP vendor.

    Key-gated on the EXISTING ``SERPER_API_KEY``: an empty key raises
    ``ProviderNotConfiguredError`` naming the fix, and the factory degrades to the
    fake. The key rides in the ``X-API-KEY`` header and is never logged - a failed
    fetch logs only the exception TYPE.
    """

    provider = "serper"
    enabled = True  # constructed only with a live key (see __init__)

    def __init__(
        self, *, api_key: str, timeout: float = 20.0, cost_per_check: float = 0.001
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Serper rank checks unavailable: {_SERPER_HINT}")
        super().__init__(
            base_url=_SERPER_BASE,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._cost_per_check = cost_per_check

    def estimated_cost(self, depth: int = DEFAULT_DEPTH) -> float:
        return _serper_cost(self._cost_per_check, depth)

    def fetch_serp(
        self,
        keyword: str,
        *,
        location: str = "",
        device: str = "desktop",
        language: str = "en",
        country: str = "us",
        engine: str = "google",
        depth: int = DEFAULT_DEPTH,
    ) -> SerpSnapshot:
        """One live SERP read. NEVER raises - a failure returns ``error`` set."""
        body: dict[str, Any] = {"q": keyword, "gl": country, "hl": language, "num": max(1, depth)}
        if location:
            body["location"] = location
        if device == "mobile":
            # Serper serves its default (desktop) viewport for everything else; only
            # mobile is a genuinely distinct SERP, so tablet stays on the default
            # rather than being silently mis-labelled as a mobile result.
            body["device"] = "mobile"
        path = "/search" if engine == "google" else f"/{engine}/search"
        try:
            data = self.request_json("POST", path, json_body=body)
        except Exception as exc:
            logger.warning(
                "rank_serp_fetch_failed", provider=self.provider, error=type(exc).__name__
            )
            return SerpSnapshot(keyword=keyword, provider=self.provider, error=type(exc).__name__)
        return SerpSnapshot(
            keyword=keyword,
            organic=_serper_organic(data),
            features=_serper_features(data),
            provider=self.provider,
            fetched_at=datetime.now(UTC),
        )


def _serper_organic(data: dict[str, Any]) -> list[OrganicHit]:
    """Read ``organic[]`` off a Serper response defensively (a missing ``position``
    falls back to the array index, so an unnumbered payload still ranks in order)."""
    out: list[OrganicHit] = []
    for index, item in enumerate(data.get("organic") or []):
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "")
        if not link:
            continue
        out.append(
            OrganicHit(
                position=_as_int(item.get("position"), index + 1),
                url=link,
                title=str(item.get("title") or ""),
            )
        )
    return out


def _serper_features(data: dict[str, Any]) -> list[str]:
    """The SERP features present in a Serper response, in a stable declared order so a
    day-over-day snapshot diff is meaningful."""
    checks: tuple[tuple[str, bool], ...] = (
        ("ai_overview", bool(data.get("aiOverview") or data.get("ai_overview"))),
        ("answer_box", "answerBox" in data),
        ("knowledge_graph", "knowledgeGraph" in data),
        ("local_pack", bool(data.get("places") or data.get("localResults"))),
        ("people_also_ask", bool(data.get("peopleAlsoAsk"))),
        ("related_searches", bool(data.get("relatedSearches"))),
        ("top_ads", bool(data.get("ads"))),
    )
    return [name for name, present in checks if present]


# --------------------------------------------------------------------------- #
# DataForSEO (the contracted fallback).
# --------------------------------------------------------------------------- #
class DataForSeoRankProvider(HttpProviderClient):
    """``RankProvider`` over the DataForSEO SERP API (the contracted fallback vendor).

    Auth is HTTP Basic on the SAME login/password pair the off-page + keyword-research
    modules already use, handed to httpx per request and NEVER logged. The response
    envelope (``tasks[].result[].items[]``) is read with ``keyword_data._dfs_items``.
    """

    provider = "dataforseo"
    enabled = True  # constructed only with a live credential pair (see __init__)

    def __init__(
        self, *, login: str, password: str, timeout: float = 30.0, cost_per_check: float = 0.002
    ) -> None:
        if not login or not password:
            raise ProviderNotConfiguredError(f"DataForSEO rank checks unavailable: {_DFS_HINT}")
        super().__init__(
            base_url=_DFS_BASE, headers={"Content-Type": "application/json"}, timeout=timeout
        )
        self._auth = (login, password)
        self._cost_per_check = cost_per_check

    def estimated_cost(self, depth: int = DEFAULT_DEPTH) -> float:
        return _dfs_cost(self._cost_per_check, depth)

    def fetch_serp(
        self,
        keyword: str,
        *,
        location: str = "",
        device: str = "desktop",
        language: str = "en",
        country: str = "us",
        engine: str = "google",
        depth: int = DEFAULT_DEPTH,
    ) -> SerpSnapshot:
        """One live SERP read. NEVER raises - a failure returns ``error`` set."""
        from integrations.keyword_data import _dfs_items

        task: dict[str, Any] = {
            "keyword": keyword,
            "language_code": language,
            # DataForSEO requires SOME location; a blank one falls back to the country.
            "location_name": location or country.upper(),
            "device": device if device in ("desktop", "mobile") else "desktop",
            "depth": max(1, depth),
        }
        try:
            data = self.request_json(
                "POST",
                f"/v3/serp/{engine}/organic/live/advanced",
                json_body=[task],
                auth=self._auth,
            )
        except Exception as exc:
            logger.warning(
                "rank_serp_fetch_failed", provider=self.provider, error=type(exc).__name__
            )
            return SerpSnapshot(keyword=keyword, provider=self.provider, error=type(exc).__name__)
        items = _dfs_items(data)
        return SerpSnapshot(
            keyword=keyword,
            organic=_dfs_organic(items),
            features=_dfs_features(items),
            provider=self.provider,
            fetched_at=datetime.now(UTC),
        )


def _dfs_organic(items: list[dict[str, Any]]) -> list[OrganicHit]:
    """The ``type == 'organic'`` items of a DataForSEO SERP result, position-ordered.

    A DataForSEO result set INTERLEAVES organic listings with feature blocks (ads, PAA,
    local pack) and ``rank_absolute`` counts BOTH - so the organic items are filtered
    out and RE-RANKED 1..n. Reading ``rank_absolute`` directly would report a client at
    #2 when they are the first organic result on a SERP with one ad on top.
    """
    organic = [item for item in items if str(item.get("type") or "") == "organic"]
    organic.sort(
        key=lambda item: _as_int(item.get("rank_absolute"), _as_int(item.get("rank_group"), 0))
    )
    out: list[OrganicHit] = []
    for index, item in enumerate(organic):
        url = str(item.get("url") or "")
        if not url:
            continue
        out.append(OrganicHit(position=index + 1, url=url, title=str(item.get("title") or "")))
    return out


def _dfs_features(items: list[dict[str, Any]]) -> list[str]:
    """The distinct non-organic item types present (DataForSEO names each SERP feature
    block by its ``type``), sorted so a day-over-day diff is stable."""
    return sorted(
        {
            str(item.get("type"))
            for item in items
            if item.get("type") and str(item.get("type")) != "organic"
        }
    )


# --------------------------------------------------------------------------- #
# The deterministic fake (offline / keyless / tests).
# --------------------------------------------------------------------------- #
class FakeRankProvider:
    """Deterministic, offline ``RankProvider`` - sha256(keyword+locale) -> stable SERP.

    Same inputs => identical snapshot every run; different keywords differ. It costs
    $0 and lets the whole module - the nightly dispatcher, the check worker, the
    movement maths - run and be tested with zero keys and zero network.

    ``enabled`` is False: it is NOT a live vendor. That is what makes a keyless deploy
    legible (the worker reports a degraded provider) instead of quietly presenting
    invented positions as real rank data.

    ``domain`` seeds a guaranteed self-hit so a test can exercise the RANKED path
    deterministically; without it the client's presence is whatever the digest yields
    (i.e. unranked), which is the honest default for an arbitrary domain.
    """

    provider = "fake"
    enabled = False

    def __init__(self, *, domain: str | None = None) -> None:
        self._domain = domain

    def estimated_cost(self, depth: int = DEFAULT_DEPTH) -> float:
        return _free(0.0, depth)

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode()).hexdigest()

    def fetch_serp(
        self,
        keyword: str,
        *,
        location: str = "",
        device: str = "desktop",
        language: str = "en",
        country: str = "us",
        engine: str = "google",
        depth: int = DEFAULT_DEPTH,
    ) -> SerpSnapshot:
        digest = self._digest(f"{keyword}|{engine}|{device}|{location}|{language}|{country}")
        count = min(max(1, depth), 5 + int(digest[0:2], 16) % 6)  # 5..10 listings
        organic = [
            OrganicHit(
                position=i + 1,
                url=f"https://{digest[i * 4 : i * 4 + 6]}.example/{digest[i * 2 : i * 2 + 4]}",
                title=f"{keyword.title()} - result {i + 1}",
            )
            for i in range(count)
        ]
        if self._domain:
            slot = int(digest[8:10], 16) % count  # a deterministic self-hit in-window
            organic[slot] = OrganicHit(
                position=slot + 1,
                url=f"https://{_host(self._domain)}/{digest[10:16]}",
                title=f"{keyword.title()} | {self._domain}",
            )
        pool = ("ai_overview", "local_pack", "people_also_ask", "answer_box")
        features = [f for i, f in enumerate(pool) if int(digest[16 + i], 16) % 2]
        return SerpSnapshot(
            keyword=keyword,
            organic=organic,
            features=features,
            provider=self.provider,
            fetched_at=datetime.now(UTC),
        )


# --------------------------------------------------------------------------- #
# The factory: config-driven, never hard-wired to a vendor.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RankPricing:
    """What one rank check costs, WITHOUT building a provider.

    The API edge (the N-A projection) needs a price, a vendor name, and whether the
    vendor is live - it never fetches a SERP. Constructing a real provider just to read
    ``estimated_cost`` would open an httpx client (and leak its socket) on every
    ``POST /keywords`` and every ``GET /cost-projection``. This is the price-only door;
    ``rank_provider_from_settings`` remains the door for code that actually fetches.
    """

    provider: str
    live: bool
    cost_per_check: float


@dataclass(frozen=True)
class _Vendor:
    """One vendor's three seams, kept together so the pricing path and the fetching
    path can never disagree about who is configured or what they charge."""

    build: Callable[[Settings], RankProvider]
    price: Callable[[float, int], float]
    configured: Callable[[Settings], bool]


def _serper_configured(settings: Settings) -> bool:
    key = settings.serper_api_key
    return key is not None and bool(key.get_secret_value())


def _build_serper(settings: Settings) -> RankProvider:
    key = settings.serper_api_key
    if key is None:  # unreachable via _resolve (guarded by _serper_configured)
        raise ProviderNotConfiguredError(f"Serper rank checks unavailable: {_SERPER_HINT}")
    return SerperRankProvider(
        api_key=key.get_secret_value(),
        cost_per_check=float(settings.rank_tracker_cost_estimate),
    )


def _dfs_configured(settings: Settings) -> bool:
    password = settings.dataforseo_password
    return bool(settings.dataforseo_login) and password is not None and bool(
        password.get_secret_value()
    )


def _build_dataforseo(settings: Settings) -> RankProvider:
    password = settings.dataforseo_password
    if not settings.dataforseo_login or password is None:  # unreachable via _resolve
        raise ProviderNotConfiguredError(f"DataForSEO rank checks unavailable: {_DFS_HINT}")
    return DataForSeoRankProvider(
        login=settings.dataforseo_login,
        password=password.get_secret_value(),
        cost_per_check=float(settings.rank_tracker_cost_estimate),
    )


def _build_fake(_settings: Settings) -> RankProvider:
    return FakeRankProvider()


# The vendor registry BOTH factories dispatch through. Adding a vendor (ValueSERP is the
# other name on the contract's shortlist) is a class + ONE line here - no call-site
# change, because tasks.py only ever holds the RankProvider Protocol and the router only
# ever holds RankPricing.
_REGISTRY: dict[str, _Vendor] = {
    "serper": _Vendor(build=_build_serper, price=_serper_cost, configured=_serper_configured),
    "dataforseo": _Vendor(
        build=_build_dataforseo, price=_dfs_cost, configured=_dfs_configured
    ),
    "fake": _Vendor(build=_build_fake, price=_free, configured=lambda _s: True),
}

_DEGRADED = RankPricing(provider="fake", live=False, cost_per_check=0.0)


def _resolve(settings: Settings) -> tuple[str, _Vendor] | None:
    """The configured vendor, or ``None`` when it is unknown or credential-less."""
    key = (settings.rank_tracker_provider or "serper").strip().lower()
    vendor = _REGISTRY.get(key)
    if vendor is None:
        logger.warning("rank_provider_unknown", configured=key, fallback="fake")
        return None
    if not vendor.configured(settings):
        logger.info("rank_provider_degraded", provider=key, reason="missing_credentials")
        return None
    return key, vendor


def rank_pricing_from_settings(
    settings: Settings, *, depth: int = DEFAULT_DEPTH
) -> RankPricing:
    """What one check costs under the CONFIGURED vendor - no client, no socket.

    A degraded (keyless) deploy prices at $0 and reports ``live=False``, so the N-A
    projection quotes an honest zero and says WHY rather than presenting simulated
    numbers as a real commitment.
    """
    resolved = _resolve(settings)
    if resolved is None:
        return _DEGRADED
    key, vendor = resolved
    if key == "fake":
        return _DEGRADED
    return RankPricing(
        provider=key,
        live=True,
        cost_per_check=vendor.price(float(settings.rank_tracker_cost_estimate), depth),
    )


def rank_provider_from_settings(settings: Settings) -> RankProvider:
    """The configured rank provider, or the deterministic fake (never ``None``).

    The vendor is chosen by ``settings.rank_tracker_provider`` (default ``serper``, the
    house vendor), so the TO-CONFIRM vendor decision is a CONFIG change, not a code
    change. A configured-but-credential-less vendor DEGRADES to the fake; it never
    crashes, and it never logs the credential itself.

    This CONSTRUCTS an HTTP client, so only the worker should call it. Code that just
    needs a price wants ``rank_pricing_from_settings``.
    """
    resolved = _resolve(settings)
    if resolved is None:
        return FakeRankProvider()
    _key, vendor = resolved
    return vendor.build(settings)
