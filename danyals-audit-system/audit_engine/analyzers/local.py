"""Local SEO analyzers (Team D core).

GBP completeness, NAP consistency, reviews, local pack rankings. Deterministic
core; Team D agents add geo-context judgement and 2026-local-update awareness.
"""

from __future__ import annotations

import re
from typing import Iterable

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.integrations.citations import CitationSummary
from audit_engine.integrations.places import Place
from audit_engine.parsers.html import ParsedHTML


def check_gbp_completeness(place: Place) -> Verdict:
    """LOC-001 / LOC-003 GBP optimization + completeness."""
    if place.error:
        return Verdict(
            "n_a", 0.0, "info", 0.3,
            {"reason": place.error},
            "Configure GOOGLE_API_KEY (Places API enabled) to evaluate GBP.",
        )
    missing: list[str] = []
    if not place.formatted_address:
        missing.append("address")
    if not place.phone:
        missing.append("phone")
    if not place.website:
        missing.append("website")
    if not place.primary_type:
        missing.append("primary_type")
    if not place.opening_hours:
        missing.append("opening_hours")
    if place.photos_count == 0:
        missing.append("photos")
    score = max(0.0, 10.0 - len(missing) * 1.5)
    sev = "critical" if len(missing) >= 4 else "major" if len(missing) >= 2 else "minor"
    if not missing:
        return Verdict("pass", 10.0, "info", 1.0,
                       {"place_id": place.place_id, "primary_type": place.primary_type})
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity=sev,
        confidence=1.0,
        evidence={"place_id": place.place_id, "missing_fields": missing},
        remediation=f"Add to GBP: {', '.join(missing)}.",
    )


def check_gbp_categories(place: Place) -> Verdict:
    """LOC-002 GBP category optimization."""
    if place.error or not place.types:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": place.error or "no types data"})
    primary = place.primary_type
    secondary_count = len(place.types) - (1 if primary else 0)
    if not primary:
        return Verdict("fail", 0.0, "critical", 1.0, {"primary_type": None, "types": place.types},
                       "Set a precise primary category that matches the core service.")
    if secondary_count == 0:
        return Verdict("warn", 6.0, "minor", 1.0, {"primary_type": primary, "secondary_count": 0},
                       "Add relevant secondary categories (up to 9 allowed).")
    return Verdict("pass", 10.0, "info", 1.0,
                   {"primary_type": primary, "secondary_count": secondary_count})


def check_gbp_photos(place: Place) -> Verdict:
    """LOC-004 GBP photos audit (quantity threshold)."""
    if place.error:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": place.error})
    if place.photos_count == 0:
        return Verdict("fail", 0.0, "major", 1.0, {"photos_count": 0},
                       "GBP has no photos. Upload at least 10 (logo, exterior, interior, team, work samples).")
    if place.photos_count < 10:
        return Verdict("warn", 6.0, "minor", 1.0, {"photos_count": place.photos_count},
                       f"Only {place.photos_count} photo(s). Target 10+ across exterior, interior, team, work.")
    return Verdict("pass", 10.0, "info", 1.0, {"photos_count": place.photos_count})


def check_gbp_hours(place: Place) -> Verdict:
    """LOC-008 GBP hours accuracy."""
    if place.error:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": place.error})
    if not place.opening_hours:
        return Verdict("fail", 3.0, "major", 1.0, {"opening_hours": None},
                       "Set business hours on GBP. Missing hours suppresses some local pack appearances.")
    periods = place.opening_hours.get("periods", []) if isinstance(place.opening_hours, dict) else []
    if not periods:
        return Verdict("warn", 5.0, "major", 1.0, {"opening_hours": "no periods"},
                       "Hours present but no periods set. Add open/close per weekday.")
    return Verdict("pass", 10.0, "info", 1.0, {"periods_count": len(periods)})


