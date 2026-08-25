"""Every declared check is either REGISTERED or LEDGERED. Nothing is silent.

``emit.build_coverage`` used to report an unimplemented check with
SKIP_UNRESOLVED_ANALYZER, a reason its own docstring described as untrustworthy.
A client could not be told why a check did not run, so "we did not check this"
and "this passed" looked the same from the outside.

Each entry names a typed reason, what it is blocked on, and a note a reviewer
can disagree with. The two-sided ratchet in tests/test_ledger.py forces the
count into the diff of any PR that changes it: a wave that implements ten
checks must delete ten entries, and a new unimplemented check cannot be added
without someone writing down why.

Reasons are checked for consistency against each check's declared
``data_sources``, so a buildable check cannot be parked behind a false excuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from audit_engine.checklist import load_registry


class Reason(StrEnum):
    """Why a declared check does not run yet."""

    #: Needs backlink data. DataForSEO backlinks/summary is priced at $0.024
    #: per request, which answers O-6; Moz was never reachable.
    NEEDS_BACKLINK_PROVIDER = "needs_backlink_provider"
    #: Needs a paid third-party API that is not backlinks.
    NEEDS_PROVIDER = "needs_provider"
    #: Needs the page as a browser renders it.
    NEEDS_RENDERED_DOM = "needs_rendered_dom"
    #: Needs Search Console or server logs, both client-granted.
    NEEDS_SEARCH_CONSOLE = "needs_search_console"
    #: Every input is already available. This is simply not written yet.
    NOT_YET_BUILT = "not_yet_built"
    #: Buildable, but WHAT it should measure is a product decision. Picking a
    #: plausible-looking definition would produce a number nobody can trace.
    OWNER_DECISION = "owner_decision"


#: Sources that justify each reason. A check ledgered under a reason must
#: declare at least one of these, or the excuse does not match the check.
REASON_REQUIRES: dict[Reason, frozenset[str]] = {
    Reason.NEEDS_BACKLINK_PROVIDER: frozenset({
        "moz_links", "moz_links_historical", "moz_da", "moz_spam_score",
        "moz_keyword", "competitor_moz_links", "competitor_moz_da",
    }),
    Reason.NEEDS_PROVIDER: frozenset({
        "serper", "serper_geo", "serper_top10", "google_places", "otterly",
        "google_nl", "w3c_validator", "web_fetch", "wikidata",
    }),
    Reason.NEEDS_RENDERED_DOM: frozenset({
        "rendered_html", "rendered_html_mobile", "screenshot_breakpoints",
    }),
    Reason.NEEDS_SEARCH_CONSOLE: frozenset({
        "gsc_coverage", "gsc_ctr", "gsc_queries", "server_logs", "crawl_log",
    }),
    # These two assert nothing about data sources. NOT_YET_BUILT asserts the
    # opposite - that every input is already free - and test_ledger.py checks it.
    Reason.NOT_YET_BUILT: frozenset(),
    Reason.OWNER_DECISION: frozenset(),
}


@dataclass(frozen=True)
class LedgerEntry:
    check_id: str
    reason: Reason
    blocked_on: str
    note: str

    @property
    def name(self) -> str:
        return load_registry()[self.check_id].name


def _e(cid: str, reason: Reason, blocked_on: str, note: str) -> tuple[str, LedgerEntry]:
    return cid, LedgerEntry(cid, reason, blocked_on, note)


NOTES: dict[Reason, str] = {
    Reason.NEEDS_BACKLINK_PROVIDER:
        "No backlink data is purchased. DataForSEO backlinks/summary is priced "
        "at $0.024 per request and would supply this.",
    Reason.NEEDS_PROVIDER:
        "Requires a paid third-party API that is not currently called for this check.",
    Reason.NEEDS_RENDERED_DOM:
        "Needs the page as a browser renders it. Firecrawl is available (1000 credits/month) "
        "and avoids shipping Chromium beside the API.",
    Reason.NEEDS_SEARCH_CONSOLE:
        "Needs data only the site owner can grant. Google OAuth credentials exist; "
        "the per-client grant does not.",
    Reason.OWNER_DECISION:
        "The inputs and the gate exist; what this should MEASURE does not follow "
        "from the checklist taxonomy and is a product decision.",
    Reason.NOT_YET_BUILT:
        "Every input this needs is already crawled and free. Simply not written yet.",
}

LEDGER: dict[str, LedgerEntry] = dict([
    _e("LOC-003", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # GBP profile completeness
    _e("LOC-005", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # GBP posts cadence and engagement
    _e("LOC-006", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # GBP products / services completeness
    _e("LOC-007", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # GBP attributes optimization
    _e("LOC-010", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # GBP service area definition
    _e("LOC-011", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Local citation audit (count and presence across tier-1 sou
    _e("LOC-014", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Missing citations detection (vs competitor baseline)
    _e("LOC-015", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Duplicate citations detection
    _e("LOC-016", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Data aggregator presence (Foursquare, Acxiom, Localeze, Ne
    _e("LOC-017", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Apple Business Connect presence
    _e("LOC-018", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Bing Places presence and optimization
    _e("LOC-019", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Industry-specific citations (Yelp, Angi, BBB, vertical dir
    _e("LOC-020", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Citation NAP exactness vs phonetic match score
    _e("LOC-023", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Review velocity analysis (reviews per month, trend)
    _e("LOC-024", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Review response rate and response time
    _e("LOC-028", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Review competitor benchmark (gap vs map pack peers)
    _e("LOC-029", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Map pack ranking by geo grid (1, 3, 5, 10 mile rings)
    _e("LOC-030", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Geo targeted keyword optimization
    _e("OFF-002", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Domain rating analysis
    _e("OFF-004", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Backlink profile analysis
    _e("OFF-006", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Link velocity analysis
    _e("OFF-007", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Toxic backlink detection
    _e("OFF-008", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Spam backlink analysis
    _e("OFF-009", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Lost backlink detection
    _e("OFF-010", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # New backlink detection
    _e("OFF-011", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # High authority backlink analysis
    _e("OFF-015", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Homepage backlink analysis
    _e("OFF-016", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Deep page backlink analysis
    _e("OFF-020", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Exact match anchor analysis
    _e("OFF-022", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Generic anchor analysis
    _e("OFF-023", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Link diversity analysis
    _e("OFF-024", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Dofollow backlink analysis
    _e("OFF-025", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Nofollow backlink analysis
    _e("OFF-026", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Sponsored link analysis
    _e("OFF-027", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # UGC link analysis
    _e("OFF-028", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Referring IP diversity analysis
    _e("OFF-029", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Referring subnet diversity analysis
    _e("OFF-030", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Country relevance analysis
    _e("OFF-031", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # TLD distribution analysis
    _e("OFF-035", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Sitewide backlink detection
    _e("OFF-038", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Link farm detection
    _e("OFF-041", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Competitor backlink gap analysis
    _e("OFF-042", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Competitor authority comparison
    _e("OFF-043", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Competitor referring domains comparison
    _e("OFF-044", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Broken backlink opportunities
    _e("OFF-051", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Knowledge Graph presence analysis
    _e("OFF-052", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Branded search volume analysis
    _e("OFF-055", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Press release backlink analysis
    _e("OFF-057", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Forum backlink analysis
    _e("OFF-058", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Profile backlink analysis
    _e("OFF-059", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Redirect backlink analysis
    _e("OFF-060", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Link decay analysis
    _e("OFF-061", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Historical backlink trend analysis
    _e("OFF-065", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Video backlink analysis
    _e("OFF-066", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Image backlink analysis
    _e("OFF-068", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # Generative search visibility analysis
    _e("OFF-070", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Trust flow analysis
    _e("OFF-071", Reason.NEEDS_BACKLINK_PROVIDER, "O-6",
       NOTES[Reason.NEEDS_BACKLINK_PROVIDER]),  # Citation flow analysis
    _e("OFF-072", Reason.OWNER_DECISION, "O-1 follow-up",
       "Indistinguishable from OFF-074 Authority given the current subpoints. Needs a definition that separates the two."),
    _e("OFF-073", Reason.OWNER_DECISION, "O-1 follow-up",
       "Indistinguishable from OFF-079 Brand popularity given the current subpoints."),
    _e("OFF-075", Reason.OWNER_DECISION, "O-1 follow-up",
       "A sub-rollup of what? OFF-080 already covers the whole off-page pillar."),
    _e("ON-010", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # NLP keyword coverage
    _e("ON-020", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Internal topical relevance analysis
    _e("ON-070", Reason.NOT_YET_BUILT, "Wave 3",
       "Needs the HTTP response of each IMAGE, not of the page. The crawler fetches HTML documents only, so this needs an image-fetch pass with its own budget."),
    _e("ON-083", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Mobile content parity analysis
    _e("ON-108", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # Hidden content detection
    _e("ON-112", Reason.OWNER_DECISION, "O-1 follow-up",
       "No matching subpoint in the checklist. Which checks constitute user value is a product decision, not a taxonomy lookup."),
    _e("TECH-005", Reason.NEEDS_SEARCH_CONSOLE, "client OAuth grant",
       NOTES[Reason.NEEDS_SEARCH_CONSOLE]),  # Crawlability analysis
    _e("TECH-007", Reason.NEEDS_SEARCH_CONSOLE, "client OAuth grant",
       NOTES[Reason.NEEDS_SEARCH_CONSOLE]),  # Crawl budget optimization
    _e("TECH-028", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # JavaScript rendering analysis
    _e("TECH-030", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # Mobile rendering analysis
    _e("TECH-031", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # Client side rendering issues
    _e("TECH-032", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # DOM rendered content comparison
    _e("TECH-033", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # JS hidden content detection
    _e("TECH-034", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # Lazy load indexing analysis
    _e("TECH-049", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # Excessive DOM size analysis
    _e("TECH-065", Reason.NEEDS_RENDERED_DOM, "Wave 6",
       NOTES[Reason.NEEDS_RENDERED_DOM]),  # Responsive design validation
    _e("TECH-070", Reason.NEEDS_SEARCH_CONSOLE, "client OAuth grant",
       NOTES[Reason.NEEDS_SEARCH_CONSOLE]),  # Crawl log analysis
    _e("TECH-071", Reason.NEEDS_SEARCH_CONSOLE, "client OAuth grant",
       NOTES[Reason.NEEDS_SEARCH_CONSOLE]),  # Googlebot activity analysis
    _e("TECH-073", Reason.NEEDS_PROVIDER, "provider budget",
       NOTES[Reason.NEEDS_PROVIDER]),  # HTML validation analysis
    _e("TECH-075", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Thin page detection (technical)
    _e("TECH-078", Reason.NEEDS_SEARCH_CONSOLE, "client OAuth grant",
       NOTES[Reason.NEEDS_SEARCH_CONSOLE]),  # Index bloat detection
    _e("TECH-082", Reason.NOT_YET_BUILT, "Wave 3",
       "Its declared sources (crawled_html, http_headers) cannot detect malware; a header scan would be security theatre. Google Safe Browsing v4 is free with the existing GOOGLE_API_KEY and is the correct implementation. The declared data_sources are wrong."),
    _e("TECH-084", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Cloaking detection
    _e("TECH-088", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Image crawlability analysis
    _e("TECH-089", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Image indexing analysis
    _e("TECH-090", Reason.NOT_YET_BUILT, "Wave 3",
       "Server WebP support is proved by content negotiation on an image request, which needs the image-fetch pass. ON-071 already reports webp usage in the HTML."),
    _e("TECH-091", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # Video indexing analysis
    _e("TECH-094", Reason.NOT_YET_BUILT, "Wave 3",
       NOTES[Reason.NOT_YET_BUILT]),  # XML errors analysis
])


#: Two-sided ratchet. Both bounds are asserted separately with different
#: messages, so implementing a check and forgetting to delete its entry fails
#: just as loudly as adding an unexplained gap.
LEDGER_CEILING = 89
LEDGER_FLOOR = 89


def ledgered() -> dict[str, LedgerEntry]:
    return dict(LEDGER)


def reason_for(check_id: str) -> LedgerEntry | None:
    return LEDGER.get(check_id)
