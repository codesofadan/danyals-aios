"""Citation-monitoring seam (7B): the ONLY door to a business's local directory /
NAP listings.

Local off-page monitoring checks a business's listings across the citation
directories (Google Business, Yelp, Apple Maps, data aggregators, ...) and reports,
per directory, whether the Name/Address/Phone is ``consistent``, has drifted
(``inconsistent``), or is ``missing`` entirely - which drives the Submit-vs-Update
action. Reachable through the ``CitationProvider`` Protocol so a later monitoring
chunk can wrap it in a cost-gated ingest; nothing else calls the provider directly.

Two impls satisfy the Protocol, mirroring the content/backlink seams exactly:

* ``BrightLocalCitations`` - real, backed by a BrightLocal / Whitespark-style
  citation-tracker API over the shared sync ``HttpProviderClient`` (retry/backoff;
  the key rides in an ``api-key`` header, never a URL or a log line). Key-gated on
  ``BRIGHTLOCAL_API_KEY``; an empty key -> ``ProviderNotConfiguredError`` naming the
  fix.
* ``FakeCitationProvider`` - deterministic, network-free: sha256(business) -> a
  stable spread of directories across all three NAP states, so tests + degraded runs
  are reproducible with zero keys.

``classify_citation`` is the shared verdict (not found -> ``missing``; found but NAP
mismatch -> ``inconsistent``; found + match -> ``consistent``) so the DB
``nap_status`` is derived one way from every source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.citations")

_INSTALL_HINT = "set BRIGHTLOCAL_API_KEY to enable live citation / NAP monitoring"
_BRIGHTLOCAL_BASE = "https://api.brightlocal.com"
_DFS_BASE = "https://api.dataforseo.com"
_DFS_HINT = (
    "set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD to enable Business Listings corroboration"
)

# The directories a local citation audit walks (a representative core set).
_CORE_DIRECTORIES = (
    "Google Business",
    "Yelp",
    "Bing Places",
    "Apple Maps",
    "Yellow Pages",
    "Facebook",
)


@dataclass(frozen=True)
class CitationRecord:
    """One directory listing from any source. ``nap_status`` is DERIVED via
    ``classify_citation`` (never trusted raw); ``note`` records what drifted or a
    listing detail.

    Evidence fields (0129): ``url`` is the listing URL the source actually FOUND
    (never a guess - '' when the source has none); ``evidence_level`` is the tier
    ``evidence_level_for`` derives ('' for a source that predates tiers); ``evidence``
    is the receipt ({sources, queries, snippet, nap, classifier}) persisted verbatim
    into ``citations.discovery_evidence`` - the WRITER stamps ``checked_at`` server-side
    at write time, never this record."""

    directory: str
    nap_status: str
    note: str = ""
    url: str = ""
    evidence_level: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)


def classify_citation(*, found: bool, nap_matches: bool) -> str:
    """The NAP verdict for a directory: no listing -> ``missing``; a listing whose
    NAP has drifted -> ``inconsistent``; a listing that matches -> ``consistent``."""
    if not found:
        return "missing"
    return "consistent" if nap_matches else "inconsistent"


# --------------------------------------------------------------------------- #
# Evidence tiers (0129): how much a discovery verdict is actually worth.
# --------------------------------------------------------------------------- #
EVIDENCE_CONFIRMED = "confirmed"
EVIDENCE_INCONSISTENT_NAP = "inconsistent_nap"
EVIDENCE_UNCERTAIN = "uncertain"
EVIDENCE_NO_EVIDENCE = "no_evidence"
#: The closed vocabulary, verbatim from 0129's CHECK ('' = a pre-tier row).
EVIDENCE_LEVELS: frozenset[str] = frozenset(
    {"", EVIDENCE_CONFIRMED, EVIDENCE_INCONSISTENT_NAP, EVIDENCE_UNCERTAIN, EVIDENCE_NO_EVIDENCE}
)


def evidence_level_for(
    *,
    url_found: bool,
    nap_matched: bool | None = None,
    page_fetched: bool = False,
    independent_sources: int = 0,
    hit_found: bool = False,
) -> str:
    """The evidence tier for one discovered listing. PURE - the one rule every source
    derives its tier through, so the DB vocabulary can never drift per provider.

    * ``confirmed``        - a URL was found AND the NAP matched, earned either by an
      actual page fetch OR by >= 2 independent sources corroborating the same listing.
    * ``inconsistent_nap`` - a URL was found but the NAP has DRIFTED (judged from the
      fetched page or the source's own NAP fields).
    * ``uncertain``        - a hit exists but nothing fetched/corroborated it (an
      unfetched snippet, a single unjudged source). Verify before acting on it.
    * ``no_evidence``      - ZERO hits across ALL sources. ABSENCE IS NEVER PROOF:
      this is a *candidate* gap (a directory that blocks crawlers still lists
      businesses), which is why it is a tier and not a fact.

    ``nap_matched`` is tri-state: ``None`` means no judgement was possible, which can
    never reach ``confirmed`` or ``inconsistent_nap``."""
    if url_found:
        if nap_matched is False:
            return EVIDENCE_INCONSISTENT_NAP
        if nap_matched and (page_fetched or independent_sources >= 2):
            return EVIDENCE_CONFIRMED
        return EVIDENCE_UNCERTAIN
    if hit_found:
        return EVIDENCE_UNCERTAIN
    return EVIDENCE_NO_EVIDENCE


@runtime_checkable
class CitationProvider(Protocol):
    """Fetch a business's directory listings as ``CitationRecord``s.

    ``business`` identifies the client (name or a business id the provider resolves).
    """

    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]: ...


class BrightLocalCitations(HttpProviderClient):
    """Real ``CitationProvider`` over a BrightLocal-style citation-tracker API.

    The key rides in the ``api-key`` header (never a URL, never a log line). The
    caller (the factory / service layer) supplies it.
    """

    provider = "brightlocal_citations"

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"BrightLocal citations unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_BRIGHTLOCAL_BASE,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]:
        data = self.request_json(
            "GET", "/v4/ct/results", params={"business": business, "limit": limit}
        )
        return [_record_from_brightlocal(item) for item in _brightlocal_items(data)]


def _brightlocal_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the listing rows out of a BrightLocal envelope defensively."""
    results = data.get("results")
    if isinstance(results, dict):
        results = results.get("citations")
    return [item for item in (results or []) if isinstance(item, dict)]


def _record_from_brightlocal(item: dict[str, Any]) -> CitationRecord:
    """Map one BrightLocal listing to a ``CitationRecord`` (NAP status derived).

    BrightLocal is a purpose-built tracker that has actually OBSERVED the listing, so a
    found row counts as fetched: found + match -> ``confirmed``, found + drift ->
    ``inconsistent_nap``, found with no URL -> ``uncertain``, not found ->
    ``no_evidence`` (a candidate gap, never proof)."""
    found = bool(item.get("found", item.get("listing_url")))
    nap_matches = bool(item.get("nap_match", item.get("is_consistent")))
    url = str(item.get("listing_url") or item.get("url") or "") if found else ""
    return CitationRecord(
        directory=str(item.get("directory") or item.get("source") or ""),
        nap_status=classify_citation(found=found, nap_matches=nap_matches),
        note=str(item.get("note") or item.get("issue") or ""),
        url=url,
        evidence_level=evidence_level_for(
            url_found=bool(url),
            nap_matched=nap_matches if found else None,
            page_fetched=found,
            hit_found=found,
        ),
        evidence={
            "sources": ["brightlocal"],
            "queries": [],
            "snippet": str(item.get("note") or item.get("issue") or ""),
            "nap": {},
            "classifier": "brightlocal",
        },
    )


# --------------------------------------------------------------------------- #
# DataForSEO Business Listings (0129): a POI-database READ used as a second
# canonical-NAP anchor + a corroborating evidence source. NOT a directory scanner -
# absence of a record here is never proof a listing is absent (plan C5).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BusinessListing:
    """One POI record from a business-listings database (name/phone/address/url)."""

    name: str
    phone: str = ""
    address: str = ""
    url: str = ""


class DataForSEOBusinessListings(HttpProviderClient):
    """DataForSEO Business Data API - Business Listings search (READ-only).

    Same ``HttpProviderClient`` pattern as ``BrightLocalCitations`` and the SAME HTTP
    Basic auth as ``DataForSeoBacklinks`` (``DATAFORSEO_LOGIN``/``DATAFORSEO_PASSWORD``,
    handed to httpx per request and NEVER logged). Its role in discovery is strictly
    additive: a second canonical-NAP anchor when Places is keyless/ambiguous, and
    corroboration that can UPGRADE an ``uncertain`` row to ``confirmed``. Its absence
    must change NOTHING except evidence strength - it never contributes candidates.

    ``search`` NEVER raises (the discovery 'never raises' contract): any failure logs
    the provider name only and returns ``[]``, so the source is simply skipped."""

    provider = "dataforseo_business_listings"

    def __init__(self, *, login: str, password: str, timeout: float = 30.0) -> None:
        if not login or not password:
            raise ProviderNotConfiguredError(f"DataForSEO Business Listings unavailable: {_DFS_HINT}")
        super().__init__(
            base_url=_DFS_BASE,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        self._auth = (login, password)

    def search(self, *, name: str, phone: str = "", limit: int = 5) -> list[BusinessListing]:
        """Search the listings database by business name (+ an optional phone filter).

        Never raises: a provider failure returns ``[]`` (that source is skipped)."""
        task: dict[str, Any] = {"title": name, "limit": max(1, min(limit, 20))}
        if phone:
            task["filters"] = ["phone", "=", phone]
        try:
            data = self.request_json(
                "POST",
                "/v3/business_data/business_listings/search/live",
                json_body=[task],
                auth=self._auth,
            )
        except Exception:
            logger.info("dataforseo_business_listings_failed")
            return []
        return [_listing_from_dfs(item) for item in _dfs_listing_items(data)]


def _dfs_listing_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull ``tasks[].result[].items[]`` out of a DataForSEO envelope defensively."""
    items: list[dict[str, Any]] = []
    for task in data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for result in task.get("result") or []:
            if not isinstance(result, dict):
                continue
            for item in result.get("items") or []:
                if isinstance(item, dict):
                    items.append(item)
    return items


def _listing_from_dfs(item: dict[str, Any]) -> BusinessListing:
    """Map one Business Listings item (title/phone/address/url) to a ``BusinessListing``."""
    return BusinessListing(
        name=str(item.get("title") or ""),
        phone=str(item.get("phone") or ""),
        address=str(item.get("address") or ""),
        url=str(item.get("url") or ""),
    )


def dataforseo_listings_from_settings(settings: Settings) -> DataForSEOBusinessListings | None:
    """The optional corroboration source, gated on the DataForSEO credentials exactly
    the way Firecrawl is gated in discovery: present -> a real client, absent -> ``None``
    and discovery proceeds unchanged (merge only ever ADDS evidence)."""
    login = settings.dataforseo_login
    password = settings.dataforseo_password
    if not login or not password:
        return None
    try:
        return DataForSEOBusinessListings(login=login, password=password.get_secret_value())
    except ProviderNotConfiguredError:
        return None


class FakeCitationProvider:
    """Deterministic, offline ``CitationProvider`` - sha256(business) -> a stable
    spread of directories across all three NAP states AND all four evidence tiers.

    Same business => identical records; different businesses differ. The first four
    directories are pinned one-per-tier (confirmed / inconsistent_nap / no_evidence /
    uncertain) so monitoring + gap-analysis tests exercise every evidence branch with
    zero keys; the rest are digest-assigned for stable variety (tier derived from the
    NAP state through the same one rule real sources use).
    """

    #: (nap_status, evidence_level) for the first four directories - one per tier.
    _PINNED: tuple[tuple[str, str], ...] = (
        ("consistent", EVIDENCE_CONFIRMED),
        ("inconsistent", EVIDENCE_INCONSISTENT_NAP),
        ("missing", EVIDENCE_NO_EVIDENCE),
        ("consistent", EVIDENCE_UNCERTAIN),  # a hit that nothing fetched/corroborated
    )

    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]:
        digest = hashlib.sha256(business.encode()).hexdigest()
        states = ("consistent", "inconsistent", "missing")
        notes = {
            "consistent": "Verified",
            "inconsistent": "Suite # differs",
            "missing": "No listing yet",
        }
        records: list[CitationRecord] = []
        for i, directory in enumerate(_CORE_DIRECTORIES[:limit]):
            if i < len(self._PINNED):
                nap, level = self._PINNED[i]
            else:
                nap = states[int(digest[i * 2 : i * 2 + 2] or "0", 16) % 3]
                level = evidence_level_for(
                    url_found=nap != "missing",
                    nap_matched=(nap == "consistent") if nap != "missing" else None,
                    page_fetched=nap != "missing",
                    hit_found=nap != "missing",
                )
            slug = directory.lower().replace(" ", "-")
            url = "" if level == EVIDENCE_NO_EVIDENCE else f"https://{slug}.example/biz/{digest[:8]}"
            records.append(
                CitationRecord(
                    directory=directory,
                    nap_status=nap,
                    note=notes[nap],
                    url=url,
                    evidence_level=level,
                    evidence={
                        "sources": ["fake"],
                        "queries": [business],
                        "snippet": notes[nap],
                        "nap": {"name": business, "phone": "", "address": ""},
                        "classifier": "fake",
                    },
                )
            )
        return records


def citation_provider_from_settings(settings: Settings) -> CitationProvider | None:
    """The live citation-discovery provider for this deploy, by precedence:

    1. ``BrightLocalCitations`` when ``BRIGHTLOCAL_API_KEY`` is set (the purpose-built
       citation tracker, unchanged).
    2. ELSE ``SearchCitationProvider`` when BOTH ``SERPER_API_KEY`` AND
       ``ANTHROPIC_API_KEY`` are present - the BrightLocal REPLACEMENT that discovers a
       business's existing listings from the keys the platform already holds (Serper +
       Places + Foursquare + Claude, Firecrawl optional). This is what makes the citation
       AUDIT find real listings when the client cannot get a BrightLocal key.
    3. ELSE ``None`` (degraded - live discovery is off until a key lands, as before).

    The search provider builds from settings lazily (breaking the import cycle:
    ``citation_discovery`` imports ``CitationRecord``/``classify_citation`` from here).
    Mirrors ``content_providers_from_settings``: no secret is ever logged, only the
    reason."""
    key = settings.brightlocal_api_key
    if key:
        return BrightLocalCitations(api_key=key.get_secret_value())

    if settings.serper_api_key and settings.anthropic_api_key:
        from integrations.citation_discovery import build_search_citation_provider

        provider = build_search_citation_provider(settings)
        if provider is not None:
            logger.info("citation_provider_search_discovery", reason="brightlocal_absent")
            return provider

    logger.info(
        "citation_provider_degraded", reason="missing_brightlocal_and_search_keys"
    )
    return None