def check_review_health(place: Place) -> Verdict:
    """LOC-021 GBP review analysis (count + recency + distribution)."""
    if place.error:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": place.error})
    count = place.rating_count or 0
    rating = place.rating
    if count == 0:
        return Verdict("fail", 0.0, "critical", 1.0, {"reviews": 0},
                       "Zero Google reviews. Establish a review-request workflow with happy customers.")
    if count < 10:
        return Verdict("warn", 4.0, "major", 1.0, {"reviews": count, "rating": rating},
                       f"Only {count} reviews. Target 25+ for credibility in the local pack.")
    if rating is not None and rating < 4.0:
        return Verdict("warn", 5.0, "major", 1.0, {"reviews": count, "rating": rating},
                       f"Rating {rating}/5 below the 4.0 threshold. Triage recent negatives, request fresh reviews.")
    return Verdict("pass", 10.0, "info", 1.0, {"reviews": count, "rating": rating})


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def check_nap_consistency_on_site(
    place: Place, parsed_pages: list[ParsedHTML]
) -> Verdict:
    """LOC-013 NAP consistency between GBP and the site's footer/contact-page.

    Heuristic: look for the formatted_address tokens and phone-digit prefix
    across crawled pages. If absent or different, flag.
    """
    if place.error or not place.formatted_address:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": place.error or "no GBP data"})
    gbp_addr_tokens = {t.lower() for t in re.findall(r"\w+", place.formatted_address) if len(t) >= 4}
    gbp_phone_digits = _digits_only(place.phone or "")[-10:]
    pages_with_addr_match = 0
    pages_with_phone_match = 0
    for p in parsed_pages:
        body = " ".join(
            x for x in [p.title or "", p.meta_description or ""] + [h.text for h in p.headings] if x
        ).lower()
        # Cheaper than reading full body; on a footer-laden site the relevant tokens are usually here.
        token_hits = sum(1 for t in gbp_addr_tokens if t in body)
        if token_hits >= max(2, int(len(gbp_addr_tokens) * 0.3)):
            pages_with_addr_match += 1
        if gbp_phone_digits and gbp_phone_digits in _digits_only(body):
            pages_with_phone_match += 1
    if pages_with_addr_match == 0 and pages_with_phone_match == 0:
        return Verdict(
            "fail", 2.0, "critical", 0.7,
            {
                "pages_checked": len(parsed_pages),
                "address_matches": 0,
                "phone_matches": 0,
                "gbp_address": place.formatted_address,
                "gbp_phone": place.phone,
            },
            "Neither GBP address nor phone appears on the site. Add NAP block to footer and contact page.",
        )
    if pages_with_addr_match < max(1, len(parsed_pages) // 5):
        return Verdict(
            "warn", 6.0, "major", 0.7,
            {
                "pages_checked": len(parsed_pages),
                "address_matches": pages_with_addr_match,
                "phone_matches": pages_with_phone_match,
            },
            "NAP appears on few pages. Ensure footer NAP is consistent on every page and matches GBP.",
        )
    return Verdict(
        "pass", 10.0, "info", 0.8,
        {
            "pages_checked": len(parsed_pages),
            "address_matches": pages_with_addr_match,
            "phone_matches": pages_with_phone_match,
        },
    )


def check_local_business_schema(parsed_pages: list[ParsedHTML]) -> Verdict:
    """LOC-032 LocalBusiness schema optimization."""
    blocks_with_lb = 0
    addr_in_lb = 0
    for p in parsed_pages:
        for block in p.schema_blocks:
            t = block.get("@type")
            types = t if isinstance(t, list) else [t]
            lb_types = {"LocalBusiness", "Restaurant", "Store", "ProfessionalService",
                        "Plumber", "Electrician", "Dentist", "Attorney", "HomeAndConstructionBusiness"}
            if any(tt in lb_types for tt in types if isinstance(tt, str)):
                blocks_with_lb += 1
                if block.get("address"):
                    addr_in_lb += 1
    if blocks_with_lb == 0:
        return Verdict(
            "fail", 2.0, "critical", 1.0,
            {"pages_checked": len(parsed_pages), "pages_with_local_business_schema": 0},
            "No LocalBusiness (or subtype) schema detected. Add LocalBusiness JSON-LD on the homepage.",
        )
    if addr_in_lb < blocks_with_lb:
        return Verdict(
            "warn", 6.0, "major", 1.0,
            {"blocks_with_lb": blocks_with_lb, "blocks_with_address": addr_in_lb},
            "LocalBusiness schema present but missing PostalAddress on some blocks.",
        )
    return Verdict("pass", 10.0, "info", 1.0,
                   {"blocks_with_lb": blocks_with_lb})


def check_citation_consistency(summary: CitationSummary) -> Verdict:
    """LOC-012 Citation consistency analysis.

    Confidence is capped at 0.6 because citation discovery is inferred from
    Serper SERP snippets rather than a direct per-directory crawl. The list of
    tier-1 directories matched is fixed; presence and NAP scores reflect what
    surfaces in Google's index, not necessarily the source-of-truth listing.
    """
    if summary.error:
        return Verdict("n_a", 0.0, "info", 0.3, {"reason": summary.error},
                       "Configure SERPER_API_KEY to evaluate citation discovery via SERP.")
    if summary.total_checked == 0:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": "no citations data"})
    inconsistent = summary.inconsistent_count
    missing = summary.missing_count
    avg = summary.average_nap_score or 0
    if missing == 0 and inconsistent == 0:
        return Verdict(
            "pass", 10.0, "info", 0.6,
            {"checked": summary.total_checked, "avg_nap_score": avg},
        )
    score = max(0.0, 10.0 - missing * 0.5 - inconsistent * 1.0)
    sev = "critical" if inconsistent >= 5 else "major" if (inconsistent + missing) >= 5 else "minor"
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity=sev,
        confidence=0.6,
        evidence={
            "checked": summary.total_checked,
            "found": summary.found_count,
            "missing": missing,
            "inconsistent": inconsistent,
            "avg_nap_score": avg,
            "method": "serper-snippet-inference",
        },
        remediation=(
            f"{missing} tier-1 directories show no SERP presence and {inconsistent} show NAP drift. "
            "Claim or create the missing listings (start with Yelp, Facebook, Foursquare, Apple Maps, Bing Places), "
            "then audit each inconsistent listing for name/address/phone variance vs the GBP canonical."
        ),
    )


def iter_local_findings(
    *, place: Place | None, citations: CitationSummary | None, parsed_pages: list[ParsedHTML]
) -> Iterable[tuple[str, str, str, Verdict]]:
    """Yield (check_id, category, owner_agent, verdict) for local SEO checks."""
    if place is not None:
        yield ("LOC-001", "local-seo", "D1", check_gbp_completeness(place))
        yield ("LOC-002", "local-seo", "D1", check_gbp_categories(place))
        yield ("LOC-004", "local-seo", "D1", check_gbp_photos(place))
        yield ("LOC-008", "local-seo", "D1", check_gbp_hours(place))
        yield ("LOC-021", "local-seo", "D3", check_review_health(place))
        if parsed_pages:
            yield ("LOC-013", "local-seo", "D2", check_nap_consistency_on_site(place, parsed_pages))
    if parsed_pages:
        yield ("LOC-032", "local-seo", "D4", check_local_business_schema(parsed_pages))
    if citations is not None:
        yield ("LOC-012", "local-seo", "D2", check_citation_consistency(citations))
