"""Unit gate for the search-based citation DISCOVERY provider (the BrightLocal
replacement). No network, no keys, no AI SDK - every seam is a deterministic fake.

Proves:
* ``SearchCitationProvider`` returns ``CitationRecord``s with the right directory names
  + NAP verdicts (consistent / inconsistent), emits the Google Business anchor, and the
  false positive (a different business) is DROPPED.
* the same works on the deterministic HEURISTIC path (no classifier).
* a raising sub-provider (Places / Serper / Foursquare / classifier) DEGRADES - the
  provider returns whatever it found and NEVER raises.
* ``citation_provider_from_settings`` precedence: BrightLocal wins when set; else the
  search provider when Serper+Anthropic are present and BrightLocal is absent; else None.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import Settings
from integrations.citation_discovery import (
    BusinessListings,
    CanonicalNAP,
    FakeBusinessListings,
    FakeFoursquarePlaces,
    FakePlacesLookup,
    FoursquareListing,
    FoursquarePlaces,
    FoursquarePlacesClient,
    GooglePlacesLookup,
    PlacesLookup,
    SearchCitationProvider,
    SerperPlacesLookup,
    build_search_citation_provider,
    directory_for_domain,
)
from integrations.citations import (
    BrightLocalCitations,
    BusinessListing,
    CitationProvider,
    CitationRecord,
    DataForSEOBusinessListings,
    citation_provider_from_settings,
)
from integrations.content_research import OrganicResult, SerpResult
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes (deterministic, network-free).
# --------------------------------------------------------------------------- #
_CANONICAL = CanonicalNAP(
    name="Verde Cafe",
    address="123 Main St, Bellevue, WA 98004",
    city="Bellevue",
    region="WA",
    phone="555-0100",
    website="https://verdecafe.example",
    place_id="pid-1",
    listing_url="https://www.google.com/maps?cid=1",
)

# A canned SERP with: a genuine Yelp listing (phone matches -> consistent), a genuine
# YellowPages listing (phone drifted -> inconsistent), a FALSE POSITIVE (a different
# business), the business's OWN website (skipped pre-classify), and a search-engine URL
# (skipped as a non-directory domain).
_SERP_ORGANIC = [
    OrganicResult(
        position=1,
        title="Verde Cafe - Bellevue | Yelp",
        link="https://www.yelp.com/biz/verde-cafe-bellevue",
        snippet="Verde Cafe, 123 Main St, Bellevue WA. Call 555-0100 to reserve.",
    ),
    OrganicResult(
        position=2,
        title="Verde Cafe | YellowPages Bellevue",
        link="https://www.yellowpages.com/bellevue-wa/mip/verde-cafe",
        snippet="Verde Cafe in Bellevue. Phone 555-0199.",  # drifted phone
    ),
    OrganicResult(
        position=3,
        title="Blue Ocean Diner - Seattle | Tripadvisor",  # DIFFERENT business
        link="https://www.tripadvisor.com/Restaurant_Review-blue-ocean",
        snippet="Blue Ocean Diner, 900 Pike St, Seattle WA. 555-7777.",
    ),
    OrganicResult(
        position=4,
        title="About - Verde Cafe",  # the business's OWN website
        link="https://verdecafe.example/about",
        snippet="Our story and hours.",
    ),
    OrganicResult(
        position=5,
        title="verde cafe - Google Search",  # non-directory / skip domain
        link="https://www.google.com/search?q=verde+cafe",
        snippet="...",
    ),
]

_FOURSQUARE = FoursquareListing(
    name="Verde Cafe",
    address="123 Main St, Bellevue, WA",
    phone="555-0100",
    website="https://verdecafe.example",
    fsq_id="fsq-abc",
)


class StubSerp:
    """A ``SerpResearcher`` returning a fixed SERP for every query (dedup by URL in the
    provider collapses the repeats). ``raises`` makes ``serp`` blow up to prove degrade."""

    def __init__(self, *, organic: list[OrganicResult] | None = None, raises: bool = False) -> None:
        self._organic = _SERP_ORGANIC if organic is None else organic
        self._raises = raises
        self.calls = 0

    def serp(self, keyword: str, geo: str | None = None) -> SerpResult:
        self.calls += 1
        if self._raises:
            raise RuntimeError("serper down")
        return SerpResult(keyword=keyword, geo=geo, organic=list(self._organic))

    def keyword_metrics(self, keyword: str) -> Any:  # pragma: no cover - unused here
        raise NotImplementedError


class RaisingPlaces:
    def lookup(self, query: str, *, geo: str | None = None) -> CanonicalNAP | None:
        raise RuntimeError("places down")


class RaisingFoursquare:
    def search(self, *, name: str, near: str) -> FoursquareListing | None:
        raise RuntimeError("foursquare down")


class FakeClaude:
    """A deterministic ``SystemSummarizer`` standing in for Anthropic. It PARSES the
    candidate listings out of the strict-JSON prompt and echoes a classification:

    * KEEP a candidate only when its title/name token-overlaps the canonical name (so a
      different business is DROPPED as a false positive);
    * mark it 'consistent' when the canonical phone digits appear in the candidate text,
      else 'inconsistent'.

    ``raises`` makes it blow up to prove the provider falls back to the heuristic."""

    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises
        self.calls = 0
        self.last_prompt = ""

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
    ) -> LLMResult:
        self.calls += 1
        self.last_prompt = prompt
        if self._raises:
            raise RuntimeError("anthropic down")
        ref = _section_json(prompt, "reference NAP):\n")
        items = _section_json(prompt, "CANDIDATE LISTINGS:\n")
        ref_tokens = _tokens(str(ref.get("name", "")))
        ref_phone = _only_digits(str(ref.get("phone", "")))
        citations: list[dict[str, str]] = []
        for item in items:
            text = f"{item.get('title', '')} {item.get('name', '')}"
            if not (ref_tokens & _tokens(text)):
                continue  # different business -> drop
            haystack = _only_digits(
                f"{item.get('snippet', '')} {item.get('phone', '')} {item.get('address', '')}"
            )
            consistent = bool(ref_phone) and ref_phone in haystack
            citations.append(
                {
                    "directory": str(item.get("directory_hint") or ""),
                    "nap_status": "consistent" if consistent else "inconsistent",
                    "note": "" if consistent else "phone/address differs",
                }
            )
        payload = json.dumps({"citations": citations})
        return LLMResult(text=payload, input_tokens=len(prompt) // 4, output_tokens=len(payload) // 4)


def _tokens(value: str) -> set[str]:
    import re

    stop = {"the", "and", "of", "llc", "inc", "co", "ltd"}
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t and t not in stop}


def _only_digits(value: str) -> str:
    import re

    return re.sub(r"\D", "", value)


def _section_json(prompt: str, marker: str) -> Any:
    idx = prompt.index(marker) + len(marker)
    blob = prompt[idx:].split("\n\n", 1)[0]
    return json.loads(blob)


def _by_directory(records: list[CitationRecord]) -> dict[str, CitationRecord]:
    return {r.directory: r for r in records}


# --------------------------------------------------------------------------- #
# Protocol conformance.
# --------------------------------------------------------------------------- #
def test_search_provider_satisfies_citation_provider_protocol() -> None:
    provider = SearchCitationProvider(serp=StubSerp())
    assert isinstance(provider, CitationProvider)


def test_real_seams_satisfy_their_protocols_network_free() -> None:
    # Construction only builds an httpx.Client - no network.
    assert isinstance(SerperPlacesLookup(api_key="k"), PlacesLookup)
    assert isinstance(GooglePlacesLookup(api_key="k"), PlacesLookup)
    assert isinstance(FoursquarePlacesClient(api_key="k"), FoursquarePlaces)
    assert isinstance(FakePlacesLookup(), PlacesLookup)
    assert isinstance(FakeFoursquarePlaces(), FoursquarePlaces)


# --------------------------------------------------------------------------- #
# The Claude path: right directories + verdicts, GBP anchor, false positive dropped.
# --------------------------------------------------------------------------- #
def test_discovery_classifies_and_drops_false_positive() -> None:
    claude = FakeClaude()
    provider = SearchCitationProvider(
        serp=StubSerp(),
        places=FakePlacesLookup(_CANONICAL),
        foursquare=FakeFoursquarePlaces(_FOURSQUARE),
        classifier=claude,
    )
    records = provider.fetch_citations("Verde Cafe")
    by_dir = _by_directory(records)

    # The Google Business Profile anchor is emitted as the canonical #1 citation.
    assert by_dir["Google Business"].nap_status == "consistent"
    # Genuine listings mapped to the catalog directory names, with correct verdicts.
    assert by_dir["Yelp"].nap_status == "consistent"  # phone matches canonical
    assert by_dir["Yellow Pages"].nap_status == "inconsistent"  # phone drifted
    assert by_dir["Foursquare"].nap_status == "consistent"  # from the Foursquare read
    # The different business (Tripadvisor / Blue Ocean Diner) is dropped, own-site +
    # search-engine URLs never became candidates.
    assert "Tripadvisor" not in by_dir
    assert all(isinstance(r, CitationRecord) for r in records)
    assert claude.calls == 1  # exactly one classify call for the whole candidate set


def test_discovery_passes_only_real_candidates_to_claude() -> None:
    claude = FakeClaude()
    provider = SearchCitationProvider(
        serp=StubSerp(), places=FakePlacesLookup(_CANONICAL),
        foursquare=FakeFoursquarePlaces(_FOURSQUARE), classifier=claude,
    )
    provider.fetch_citations("Verde Cafe")
    items = _section_json(claude.last_prompt, "CANDIDATE LISTINGS:\n")
    domains = {i["domain"] for i in items}
    # The own website + the google.com search URL were filtered BEFORE Claude ever saw
    # them; the directory candidates (incl. the false positive, which Claude drops) are
    # the only ones passed.
    assert "verdecafe.example" not in domains
    assert "google.com" not in domains
    assert {"yelp.com", "yellowpages.com", "tripadvisor.com", "foursquare.com"} <= domains


# --------------------------------------------------------------------------- #
# The heuristic path (no classifier) also classifies + drops the false positive.
# --------------------------------------------------------------------------- #
def test_heuristic_path_without_classifier() -> None:
    provider = SearchCitationProvider(
        serp=StubSerp(),
        places=FakePlacesLookup(_CANONICAL),
        foursquare=FakeFoursquarePlaces(_FOURSQUARE),
        classifier=None,  # forces the deterministic heuristic
    )
    by_dir = _by_directory(provider.fetch_citations("Verde Cafe"))
    assert by_dir["Google Business"].nap_status == "consistent"
    assert by_dir["Yelp"].nap_status == "consistent"
    assert by_dir["Yellow Pages"].nap_status == "inconsistent"
    assert by_dir["Foursquare"].nap_status == "consistent"
    assert "Tripadvisor" not in by_dir  # no name/phone tie -> dropped even without Claude


# --------------------------------------------------------------------------- #
# Degrade-not-crash: a raising sub-provider returns partial, never raises.
# --------------------------------------------------------------------------- #
def test_raising_foursquare_degrades_to_partial() -> None:
    provider = SearchCitationProvider(
        serp=StubSerp(), places=FakePlacesLookup(_CANONICAL),
        foursquare=RaisingFoursquare(), classifier=FakeClaude(),
    )
    by_dir = _by_directory(provider.fetch_citations("Verde Cafe"))
    # Foursquare blew up -> skipped; the Serper-found listings + the anchor still land.
    assert "Foursquare" not in by_dir
    assert {"Google Business", "Yelp", "Yellow Pages"} <= set(by_dir)


def test_raising_serper_degrades_to_places_plus_foursquare() -> None:
    provider = SearchCitationProvider(
        serp=StubSerp(raises=True), places=FakePlacesLookup(_CANONICAL),
        foursquare=FakeFoursquarePlaces(_FOURSQUARE), classifier=FakeClaude(),
    )
    by_dir = _by_directory(provider.fetch_citations("Verde Cafe"))
    # Serper down -> no web candidates, but the anchor + the Foursquare read survive.
    assert {"Google Business", "Foursquare"} <= set(by_dir)
    assert "Yelp" not in by_dir


def test_raising_places_degrades_without_anchor() -> None:
    provider = SearchCitationProvider(
        serp=StubSerp(), places=RaisingPlaces(),
        foursquare=FakeFoursquarePlaces(_FOURSQUARE), classifier=FakeClaude(),
    )
    records = provider.fetch_citations("Verde Cafe")
    by_dir = _by_directory(records)
    # Places blew up -> no canonical anchor, but discovery still returns found listings.
    assert "Google Business" not in by_dir
    assert "Yelp" in by_dir  # classified from the SERP snippet alone


def test_raising_classifier_falls_back_to_heuristic() -> None:
    provider = SearchCitationProvider(
        serp=StubSerp(), places=FakePlacesLookup(_CANONICAL),
        foursquare=FakeFoursquarePlaces(_FOURSQUARE), classifier=FakeClaude(raises=True),
    )
    by_dir = _by_directory(provider.fetch_citations("Verde Cafe"))
    # Claude raised -> heuristic classifier still returns the genuine listings.
    assert by_dir["Yelp"].nap_status == "consistent"
    assert by_dir["Yellow Pages"].nap_status == "inconsistent"
    assert "Tripadvisor" not in by_dir


def test_everything_raising_never_raises_and_returns_anchor_only() -> None:
    provider = SearchCitationProvider(
        serp=StubSerp(raises=True), places=FakePlacesLookup(_CANONICAL),
        foursquare=RaisingFoursquare(), classifier=FakeClaude(raises=True),
    )
    records = provider.fetch_citations("Verde Cafe")  # must not raise
    assert _by_directory(records)["Google Business"].nap_status == "consistent"


# --------------------------------------------------------------------------- #
# Evidence tiers + discovered URLs (0129): discovery stops discarding what it found.
# --------------------------------------------------------------------------- #
def _provider(**over: Any) -> SearchCitationProvider:
    kwargs: dict[str, Any] = {
        "serp": StubSerp(),
        "places": FakePlacesLookup(_CANONICAL),
        "foursquare": FakeFoursquarePlaces(_FOURSQUARE),
        "classifier": FakeClaude(),
    }
    kwargs.update(over)
    return SearchCitationProvider(**kwargs)


def test_discovery_threads_the_found_url_into_the_record() -> None:
    by_dir = _by_directory(_provider().fetch_citations("Verde Cafe"))
    assert by_dir["Yelp"].url == "https://www.yelp.com/biz/verde-cafe-bellevue"
    assert by_dir["Yellow Pages"].url == "https://www.yellowpages.com/bellevue-wa/mip/verde-cafe"
    assert by_dir["Foursquare"].url == "https://foursquare.com/v/fsq-abc"
    assert by_dir["Google Business"].url == _CANONICAL.listing_url


def test_discovery_assigns_honest_evidence_tiers() -> None:
    by_dir = _by_directory(_provider().fetch_citations("Verde Cafe"))
    # The Places anchor is a direct read of the listing's own data -> confirmed.
    assert by_dir["Google Business"].evidence_level == "confirmed"
    # Yelp: ONE unfetched Serper snippet agreeing with the NAP is a hint, not a fact.
    assert by_dir["Yelp"].evidence_level == "uncertain"
    # Yellow Pages: the listing exists, its phone drifted.
    assert by_dir["Yellow Pages"].evidence_level == "inconsistent_nap"
    # Foursquare: the API read IS a fetch of the listing's own NAP -> confirmed.
    assert by_dir["Foursquare"].evidence_level == "confirmed"


def test_discovery_records_carry_the_evidence_receipt() -> None:
    by_dir = _by_directory(_provider().fetch_citations("Verde Cafe"))
    evidence = by_dir["Yelp"].evidence
    assert evidence["sources"] == ["serper"]
    assert evidence["queries"], "the query that surfaced the hit must be recorded"
    assert "555-0100" in evidence["snippet"] or "Verde" in evidence["snippet"]
    assert evidence["classifier"] == "claude"
    assert set(evidence["nap"]) == {"name", "phone", "address"}
    # checked_at is stamped SERVER-SIDE at write time (the worker), never here.
    assert "checked_at" not in evidence


# --------------------------------------------------------------------------- #
# DataForSEO corroboration (0129): strictly additive evidence, never candidates.
# --------------------------------------------------------------------------- #
_DFS_MATCH = BusinessListing(
    name="Verde Cafe", phone="555-0100", address="123 Main St, Bellevue, WA 98004",
    url="https://verdecafe.example",
)


class _RaisingListings:
    def search(self, *, name: str, phone: str = "", limit: int = 5) -> list[BusinessListing]:
        raise RuntimeError("dataforseo down")


def test_dataforseo_absence_yields_identical_candidates_and_never_stronger_tiers() -> None:
    """THE INVARIANT: a result set WITHOUT dataforseo has exactly the same candidates,
    and each tier is identical-or-weaker - merge only ever ADDS evidence."""
    without = _by_directory(_provider(listings=None).fetch_citations("Verde Cafe"))
    with_dfs = _by_directory(
        _provider(listings=FakeBusinessListings([_DFS_MATCH])).fetch_citations("Verde Cafe")
    )
    # Identical candidate sets: the POI database contributes ZERO directories.
    assert set(without) == set(with_dfs)
    for directory, record in without.items():
        upgraded = with_dfs[directory]
        assert record.nap_status == upgraded.nap_status  # verdicts never move
        assert record.url == upgraded.url
        # identical-or-weaker without: the only legal difference is the
        # uncertain -> confirmed upgrade corroboration buys.
        assert (record.evidence_level == upgraded.evidence_level) or (
            record.evidence_level == "uncertain" and upgraded.evidence_level == "confirmed"
        )


def test_dataforseo_corroboration_upgrades_uncertain_to_confirmed() -> None:
    by_dir = _by_directory(
        _provider(listings=FakeBusinessListings([_DFS_MATCH])).fetch_citations("Verde Cafe")
    )
    # Yelp was a single unfetched snippet (uncertain); the POI record independently
    # confirming the canonical NAP is the second source -> confirmed.
    assert by_dir["Yelp"].evidence_level == "confirmed"
    assert "dataforseo" in by_dir["Yelp"].evidence["sources"]
    # A DRIFTED listing is never talked back into confirmed by corroboration.
    assert by_dir["Yellow Pages"].evidence_level == "inconsistent_nap"
    assert "dataforseo" not in by_dir["Yellow Pages"].evidence["sources"]


def test_a_different_branch_listing_corroborates_nothing() -> None:
    other_branch = BusinessListing(name="Verde Cafe", phone="555-9999")
    by_dir = _by_directory(
        _provider(listings=FakeBusinessListings([other_branch])).fetch_citations("Verde Cafe")
    )
    assert by_dir["Yelp"].evidence_level == "uncertain"  # same name, different phone


def test_a_raising_listings_source_degrades_and_never_raises() -> None:
    by_dir = _by_directory(_provider(listings=_RaisingListings()).fetch_citations("Verde Cafe"))
    assert by_dir["Yelp"].evidence_level == "uncertain"  # no corroboration, no crash


def test_dataforseo_business_listings_satisfies_the_protocol() -> None:
    assert isinstance(DataForSEOBusinessListings(login="l", password="p"), BusinessListings)
    assert isinstance(FakeBusinessListings(), BusinessListings)


def test_dataforseo_business_listings_search_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'never raises' contract: a provider failure logs + returns [] (skipped)."""
    client = DataForSEOBusinessListings(login="l", password="p")

    def _boom(*a: Any, **k: Any) -> dict[str, Any]:
        raise RuntimeError("dataforseo down")

    monkeypatch.setattr(client, "request_json", _boom)
    assert client.search(name="Verde Cafe", phone="555-0100") == []


