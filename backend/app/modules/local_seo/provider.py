"""Map-pack rank seam (Part 8 Phase 2E): the ONLY door to a local-pack position.

A local-pack check asks ONE question: for ``keyword`` at ``geo``, where does this
business sit in Google's 3-pack (and who is in it)? That is a SINGLE position at a
SINGLE representative locale - there is deliberately no geo-grid / lat-lng fan-out /
heatmap anywhere behind this Protocol (out of contract scope), so an implementation
that wanted to fan out has nowhere to put the extra points.

The provider is TO-CONFIRM with the client, so the seam is provider-AGNOSTIC and
three impls satisfy it (mirroring the citations / keyword_data seams exactly):

* ``SerperPlacesProvider`` - the HOUSE DEFAULT, reusing the Serper key the platform
  already holds (``SERPER_API_KEY``) against Serper's ``/places`` endpoint. The key
  rides in the ``X-API-KEY`` header - never a URL, never a log line.
* ``DataForSeoMapsProvider`` - the fallback, behind the SAME Protocol, on the
  DataForSEO login/password the off-page module already carries. Key-gated the same
  way, so swapping providers is a settings change, not a code change.
* ``FakeLocalPackProvider`` - deterministic, network-free: sha256(keyword|geo|
  business) drives the position, so the same inputs always yield the same rank and a
  keyless deploy still works with plausible data.

``local_pack_provider_from_settings`` returns the REAL provider when its keys are
present, else the FAKE (never ``None``) - the module works offline / keyless.

THE NULL CONTRACT (the whole reason ``rank`` is ``int | None``): a result with
``rank=None`` and ``error=None`` means "checked successfully, the business is NOT in
the pack" - an honest absence. A FAILED check sets ``error`` and the caller must
write NOTHING (see ``tasks.refresh_local_ranks``): persisting a failure as a null
rank would fabricate a ranking loss the business never suffered.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("app.modules.local_seo.provider")

_SERPER_INSTALL_HINT = (
    "set SERPER_API_KEY to enable live map-pack rank checks; without it the "
    "deterministic fake is used"
)
_DFS_INSTALL_HINT = (
    "set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD to enable the DataForSEO Maps "
    "fallback for map-pack rank checks"
)
_SERPER_BASE = "https://google.serper.dev"
_DFS_BASE = "https://api.dataforseo.com"

# The local pack is a 3-pack: a position at or below this is "in the map pack".
MAP_PACK_SIZE = 3
# How many pack entries we keep as the competitor set (the pack itself).
_TOP_COMPETITORS = 3


@dataclass(frozen=True)
class LocalRankResult:
    """One map-pack check for ONE (keyword, geo, business).

    ``rank`` is the 1-based position in the local pack, or ``None`` for "not found
    in the pack". ``in_map_pack`` is the top-3 flag. ``found_url`` is the listing
    link the pack showed. ``top_competitors`` are the pack's top-3 business names
    (how displacement is trended without a grid). ``error`` is set ONLY when the
    check FAILED - and then ``rank`` is meaningless and the caller must persist
    nothing (a failure is not an absence).
    """

    rank: int | None = None
    in_map_pack: bool = False
    found_url: str = ""
    top_competitors: list[str] = field(default_factory=list)
    provider: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this is a SUCCESSFUL check (``rank=None`` on an ok result is an
        honest "not in the pack", never a failure)."""
        return self.error is None


@runtime_checkable
class LocalPackProvider(Protocol):
    """Check ONE keyword's local-pack position for ONE business at ONE locale.

    ``geo`` is the single representative locale string (a city / market), NOT a grid
    point. ``place_id`` is the provider's handle for the client's own listing when we
    hold one (the precise match); ``business_name`` is the fallback match. Impls MUST
    be deterministic given the same inputs, and MUST return an ``error``-bearing
    result rather than raising for a provider-side failure.
    """

    provider: str
    enabled: bool

    def rank(
        self, *, keyword: str, geo: str | None, place_id: str | None, business_name: str
    ) -> LocalRankResult: ...

    def estimated_cost(self) -> float: ...


