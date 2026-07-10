"""Citation discovery + NAP consistency client (Serper-backed).

Replaces the prior BrightLocal client. Uses Serper.dev's Google SERP API to
discover which tier-1 directories list the business and infers NAP match
strength from result snippets.

The dataclass shapes (`CitationStatus`, `CitationSummary`) match the previous
BrightLocal client byte-for-byte so the local analyzer is a drop-in swap.

Approach
--------
For a business with name + (optional) address + (optional) phone:

1. Issue 1-2 Serper queries scoped to tier-1 citation domains using the
   `site:` operator pattern through an `OR` of brand + phone / brand + address.
   Falls back to a single broad query if neither address nor phone is known.
2. For each tier-1 directory in `TIER_1_DIRECTORIES`, check whether any organic
   result's host matches the directory's host. Record presence + listing URL.
3. For found directories, parse the snippet text and compute three sub-scores:
   - name_match  : token overlap of business name vs snippet (0.0-1.0)
   - address_match : token overlap of address vs snippet (0.0-1.0)
   - phone_match : exact substring match of the last 7+ digits of the phone
4. `nap_score` is the mean of available sub-scores. A value below 1.0 means
   inconsistent (some field did not appear in the snippet).

This is a snippet-level inference, not a per-page fetch. It is fast and cheap,
but lower-confidence than BrightLocal's direct directory crawl. Findings emitted
through this module should carry `confidence: 0.6` upstream.

If `SERPER_API_KEY` is not set, the client returns a stub error-summary and the
analyzer downgrades gracefully (NAP-on-site only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from audit_engine.integrations.serper import SerperClient
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)


# Tier-1 directories the audit checks for presence. Tuple shape:
#   (display_name, host_match, is_aggregator)
# `host_match` is matched as a suffix against organic result hosts (so
# subdomains like `www.yelp.com` and `m.yelp.com` both count).
TIER_1_DIRECTORIES: list[tuple[str, str, bool]] = [
    ("Yelp", "yelp.com", False),
    ("Facebook", "facebook.com", False),
    ("Foursquare", "foursquare.com", True),
    ("YellowPages", "yellowpages.com", False),
    ("Apple Maps", "maps.apple.com", False),
    ("Bing Places", "bingplaces.com", False),
    ("BBB", "bbb.org", False),
    ("Manta", "manta.com", False),
    ("MapQuest", "mapquest.com", False),
    ("Cylex", "cylex.us.com", False),
    ("Hotfrog", "hotfrog.com", False),
    ("Brownbook", "brownbook.net", False),
    ("Localeze (Neustar)", "neustarlocaleze.biz", True),
    ("Data Axle", "dataaxleusa.com", True),
    ("Tripadvisor", "tripadvisor.com", False),
    ("Angi", "angi.com", False),
    ("HomeAdvisor", "homeadvisor.com", False),
    ("Thumbtack", "thumbtack.com", False),
]


@dataclass
class CitationStatus:
    source: str
    found: bool
    listing_url: str | None
    name_match: float | None
    address_match: float | None
    phone_match: float | None
    nap_score: float | None


@dataclass
class CitationSummary:
    business_query: str
    total_checked: int
    found_count: int
    missing_count: int
    inconsistent_count: int
    average_nap_score: float | None
    per_source: list[CitationStatus] = field(default_factory=list)
    error: str | None = None


def _host(link: str) -> str:
    return link.replace("https://", "").replace("http://", "").split("/", 1)[0].lower()


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


_STOPWORDS = {
    "the", "and", "for", "inc", "llc", "co", "company", "ltd", "limited",
    "of", "in", "on", "at", "to", "a", "an", "is", "by", "with", "&",
}


def _tokenize(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower())
            if len(t) >= 3 and t not in _STOPWORDS}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a:
        return 0.0
    return round(len(a & b) / len(a), 2)


def _match_scores(
    *,
    snippet: str,
    title: str,
    business_name: str,
    address: str | None,
    phone: str | None,
) -> tuple[float | None, float | None, float | None]:
    """Return (name_match, address_match, phone_match) — each 0.0-1.0 or None."""
    haystack = f"{title or ''} {snippet or ''}".lower()
    haystack_tokens = _tokenize(haystack)

    name_tokens = _tokenize(business_name)
    name_match = _overlap(name_tokens, haystack_tokens) if name_tokens else None

    address_match: float | None
    if address:
        addr_tokens = _tokenize(address)
        address_match = _overlap(addr_tokens, haystack_tokens) if addr_tokens else None
    else:
        address_match = None

    phone_match: float | None
    if phone:
        digits = _digits_only(phone)
        if len(digits) >= 7:
            tail = digits[-7:]
            phone_match = 1.0 if tail in _digits_only(haystack) else 0.0
        else:
            phone_match = None
    else:
        phone_match = None

    return name_match, address_match, phone_match


def _aggregate_nap(name_match, address_match, phone_match) -> float | None:
    parts = [x for x in (name_match, address_match, phone_match) if x is not None]
    if not parts:
        return None
    return round(sum(parts) / len(parts), 2)


class CitationsClient:
    """Serper-backed citation discovery + NAP inference.

    Usage:
        async with CitationsClient(api_key=keys.serper) as cc:
            summary = await cc.citation_status(name, address=..., phone=...)
    """

    provider_name = "citations_serper"

    def __init__(self, *, api_key: str | None = None, timeout: float = 20.0) -> None:
        self._api_key = api_key
        self._enabled = bool(api_key)
        self._serper = SerperClient(api_key=api_key, timeout=timeout) if api_key else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def __aenter__(self) -> CitationsClient:
        if self._serper is not None:
            await self._serper.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._serper is not None:
            await self._serper.__aexit__(*args)

    async def citation_status(
        self,
        business_name: str,
        *,
        address: str | None = None,
        phone: str | None = None,
    ) -> CitationSummary:
        """Discover which tier-1 directories list this business and score NAP match.

        Returns a CitationSummary identical in shape to the prior BrightLocal client.
        """
        if not self._enabled or self._serper is None:
            return CitationSummary(
                business_query=business_name,
                total_checked=0,
                found_count=0,
                missing_count=0,
                inconsistent_count=0,
                average_nap_score=None,
                error="SERPER_API_KEY not set",
            )

        # Build 1-2 broad queries. Serper returns ~10 organic results per call;
        # two queries surface enough tier-1 hits for a representative snapshot.
        queries: list[str] = []
        if phone:
            queries.append(f'"{business_name}" "{phone}"')
        if address:
            short_addr = address.split(",")[0].strip()
            queries.append(f'"{business_name}" "{short_addr}"')
        if not queries:
            queries.append(f'"{business_name}"')

        # Best result per directory, keyed by the directory display name.
        best_per_dir: dict[str, dict[str, Any]] = {}
        any_serper_error: str | None = None

        for q in queries:
            try:
                resp = await self._serper.search(q, results=10)
            except Exception as e:  # noqa: BLE001
                log.error("citations_serper_failed", query=q, error=type(e).__name__)
                any_serper_error = f"{type(e).__name__}: {e}"
                continue
            if resp.error:
                any_serper_error = resp.error
                continue
            for r in resp.organic:
                host = _host(r.link)
                for display, host_match, _agg in TIER_1_DIRECTORIES:
                    if host == host_match or host.endswith("." + host_match):
                        nm, am, pm = _match_scores(
                            snippet=r.snippet or "",
                            title=r.title or "",
                            business_name=business_name,
                            address=address,
                            phone=phone,
                        )
                        nap = _aggregate_nap(nm, am, pm)
                        candidate = {
                            "listing_url": r.link,
                            "name_match": nm,
                            "address_match": am,
                            "phone_match": pm,
                            "nap_score": nap,
                        }
                        existing = best_per_dir.get(display)
                        # Keep the candidate with the higher nap_score (None loses).
                        if existing is None or (
                            (nap or 0.0) > (existing.get("nap_score") or 0.0)
                        ):
                            best_per_dir[display] = candidate
                        break

        per: list[CitationStatus] = []
        nap_scores: list[float] = []
        found_count = 0
        inconsistent_count = 0

        for display, _host_match, _is_agg in TIER_1_DIRECTORIES:
            hit = best_per_dir.get(display)
            if hit:
                found_count += 1
                nap = hit.get("nap_score")
                if nap is not None:
                    nap_scores.append(float(nap))
                    if nap < 1.0:
                        inconsistent_count += 1
                per.append(
                    CitationStatus(
                        source=display,
                        found=True,
                        listing_url=hit.get("listing_url"),
                        name_match=hit.get("name_match"),
                        address_match=hit.get("address_match"),
                        phone_match=hit.get("phone_match"),
                        nap_score=nap,
                    )
                )
            else:
                per.append(
                    CitationStatus(
                        source=display,
                        found=False,
                        listing_url=None,
                        name_match=None,
                        address_match=None,
                        phone_match=None,
                        nap_score=None,
                    )
                )

        return CitationSummary(
            business_query=business_name,
            total_checked=len(per),
            found_count=found_count,
            missing_count=len(per) - found_count,
            inconsistent_count=inconsistent_count,
            average_nap_score=(sum(nap_scores) / len(nap_scores)) if nap_scores else None,
            per_source=per,
            error=any_serper_error if found_count == 0 and any_serper_error else None,
        )