def test_dataforseo_business_listings_parses_the_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DataForSEOBusinessListings(login="l", password="p")
    sent: dict[str, Any] = {}

    def _canned(method: str, url: str, **kw: Any) -> dict[str, Any]:
        sent["method"], sent["url"], sent["body"] = method, url, kw.get("json_body")
        return {
            "tasks": [
                {
                    "result": [
                        {
                            "items": [
                                {
                                    "title": "Verde Cafe",
                                    "phone": "555-0100",
                                    "address": "123 Main St, Bellevue, WA 98004",
                                    "url": "https://verdecafe.example",
                                },
                                "not-a-dict",
                            ]
                        }
                    ]
                }
            ]
        }

    monkeypatch.setattr(client, "request_json", _canned)
    out = client.search(name="Verde Cafe", phone="555-0100")
    assert out == [_DFS_MATCH]
    assert sent["method"] == "POST"
    assert sent["url"] == "/v3/business_data/business_listings/search/live"
    assert sent["body"][0]["title"] == "Verde Cafe"
    assert sent["body"][0]["filters"] == ["phone", "=", "555-0100"]


# --------------------------------------------------------------------------- #
# Directory-name mapping.
# --------------------------------------------------------------------------- #
def test_directory_for_domain_maps_and_falls_back() -> None:
    assert directory_for_domain("https://www.yelp.com/biz/x") == "Yelp"
    assert directory_for_domain("https://biz.yellowpages.com/x") == "Yellow Pages"  # subdomain
    assert directory_for_domain("https://www.somedir.io/listing/x") == "Somedir"  # title-cased root
    assert directory_for_domain("not a url") == ""