def _match_index(
    entries: list[dict[str, Any]], *, place_id: str | None, business_name: str
) -> int | None:
    """The 0-based index of the client's own listing in the pack, or ``None``.

    Matches on ``place_id`` first (exact, provider-issued) and falls back to a
    normalised name comparison - a business whose listing name drifts slightly from
    the client record would otherwise read as "not in the pack" (a phantom loss).
    """
    wanted_name = " ".join(business_name.lower().split())
    for index, entry in enumerate(entries):
        entry_place = str(entry.get("placeId") or entry.get("place_id") or "")
        if place_id and entry_place and entry_place == place_id:
            return index
        entry_name = " ".join(str(entry.get("title") or entry.get("name") or "").lower().split())
        if wanted_name and entry_name and entry_name == wanted_name:
            return index
    return None


def _names(entries: list[dict[str, Any]]) -> list[str]:
    """The pack's business names, in pack order (the competitor set)."""
    out: list[str] = []
    for entry in entries[:_TOP_COMPETITORS]:
        name = str(entry.get("title") or entry.get("name") or "").strip()
        if name:
            out.append(name)
    return out


def _result_from_entries(
    entries: list[dict[str, Any]],
    *,
    place_id: str | None,
    business_name: str,
    provider: str,
) -> LocalRankResult:
    """Fold a provider's pack listing into a ``LocalRankResult``.

    An unmatched business yields ``rank=None`` with NO error - the honest "checked,
    not in the pack" outcome. The competitor set is recorded either way, so a client
    that fell out of the pack still shows WHO is in it.
    """
    index = _match_index(entries, place_id=place_id, business_name=business_name)
    if index is None:
        return LocalRankResult(
            rank=None, in_map_pack=False, found_url="",
            top_competitors=_names(entries), provider=provider,
        )
    entry = entries[index]
    position = index + 1
    return LocalRankResult(
        rank=position,
        in_map_pack=position <= MAP_PACK_SIZE,
        found_url=str(entry.get("website") or entry.get("url") or ""),
        top_competitors=_names(entries),
        provider=provider,
    )


