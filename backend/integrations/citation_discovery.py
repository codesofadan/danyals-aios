"""Search-based citation DISCOVERY (the BrightLocal replacement for the AUDIT side).

THE PROBLEM THIS FIXES: ``citation_provider_from_settings`` only returned a REAL
discovery provider when ``BRIGHTLOCAL_API_KEY`` was set. The client cannot get a
BrightLocal key, so in prod the citation AUDIT had NO real discovery - it found 0
existing listings and treated all ~155 catalog directories as ``missing``. But the
platform ALREADY holds Serper, Google Places, Foursquare, Anthropic and (optionally)
Firecrawl keys. This module discovers a business's EXISTING citations from those.

``SearchCitationProvider`` satisfies the SAME ``CitationProvider`` Protocol as
``BrightLocalCitations`` (``fetch_citations(business, *, limit) -> list[CitationRecord]``),
so ``workers.tasks.offpage.run_citation_monitor`` (and the citation-builder audit that
reuses it) consumes it UNCHANGED. The pipeline, given a business name (the Places
anchor resolves the rest of the NAP from it):

1. **Places anchor** - look the business up (a real Google Places key if present, else
   Serper's ``/places``) to get the CANONICAL NAP + the Google Business Profile listing.
   That NAP is the reference every other listing's consistency is judged against, and
   the GBP listing itself is emitted as the anchor citation.
2. **Serper web search** - a few targeted Google searches (exact name + city; the phone
   number; the name scoped to known directory domains) collect result URLs that are
   directory listings of THIS business; each domain maps to a directory name.
3. **Foursquare** - a direct Places read (the Foursquare listing + aggregator feed).
4. **Firecrawl (OPTIONAL)** - when configured, render the top few found listings for
   their EXACT on-page NAP before the consistency judgement; when absent, judge from the
   search snippet + Places anchor.
5. **Claude** - the collected candidates go to Claude under a strict-JSON contract to
   (a) drop false positives (a listing that is NOT this business), (b) assign each a
   directory name, and (c) judge NAP consistency vs the canonical NAP -> a clean
   ``list[CitationRecord]``. If Claude is absent or fails, a deterministic heuristic
   classifier keeps only known-directory listings that match the NAP.

DEGRADE, NEVER CRASH: every sub-call (a provider being down, a bad response, a raising
firecrawl) is caught - that source is skipped and discovery returns whatever it found.
``fetch_citations`` NEVER raises. No secret is ever logged (auth rides in headers).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

from app.logging_setup import get_logger
from integrations.citations import CitationRecord, classify_citation
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

if TYPE_CHECKING:  # typing-only; the real seams are injected, so no runtime import cycle
    from app.config import Settings
    from integrations.content_research import SerpResearcher
    from integrations.firecrawl import Firecrawl
    from integrations.llm import SystemSummarizer

logger = get_logger("integrations.citation_discovery")

_SERPER_BASE = "https://google.serper.dev"
_GOOGLE_PLACES_BASE = "https://places.googleapis.com"
_FOURSQUARE_BASE = "https://api.foursquare.com/v3"

# The canonical GBP listing is emitted under this directory name (matches the core
# directory label the BrightLocal/Fake providers use, so the gap analysis lines up).
_GOOGLE_BUSINESS = "Google Business"

# Domains we never treat as a "citation" candidate: search engines, the business's own
# feeds, and generic content hosts that are not directory listings.
_SKIP_DOMAINS = frozenset(
    {
        "google.com", "www.google.com", "bing.com", "duckduckgo.com",
        "youtube.com", "m.youtube.com", "wikipedia.org", "en.wikipedia.org",
        "reddit.com", "amazon.com", "indeed.com", "glassdoor.com",
    }
)

# A curated domain -> directory-name map covering the common citation directories, so a
# result URL maps to the SAME directory name the catalog (``public.directories``) uses
# where possible. Anything not here is named by Claude (or title-cased from the domain
# in the heuristic fallback), so an unknown directory still gets a sensible label.
_DIRECTORY_DOMAINS: dict[str, str] = {
    "yelp.com": "Yelp",
    "facebook.com": "Facebook",
    "bing.com": "Bing Places",
    "apple.com": "Apple Maps",
    "mapquest.com": "MapQuest",
    "yellowpages.com": "Yellow Pages",
    "yellowpages.ca": "Yellow Pages",
    "bbb.org": "BBB",
    "foursquare.com": "Foursquare",
    "tripadvisor.com": "Tripadvisor",
    "angi.com": "Angi",
    "angieslist.com": "Angi",
    "houzz.com": "Houzz",
    "thumbtack.com": "Thumbtack",
    "nextdoor.com": "Nextdoor",
    "manta.com": "Manta",
    "hotfrog.com": "Hotfrog",
    "citysearch.com": "Citysearch",
    "superpages.com": "Superpages",
    "chamberofcommerce.com": "ChamberofCommerce",
    "brownbook.net": "Brownbook",
    "cylex.us.com": "Cylex",
    "ezlocal.com": "EZlocal",
    "merchantcircle.com": "MerchantCircle",
    "local.com": "Local.com",
    "n49.com": "N49",
    "healthgrades.com": "Healthgrades",
    "zocdoc.com": "Zocdoc",
    "avvo.com": "Avvo",
    "justia.com": "Justia",
    "findlaw.com": "FindLaw",
    "opentable.com": "OpenTable",
}


@dataclass(frozen=True)
class CanonicalNAP:
    """The reference NAP for a business, from the Places anchor. Every discovered
    listing's consistency is judged against this. Empty when no anchor was found - the
    provider then still returns found listings but cannot assert consistency."""

    name: str
    address: str = ""
    city: str = ""
    region: str = ""
    phone: str = ""
    website: str = ""
    place_id: str = ""
    listing_url: str = ""

    @property
    def found(self) -> bool:
        return bool(self.name)


@dataclass(frozen=True)
class FoursquareListing:
    """One Foursquare Places search hit (a citation + the aggregator feed)."""

    name: str
    address: str = ""
    phone: str = ""
    website: str = ""
    fsq_id: str = ""


@dataclass
class _Candidate:
    """One discovery candidate before Claude's keep/classify pass. ``name``/``phone``/
    ``address`` are whatever the source surfaced (a Foursquare field, a Firecrawl scrape,
    or empty for a bare Serper hit); ``snippet`` carries the SERP text Claude reads."""

    source: str
    domain: str
    directory: str
    url: str
    title: str = ""
    snippet: str = ""
    name: str = ""
    phone: str = ""
    address: str = ""


# --------------------------------------------------------------------------- #
# Places anchor seam (canonical NAP + the GBP listing).
# --------------------------------------------------------------------------- #
@runtime_checkable
class PlacesLookup(Protocol):
    """Resolve a business ``query`` to its canonical NAP + Google listing, or ``None``.

    ``geo`` biases the lookup to a locale. Impls MUST NOT raise for a provider-side
    failure - they return ``None`` so discovery degrades to the other sources.
    """

    def lookup(self, query: str, *, geo: str | None = None) -> CanonicalNAP | None: ...


class SerperPlacesLookup(HttpProviderClient):
    """The HOUSE-DEFAULT Places anchor: Serper's ``/places`` endpoint (Google Business
    Profile data), reusing the ``SERPER_API_KEY`` the platform already holds. The key
    rides in the ``X-API-KEY`` header (never a URL, never a log line)."""

    provider = "serper_places_anchor"

    def __init__(self, *, api_key: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(
                "Serper Places anchor unavailable: set SERPER_API_KEY"
            )
        super().__init__(
            base_url=_SERPER_BASE,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def lookup(self, query: str, *, geo: str | None = None) -> CanonicalNAP | None:
        body: dict[str, Any] = {"q": query}
        if geo:
            body["location"] = geo
        try:
            data = self.request_json("POST", "/places", json_body=body)
        except Exception:
            logger.info("places_anchor_failed", provider=self.provider)
            return None
        places = [p for p in (data.get("places") or []) if isinstance(p, dict)]
        if not places:
            return None
        top = places[0]
        cid = str(top.get("cid") or "")
        place_id = str(top.get("placeId") or "")
        return CanonicalNAP(
            name=str(top.get("title") or ""),
            address=str(top.get("address") or ""),
            phone=str(top.get("phoneNumber") or ""),
            website=str(top.get("website") or ""),
            place_id=place_id,
            listing_url=(f"https://www.google.com/maps?cid={cid}" if cid else ""),
        )


class GooglePlacesLookup(HttpProviderClient):
    """The Places anchor over the real Google Places API (New) ``places:searchText``.

    Used when ``GOOGLE_PLACES_API_KEY`` (or the ``GOOGLE_MAPS_API_KEY`` alias) is set.
    Auth rides in the ``X-Goog-Api-Key`` header + a field mask (never a URL query, so a
    stripped-path error line can never echo the key)."""

    provider = "google_places_anchor"

    _FIELD_MASK = (
        "places.id,places.displayName,places.formattedAddress,"
        "places.nationalPhoneNumber,places.internationalPhoneNumber,"
        "places.websiteUri,places.googleMapsUri"
    )

    def __init__(self, *, api_key: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(
                "Google Places anchor unavailable: set GOOGLE_PLACES_API_KEY"
            )
        super().__init__(
            base_url=_GOOGLE_PLACES_BASE,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": self._FIELD_MASK,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def lookup(self, query: str, *, geo: str | None = None) -> CanonicalNAP | None:
        text = f"{query} {geo}".strip() if geo else query
        try:
            data = self.request_json("POST", "/v1/places:searchText", json_body={"textQuery": text})
        except Exception:
            logger.info("places_anchor_failed", provider=self.provider)
            return None
        places = [p for p in (data.get("places") or []) if isinstance(p, dict)]
        if not places:
            return None
        top = places[0]
        display = top.get("displayName")
        name = str(display.get("text")) if isinstance(display, dict) else str(display or "")
        phone = str(top.get("nationalPhoneNumber") or top.get("internationalPhoneNumber") or "")
        return CanonicalNAP(
            name=name,
            address=str(top.get("formattedAddress") or ""),
            phone=phone,
            website=str(top.get("websiteUri") or ""),
            place_id=str(top.get("id") or ""),
            listing_url=str(top.get("googleMapsUri") or ""),
        )


class FakePlacesLookup:
    """Deterministic, offline ``PlacesLookup`` - returns a fixed canonical NAP (or
    ``None`` to exercise the anchorless degrade path). No network."""

    def __init__(self, nap: CanonicalNAP | None = None) -> None:
        self._nap = nap

    def lookup(self, query: str, *, geo: str | None = None) -> CanonicalNAP | None:
        if self._nap is not None:
            return self._nap
        return CanonicalNAP(
            name=query,
            address="123 Main St",
            city="Bellevue",
            region="WA",
            phone="555-0100",
            website="https://example.test",
            place_id="fake-place-id",
            listing_url="https://www.google.com/maps?cid=fake",
        )


# --------------------------------------------------------------------------- #
# Foursquare Places READ seam (a citation + the aggregator feed).
# --------------------------------------------------------------------------- #
@runtime_checkable
class FoursquarePlaces(Protocol):
    """Search Foursquare for a business's listing, or ``None``. Never raises for a
    provider-side failure - returns ``None`` so discovery degrades."""

    def search(self, *, name: str, near: str) -> FoursquareListing | None: ...


class FoursquarePlacesClient(HttpProviderClient):
    """Foursquare v3 Places search (READ). The key rides in the ``Authorization``
    header (Foursquare's convention), never a URL or a log line."""

    provider = "foursquare_places"

    def __init__(self, *, api_key: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(
                "Foursquare Places unavailable: set FOURSQUARE_API_KEY"
            )
        super().__init__(
            base_url=_FOURSQUARE_BASE,
            headers={"Authorization": api_key, "Accept": "application/json"},
            timeout=timeout,
        )

    def search(self, *, name: str, near: str) -> FoursquareListing | None:
        params: dict[str, Any] = {
            "query": name,
            "fields": "fsq_id,name,location,tel,website",
            "limit": 1,
        }
        if near:
            params["near"] = near
        try:
            data = self.request_json("GET", "/places/search", params=params)
        except Exception:
            logger.info("foursquare_places_failed")
            return None
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        if not results:
            return None
        top = results[0]
        raw_loc = top.get("location")
        loc: dict[str, Any] = raw_loc if isinstance(raw_loc, dict) else {}
        return FoursquareListing(
            name=str(top.get("name") or ""),
            address=str(loc.get("formatted_address") or ""),
            phone=str(top.get("tel") or ""),
            website=str(top.get("website") or ""),
            fsq_id=str(top.get("fsq_id") or ""),
        )


class FakeFoursquarePlaces:
    """Deterministic, offline ``FoursquarePlaces`` - a fixed listing (or ``None``)."""

    def __init__(self, listing: FoursquareListing | None = None) -> None:
        self._listing = listing

    def search(self, *, name: str, near: str) -> FoursquareListing | None:
        return self._listing


# --------------------------------------------------------------------------- #
# Helpers (pure) - domain mapping, NAP normalisation, prompt + parse.
# --------------------------------------------------------------------------- #
def _domain_of(url: str) -> str:
    """The registrable-ish host of a URL, lowercased, ``www.`` stripped."""
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _registrable(domain: str) -> str:
    """The last two labels of a host (a cheap eTLD+1 proxy) so ``biz.yelp.com`` and
    ``yelp.com`` map to the same directory. Not a full PSL - good enough for labelling."""
    parts = [p for p in domain.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def directory_for_domain(url: str) -> str:
    """Map a result URL's domain to a directory name: the curated map first (exact host
    then registrable), else a title-cased root. Never empty for a real URL."""
    domain = _domain_of(url)
    if not domain:
        return ""
    if domain in _DIRECTORY_DOMAINS:
        return _DIRECTORY_DOMAINS[domain]
    reg = _registrable(domain)
    if reg in _DIRECTORY_DOMAINS:
        return _DIRECTORY_DOMAINS[reg]
    root = reg.split(".")[0] if reg else domain
    return root.replace("-", " ").title() if root else domain


def _digits(value: str) -> str:
    """Just the digits of a phone string (for a normalised comparison)."""
    return re.sub(r"\D", "", value or "")


def _name_tokens(value: str) -> set[str]:
    """Lowercased word tokens of a business name, dropping trivial connectors."""
    stop = {"the", "and", "of", "llc", "inc", "co", "ltd"}
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t and t not in stop}


# --------------------------------------------------------------------------- #
# The provider.
# --------------------------------------------------------------------------- #
# Strict-JSON contract for the classifier. Claude drops false positives, names each
# directory, and judges NAP consistency against the canonical NAP.
_CLASSIFY_SYSTEM = (
    "You are a local-SEO citation auditor. You are given a business's CANONICAL "
    "name/address/phone/website (the reference) and a list of candidate directory "
    "listings found by search. For EACH candidate decide, strictly, whether it is a "
    "listing of the SAME business (matching name AND phone/address/website - drop a "
    "candidate that is a different business, a generic category/blog page, or the "
    "business's own website). For every candidate you KEEP, assign a short directory "
    "name (use the provided directory hint when it is sensible) and judge its NAP "
    "against the canonical: 'consistent' when name+address+phone match, 'inconsistent' "
    "when the listing exists but a field has drifted. Respond with STRICT JSON ONLY - no "
    "prose, no markdown, no code fences - as an object with ONE key 'citations' whose "
    "value is an array of objects each with EXACTLY these keys: directory (string), "
    "nap_status (one of 'consistent' or 'inconsistent'), note (a short string naming what "
    "drifted, or '' when consistent). Return ONLY genuine listings of this business; "
    "return an empty array if none match. Never invent a listing that was not provided."
)


class SearchCitationProvider:
    """Discover a business's existing citations from Serper + Places + Foursquare +
    Claude (Firecrawl optional). Satisfies the ``CitationProvider`` Protocol so the
    monitor / audit worker consumes it exactly like ``BrightLocalCitations``.

    Every dependency is INJECTED (so the whole pipeline unit-tests on fakes with zero
    network). ``fetch_citations`` is the single entry point and NEVER raises - any
    sub-call failure is caught, that source is skipped, and whatever was discovered is
    returned. No secret is ever logged.
    """

    def __init__(
        self,
        *,
        serp: SerpResearcher,
        places: PlacesLookup | None = None,
        foursquare: FoursquarePlaces | None = None,
        classifier: SystemSummarizer | None = None,
        firecrawl: Firecrawl | None = None,
        geo: str | None = None,
        model: str = "claude-haiku-4-5",
        max_tokens: int = 2000,
        scrape_top_n: int = 2,
    ) -> None:
        self._serp = serp
        self._places = places
        self._foursquare = foursquare
        self._classifier = classifier
        self._firecrawl = firecrawl
        self._geo = geo
        self._model = model
        self._max_tokens = max_tokens
        self._scrape_top_n = max(0, scrape_top_n)

    # -- CitationProvider Protocol ----------------------------------------- #
    def fetch_citations(self, business: str, *, limit: int = 50) -> list[CitationRecord]:
        """Discover ``business``'s existing directory listings as ``CitationRecord``s.

        ``business`` is the business name (optionally 'Name, City'); the Places anchor
        resolves the rest of the NAP from it. Returns FOUND listings (consistent /
        inconsistent) - a catalog directory NOT returned is derived as ``missing`` by the
        gap analysis, exactly as with BrightLocal. Never raises."""
        try:
            return self._discover(business, limit=limit)
        except Exception:  # belt-and-braces: the provider must never crash the audit
            logger.exception("citation_discovery_failed", business=business)
            return []

    # -- internals --------------------------------------------------------- #
    def _discover(self, business: str, *, limit: int) -> list[CitationRecord]:
        anchor = self._anchor(business)
        # The reference NAP the consistency judgement is made against. When Places
        # resolved a listing it IS the anchor; otherwise fall back to just the business
        # name (still a real reference for name matching) so discovery keeps working
        # keyless/anchorless - we simply cannot assert the GBP listing exists.
        reference = anchor if anchor.found else CanonicalNAP(name=_name_hint(business))
        city = anchor.city or _city_hint(business)
        candidates = self._collect_candidates(business, reference, city)
        self._enrich_with_firecrawl(candidates)

        records: list[CitationRecord] = []
        # The Google Business Profile anchor is itself the #1 citation (the canonical
        # source) - emit it consistent ONLY when Places actually resolved one.
        if anchor.found:
            records.append(
                CitationRecord(
                    directory=_GOOGLE_BUSINESS,
                    nap_status="consistent",
                    note="Google Business Profile (canonical NAP)",
                )
            )

        classified = self._classify(reference, candidates)
        records.extend(classified)
        return _dedupe(records, limit=limit)

    def _anchor(self, business: str) -> CanonicalNAP:
        """Resolve the canonical NAP + GBP listing, or an empty NAP (never raises)."""
        if self._places is None:
            return CanonicalNAP(name="")
        try:
            nap = self._places.lookup(business, geo=self._geo)
        except Exception:
            logger.info("places_anchor_error")
            return CanonicalNAP(name="")
        return nap or CanonicalNAP(name="")

    def _collect_candidates(
        self, business: str, canonical: CanonicalNAP, city: str
    ) -> list[_Candidate]:
        """Run the Serper searches + the Foursquare read, mapping each hit to a
        directory candidate (deduped by directory). Each source is independently
        guarded so one failing does not lose the others."""
        name = canonical.name or business
        own_domain = _registrable(_domain_of(canonical.website)) if canonical.website else ""
        by_directory: dict[str, _Candidate] = {}

        for cand in self._serper_candidates(name, city, canonical.phone):
            is_own_site = bool(own_domain) and _registrable(cand.domain) == own_domain
            if cand.domain in _SKIP_DOMAINS or is_own_site:
                continue
            by_directory.setdefault(cand.directory.lower(), cand)

        fsq = self._foursquare_candidate(name, city)
        if fsq is not None:
            by_directory.setdefault(fsq.directory.lower(), fsq)

        return list(by_directory.values())

    def _serper_candidates(self, name: str, city: str, phone: str) -> list[_Candidate]:
        """A few targeted Google searches -> directory-listing candidates. Bounded to a
        handful of queries; each query is guarded (a failure skips just that query)."""
        queries: list[str] = [f'"{name}" {city}'.strip()]
        if phone:
            queries.append(_digits(phone))
        directory_scope = " OR ".join(f"site:{d}" for d in _TOP_DIRECTORY_SITES)
        queries.append(f'{name} {city} ({directory_scope})'.strip())

        out: list[_Candidate] = []
        seen_urls: set[str] = set()
        for query in queries:
            if not query:
                continue
            try:
                result = self._serp.serp(query, self._geo)
            except Exception:
                logger.info("citation_discovery_serp_failed")
                continue
            for organic in result.organic:
                url = organic.link
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                domain = _domain_of(url)
                if not domain:
                    continue
                out.append(
                    _Candidate(
                        source="serper",
                        domain=domain,
                        directory=directory_for_domain(url),
                        url=url,
                        title=organic.title,
                        snippet=organic.snippet or "",
                    )
                )
        return out

    def _foursquare_candidate(self, name: str, city: str) -> _Candidate | None:
        if self._foursquare is None:
            return None
        try:
            listing = self._foursquare.search(name=name, near=city)
        except Exception:
            logger.info("citation_discovery_foursquare_failed")
            return None
        if listing is None or not listing.name:
            return None
        url = (
            f"https://foursquare.com/v/{listing.fsq_id}" if listing.fsq_id else "https://foursquare.com"
        )
        return _Candidate(
            source="foursquare",
            domain="foursquare.com",
            directory="Foursquare",
            url=url,
            title=listing.name,
            snippet=f"{listing.address} {listing.phone}".strip(),
            name=listing.name,
            phone=listing.phone,
            address=listing.address,
        )

    def _enrich_with_firecrawl(self, candidates: list[_Candidate]) -> None:
        """OPTIONAL: render the top few listings for their exact on-page NAP text and
        fold it into the candidate snippet Claude reads. Best-effort + never raises."""
        if self._firecrawl is None or self._scrape_top_n == 0 or not candidates:
            return
        targets = [c for c in candidates if c.url][: self._scrape_top_n]
        if not targets:
            return
        try:
            import asyncio

            scraped = asyncio.run(_scrape_markdown(self._firecrawl, [c.url for c in targets]))
        except Exception:
            logger.info("citation_discovery_firecrawl_skipped")
            return
        for cand in targets:
            text = scraped.get(cand.url)
            if text:
                cand.snippet = f"{cand.snippet} {text}".strip()

    def _classify(
        self, canonical: CanonicalNAP, candidates: list[_Candidate]
    ) -> list[CitationRecord]:
        """Claude keeps genuine listings + judges NAP; falls back to a deterministic
        heuristic when Claude is absent or fails. Never raises."""
        if not candidates:
            return []
        if self._classifier is not None:
            claude = self._classify_with_claude(canonical, candidates)
            if claude is not None:
                return claude
        return _heuristic_records(canonical, candidates)

    def _classify_with_claude(
        self, canonical: CanonicalNAP, candidates: list[_Candidate]
    ) -> list[CitationRecord] | None:
        """One Claude call under the strict-JSON contract, or ``None`` on any failure
        (so the caller falls back to the heuristic)."""
        prompt = _build_classify_prompt(canonical, candidates)
        classifier = self._classifier
        if classifier is None:
            return None
        try:
            result = classifier.summarize(
                prompt, model=self._model, max_tokens=self._max_tokens, system=_CLASSIFY_SYSTEM
            )
        except Exception:
            logger.info("citation_discovery_classify_failed")
            return None
        parsed = _parse_classify_response(result.text)
        if parsed is None:
            logger.info("citation_discovery_classify_unparseable")
            return None
        return parsed


# --------------------------------------------------------------------------- #
# Module-level pure helpers (prompt build / response parse / heuristic / dedupe).
# --------------------------------------------------------------------------- #
# The directory domains the Serper directory-scoped query targets (a small, high-signal
# set - the query stays one bounded call).
_TOP_DIRECTORY_SITES = (
    "yelp.com", "facebook.com", "yellowpages.com", "bbb.org", "mapquest.com", "foursquare.com",
)


def _city_hint(business: str) -> str:
    """A best-effort city from a 'Name, City' business string (else empty)."""
    if "," in business:
        return business.split(",", 1)[1].strip()
    return ""


def _name_hint(business: str) -> str:
    """The business NAME from a 'Name, City' string (the part before the first comma)."""
    return business.split(",", 1)[0].strip() if "," in business else business.strip()


async def _scrape_markdown(firecrawl: Firecrawl, urls: list[str]) -> dict[str, str]:
    """Render each URL via the injected Firecrawl seam and return {url: bounded markdown}.

    Uses its own short-lived ``httpx.AsyncClient`` (this runs from the sync worker, off
    the app lifespan). Each scrape is individually guarded; a failure just omits that URL.
    """
    import httpx

    out: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http:
        for url in urls:
            try:
                page = await firecrawl.scrape(http, url, want_screenshot=False)
            except Exception:
                continue
            if page is not None and page.markdown:
                out[url] = page.markdown[:2000]
    return out


def _build_classify_prompt(canonical: CanonicalNAP, candidates: list[_Candidate]) -> str:
    """The user turn: the canonical NAP + the candidate listings as compact JSON."""
    ref = {
        "name": canonical.name,
        "address": canonical.address,
        "city": canonical.city,
        "region": canonical.region,
        "phone": canonical.phone,
        "website": canonical.website,
    }
    items = [
        {
            "directory_hint": c.directory,
            "domain": c.domain,
            "url": c.url,
            "title": c.title,
            "snippet": c.snippet[:600],
            "name": c.name,
            "phone": c.phone,
            "address": c.address,
        }
        for c in candidates
    ]
    return (
        "CANONICAL BUSINESS (reference NAP):\n"
        + json.dumps(ref, ensure_ascii=False)
        + "\n\nCANDIDATE LISTINGS:\n"
        + json.dumps(items, ensure_ascii=False)
        + "\n\nReturn the strict-JSON object described in the system prompt."
    )


def _parse_classify_response(text: str) -> list[CitationRecord] | None:
    """Parse Claude's strict-JSON reply into records, or ``None`` if unparseable.

    Tolerant of code fences / leading prose: extracts the first JSON object. Each item's
    ``nap_status`` is re-normalised through ``classify_citation`` (found=True), so a bad
    value can never write a raw, unvalidated status."""
    blob = _extract_json_object(text)
    if blob is None:
        return None
    try:
        payload = json.loads(blob)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_items = payload.get("citations")
    if not isinstance(raw_items, list):
        return None
    records: list[CitationRecord] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        directory = str(item.get("directory") or "").strip()
        if not directory:
            continue
        matches = str(item.get("nap_status") or "").strip().lower() == "consistent"
        records.append(
            CitationRecord(
                directory=directory,
                nap_status=classify_citation(found=True, nap_matches=matches),
                note=str(item.get("note") or "").strip(),
            )
        )
    return records


def _extract_json_object(text: str) -> str | None:
    """The first balanced ``{...}`` block in ``text`` (strips fences / prose), or ``None``."""
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _heuristic_records(canonical: CanonicalNAP, candidates: list[_Candidate]) -> list[CitationRecord]:
    """Deterministic fallback when Claude is absent/failed: keep candidates on a KNOWN
    directory domain that plausibly match the canonical business (name-token overlap OR a
    phone match), and judge consistency by a phone/name match. Unknown-domain candidates
    are dropped (too risky to keep without Claude). Never raises."""
    ref_tokens = _name_tokens(canonical.name)
    ref_phone = _digits(canonical.phone)
    out: list[CitationRecord] = []
    for cand in candidates:
        known = _domain_of(cand.url) in _DIRECTORY_DOMAINS or _registrable(cand.domain) in _DIRECTORY_DOMAINS
        if not known:
            continue
        hay = f"{cand.title} {cand.snippet} {cand.name}"
        cand_tokens = _name_tokens(hay)
        cand_phone = _digits(f"{cand.phone} {cand.snippet}")
        name_overlap = bool(ref_tokens & cand_tokens)
        phone_hit = bool(ref_phone) and ref_phone in cand_phone
        if not (name_overlap or phone_hit):
            continue  # a listing we cannot tie to this business -> drop (false positive)
        nap_matches = (phone_hit and name_overlap) if ref_phone else name_overlap
        out.append(
            CitationRecord(
                directory=cand.directory,
                nap_status=classify_citation(found=True, nap_matches=nap_matches),
                note="" if nap_matches else "NAP differs from canonical",
            )
        )
    return out


def _dedupe(records: list[CitationRecord], *, limit: int) -> list[CitationRecord]:
    """One record per directory (first wins), capped at ``limit``."""
    seen: set[str] = set()
    out: list[CitationRecord] = []
    for rec in records:
        key = rec.directory.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(rec)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# Factory (key-gated assembly). Lazily imports the real seams so importing this
# module stays free at the base gate and there is no import cycle with citations.py.
# --------------------------------------------------------------------------- #
def build_search_citation_provider(settings: Settings) -> SearchCitationProvider | None:
    """Assemble a ``SearchCitationProvider`` from the wired keys, or ``None`` when the
    essential ones (Serper for search + Anthropic for the classifier) are absent.

    The Places anchor prefers a real Google Places key, else Serper's ``/places``.
    Foursquare + Firecrawl are OPTIONAL enrichment (added per key). Constructing the
    Anthropic classifier lazily imports the SDK; if it is genuinely absent the whole
    provider degrades to ``None`` (no keyless discovery). No secret is ever logged."""
    from integrations.content_research import SerperResearcher
    from integrations.firecrawl import firecrawl_from_settings
    from integrations.llm import AnthropicSummarizer

    serper_key = settings.serper_api_key
    anthropic_key = settings.anthropic_api_key
    if not serper_key or not anthropic_key:
        logger.info("citation_provider_degraded", reason="missing_serper_or_anthropic_key")
        return None

    try:
        classifier: SystemSummarizer = AnthropicSummarizer(
            api_key=anthropic_key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
            model_heavy=settings.anthropic_model_heavy,
        )
    except ProviderNotConfiguredError as exc:
        # The [ai] SDK is not installed -> no classifier -> degrade cleanly (reason only).
        logger.info("citation_provider_degraded", reason=str(exc))
        return None

    serp = SerperResearcher(api_key=serper_key.get_secret_value())

    places = _build_places_anchor(settings, serper_key.get_secret_value())
    foursquare = _build_foursquare(settings)
    firecrawl = firecrawl_from_settings(settings)

    return SearchCitationProvider(
        serp=serp,
        places=places,
        foursquare=foursquare,
        classifier=classifier,
        firecrawl=firecrawl,
        model=settings.anthropic_model_summary,
    )


def _build_places_anchor(settings: Settings, serper_key: str) -> PlacesLookup:
    """A real Google Places anchor when a Google key is set, else the Serper `/places`
    house default (we already hold the Serper key)."""
    google_key = settings.google_places_api_key or settings.google_maps_api_key
    if google_key:
        try:
            return GooglePlacesLookup(api_key=google_key.get_secret_value())
        except ProviderNotConfiguredError:
            pass
    return SerperPlacesLookup(api_key=serper_key)


def _build_foursquare(settings: Settings) -> FoursquarePlaces | None:
    """A real Foursquare Places reader when its key is set, else ``None`` (skipped)."""
    key = settings.foursquare_api_key
    if not key:
        return None
    try:
        return FoursquarePlacesClient(api_key=key.get_secret_value())
    except ProviderNotConfiguredError:
        return None