# --------------------------------------------------------------------------- #
# Factory precedence: BrightLocal > search provider > None.
# --------------------------------------------------------------------------- #
def _settings(**overrides: object) -> Settings:
    # Keyless means KEYLESS: app.main's import-time apply_provider_env exports the
    # real ANTHROPIC_API_KEY into os.environ on a keyed dev box, and
    # pydantic-settings reads os.environ even with _env_file=None.
    overrides.setdefault("anthropic_api_key", None)
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_factory_selects_search_provider_when_serper_and_anthropic_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Avoid the real anthropic SDK: the classifier construction is monkeypatched to a fake.
    monkeypatch.setattr("integrations.llm.AnthropicSummarizer", lambda **_k: FakeClaude())
    provider = citation_provider_from_settings(
        _settings(serper_api_key="sk", anthropic_api_key="ak")
    )
    assert isinstance(provider, SearchCitationProvider)


def test_factory_brightlocal_still_wins_when_its_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("integrations.llm.AnthropicSummarizer", lambda **_k: FakeClaude())
    provider = citation_provider_from_settings(
        _settings(brightlocal_api_key="bl", serper_api_key="sk", anthropic_api_key="ak")
    )
    assert isinstance(provider, BrightLocalCitations)


def test_factory_degrades_to_none_when_neither_key_present() -> None:
    assert citation_provider_from_settings(_settings()) is None