class SerperPlacesProvider(HttpProviderClient):
    """The HOUSE DEFAULT ``LocalPackProvider``: Serper's ``/places`` endpoint.

    Reuses the Serper key the platform ALREADY holds for SERP research, so local rank
    tracking activates with zero new vendor onboarding. The key rides in the
    ``X-API-KEY`` header (never a URL, never a log line); ``location`` carries the
    single representative locale.
    """

    provider = "serper_places"
    enabled = True

    def __init__(self, *, api_key: str, timeout: float = 20.0, cost: float = 0.003) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Serper Places unavailable: {_SERPER_INSTALL_HINT}")
        self._cost = cost
        super().__init__(
            base_url=_SERPER_BASE,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def estimated_cost(self) -> float:
        return self._cost

    def rank(
        self, *, keyword: str, geo: str | None, place_id: str | None, business_name: str
    ) -> LocalRankResult:
        body: dict[str, Any] = {"q": keyword}
        if geo:
            body["location"] = geo
        try:
            data = self.request_json("POST", "/places", json_body=body)
        except Exception as exc:
            # A failure is NOT an absence: surface it as an error result so the caller
            # writes nothing rather than recording a phantom rank=NULL.
            logger.warning(
                "local_pack_fetch_failed", provider=self.provider, error=type(exc).__name__
            )
            return LocalRankResult(provider=self.provider, error=f"{type(exc).__name__}")
        entries = [item for item in (data.get("places") or []) if isinstance(item, dict)]
        return _result_from_entries(
            entries, place_id=place_id, business_name=business_name, provider=self.provider
        )


class DataForSeoMapsProvider(HttpProviderClient):
    """The FALLBACK ``LocalPackProvider``: DataForSEO's Maps live SERP.

    Behind the SAME Protocol as the Serper default, on the DataForSEO login/password
    the off-page module already carries, so switching the map-pack provider is a
    settings change rather than a code change. Credentials go to httpx per request as
    HTTP Basic and are NEVER logged.
    """

    provider = "dataforseo_maps"
    enabled = True

    def __init__(
        self, *, login: str, password: str, timeout: float = 30.0, cost: float = 0.003
    ) -> None:
        if not login or not password:
            raise ProviderNotConfiguredError(f"DataForSEO Maps unavailable: {_DFS_INSTALL_HINT}")
        self._cost = cost
        super().__init__(
            base_url=_DFS_BASE,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        # Basic auth is handed to httpx PER REQUEST (the house DataForSEO pattern) so
        # the credential never sits in a persistent header dict.
        self._auth = (login, password)

    def estimated_cost(self) -> float:
        return self._cost

    def rank(
        self, *, keyword: str, geo: str | None, place_id: str | None, business_name: str
    ) -> LocalRankResult:
        task: dict[str, Any] = {"keyword": keyword, "language_code": "en"}
        if geo:
            task["location_name"] = geo
        try:
            data = self.request_json(
                "POST", "/v3/serp/google/maps/live/advanced", json_body=[task], auth=self._auth
            )
        except Exception as exc:
            logger.warning(
                "local_pack_fetch_failed", provider=self.provider, error=type(exc).__name__
            )
            return LocalRankResult(provider=self.provider, error=f"{type(exc).__name__}")
        return _result_from_entries(
            _dfs_items(data), place_id=place_id, business_name=business_name,
            provider=self.provider,
        )


def _dfs_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the maps items out of a DataForSEO envelope defensively.

    The envelope nests ``tasks[].result[].items[]``; any level may be absent on a
    thin/failed task, so every hop is guarded rather than indexed.
    """
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        return []
    first = tasks[0] if isinstance(tasks[0], dict) else {}
    results = first.get("result") or []
    if not isinstance(results, list) or not results:
        return []
    head = results[0] if isinstance(results[0], dict) else {}
    items = head.get("items") or []
    return [item for item in items if isinstance(item, dict)]


class FakeLocalPackProvider:
    """Deterministic, offline ``LocalPackProvider`` - sha256(keyword|geo|business).

    Same inputs => identical result; different inputs differ. Roughly one check in
    five lands OUTSIDE the pack with ``rank=None`` (the honest-absence branch), so a
    keyless test run exercises the NULL contract as well as the ranked path. It never
    returns an ``error`` - a fake has nothing to fail at, and the error branch is
    driven in tests by an explicitly exploding stub instead.
    """

    provider = "fake"
    enabled = True

    def estimated_cost(self) -> float:
        return 0.0

    def rank(
        self, *, keyword: str, geo: str | None, place_id: str | None, business_name: str
    ) -> LocalRankResult:
        seed = f"{keyword}|{geo or ''}|{business_name}".encode()
        digest = hashlib.sha256(seed).hexdigest()
        # 0..9; 8-9 (20%) => not in the pack at all.
        slot = int(digest[:2], 16) % 10
        competitors = [f"{keyword.title()} Co {i}" for i in range(1, _TOP_COMPETITORS + 1)]
        if slot >= 8:
            return LocalRankResult(
                rank=None, in_map_pack=False, found_url="",
                top_competitors=competitors, provider=self.provider,
            )
        position = slot + 1  # 1..8
        return LocalRankResult(
            rank=position,
            in_map_pack=position <= MAP_PACK_SIZE,
            found_url=f"https://example.test/{digest[:8]}",
            top_competitors=competitors,
            provider=self.provider,
        )


def local_pack_provider_from_settings(settings: Settings) -> LocalPackProvider:
    """The map-pack provider for this deploy: the house Serper Places default, the
    DataForSEO Maps fallback, else the deterministic fake (NEVER ``None``).

    Preference order is deliberate: Serper is the key the platform already holds, so
    a live deploy activates local rank with no new vendor. Only the REASON is ever
    logged - never a credential.
    """
    cost = float(settings.local_rank_cost_estimate)
    serper = settings.serper_api_key
    if serper:
        return SerperPlacesProvider(api_key=serper.get_secret_value(), cost=cost)
    dfs_password = settings.dataforseo_password
    if settings.dataforseo_login and dfs_password:
        return DataForSeoMapsProvider(
            login=settings.dataforseo_login,
            password=dfs_password.get_secret_value(),
            cost=cost,
        )
    logger.info("local_pack_provider_degraded", reason="missing_serper_and_dataforseo_keys")
    return FakeLocalPackProvider()