def test_factory_needs_both_serper_and_anthropic() -> None:
    assert citation_provider_from_settings(_settings(serper_api_key="sk")) is None
    assert citation_provider_from_settings(_settings(anthropic_api_key="ak")) is None


def test_build_search_provider_degrades_when_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.errors import ProviderNotConfiguredError

    def _boom(**_k: object) -> Any:
        raise ProviderNotConfiguredError("install the AI extra")

    monkeypatch.setattr("integrations.llm.AnthropicSummarizer", _boom)
    # No classifier can be built -> the whole provider degrades to None (no keyless run).
    assert build_search_citation_provider(_settings(serper_api_key="sk", anthropic_api_key="ak")) is None


def test_build_search_provider_prefers_google_places_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integrations.llm.AnthropicSummarizer", lambda **_k: FakeClaude())
    provider = build_search_citation_provider(
        _settings(serper_api_key="sk", anthropic_api_key="ak", google_places_api_key="gk")
    )
    assert isinstance(provider, SearchCitationProvider)
    assert isinstance(provider._places, GooglePlacesLookup)  # Google key wins the anchor


def test_build_search_provider_uses_serper_anchor_without_google_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("integrations.llm.AnthropicSummarizer", lambda **_k: FakeClaude())
    provider = build_search_citation_provider(_settings(serper_api_key="sk", anthropic_api_key="ak"))
    assert isinstance(provider, SearchCitationProvider)
    assert isinstance(provider._places, SerperPlacesLookup)  # falls back to the house Serper anchor
    assert provider._foursquare is None  # no key -> Foursquare enrichment skipped
    assert provider._listings is None  # no DataForSEO creds -> corroboration skipped


def test_build_search_provider_wires_dataforseo_when_creds_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gated exactly like Firecrawl: the creds' presence wires the source, their
    absence changes nothing (the test above pins the None half)."""
    monkeypatch.setattr("integrations.llm.AnthropicSummarizer", lambda **_k: FakeClaude())
    provider = build_search_citation_provider(
        _settings(
            serper_api_key="sk", anthropic_api_key="ak",
            dataforseo_login="user", dataforseo_password="pass",
        )
    )
    assert isinstance(provider, SearchCitationProvider)
    assert isinstance(provider._listings, DataForSEOBusinessListings)
