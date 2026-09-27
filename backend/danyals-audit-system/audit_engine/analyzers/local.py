"""Local SEO analyzers (Team D core).

GBP completeness, NAP consistency, reviews, local pack rankings. Deterministic
core; Team D agents add geo-context judgement and 2026-local-update awareness.

TWO THINGS THIS MODULE IS CAREFUL ABOUT, both of them cases of the engine being
able to claim more than it measured.

WHOSE PROFILE IS THIS. ``places.find_place`` returns a candidate whether or not it
proved the listing belongs to the audited business, and says so on
``Place.identity_verified``. That flag used to reach only a console line, so a GBP
that might belong to a different company was scored at ``confidence=1.0`` and could
report ``critical`` findings about a stranger's listing. :func:`identity_of` grades
the evidence - a domain match, else corroboration from the site's own text, else
nothing (and it distinguishes "looked and found nothing" from "had nothing to look
at") - and :func:`qualify_for_identity` applies the consequence to EVERY GBP-derived
verdict in one place, so a new GBP check cannot forget it.

WHERE NAP ACTUALLY LIVES. The consistency check used to scan titles, meta
descriptions and headings. A business's address and phone sit in the FOOTER and on
the contact page - i.e. in body text - so the check systematically missed a
perfectly good NAP block and fired ``critical`` at sites that had one.
``ParsedHTML.body_text`` was already parsed and free; :func:`site_text_of` reads it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.integrations.citations import CitationSummary
from audit_engine.integrations.places import Place
from audit_engine.parsers.html import ParsedHTML

# --------------------------------------------------------------------------- #
# Whose Google Business Profile is this? (the identity ladder)
# --------------------------------------------------------------------------- #
#: The identity grades, strongest first.
#:
#: ``domain``      - the GBP's own website field resolves to the audited domain.
#:                   Google only shows a website the profile owner entered, so this
#:                   is as close to proof as an external audit gets.
#: ``corroborated``- the GBP's phone (or its street number + postal code) appears in
#:                   the audited site's own text. Not proof - a directory page could
#:                   list a competitor - but a business publishing another company's
#:                   phone number on its own site is rare enough to act on.
#: ``unverified``  - neither, having checked. Extremely common and NOT evidence of a
#:                   wrong match: a great many legitimate GBPs carry no website at
#:                   all. It means only that nothing here establishes the listing is
#:                   the client's.
IDENTITY_DOMAIN = "domain"
IDENTITY_CORROBORATED = "corroborated"
IDENTITY_UNVERIFIED = "unverified"
#: ``unchecked`` - the corroboration pass had nothing to read (no crawled pages, or no
#: profile at all). It carries the SAME consequences as ``unverified``, and exists as a
#: separate grade for one reason: "we looked and found nothing" and "there was nothing
#: to look at" are different statements, and the finding says which. Collapsing them
#: would have the report assert it checked the site's text when it never did - the
#: exact class of overclaim this whole module was fixed for.
IDENTITY_UNCHECKED = "unchecked"

#: What fraction of a GBP-derived verdict's confidence survives each grade. A
#: corroborated match is discounted a little (it is inference, not proof); an
#: unverified one is discounted hard, because the profile may not be the client's.
IDENTITY_CONFIDENCE: dict[str, float] = {
    IDENTITY_DOMAIN: 1.0,
    IDENTITY_CORROBORATED: 0.8,
    IDENTITY_UNVERIFIED: 0.35,
    IDENTITY_UNCHECKED: 0.35,
}

#: The grades that have NOT established the profile is the client's. Both take the
#: severity cap and the confirm-first remediation.
IDENTITY_UNPROVEN: frozenset[str] = frozenset({IDENTITY_UNVERIFIED, IDENTITY_UNCHECKED})

#: Why each unproven grade is unproven, in a sentence a reader can act on.
_IDENTITY_BASIS: dict[str, str] = {
    IDENTITY_UNVERIFIED: (
        "the profile's website field does not resolve to this domain, and neither its "
        "phone nor its street address appears in the site's own text"
    ),
    IDENTITY_UNCHECKED: (
        "the profile's website field does not resolve to this domain, and there were no "
        "crawled pages to check its phone or address against"
    ),
}

#: The worst severity an UNVERIFIED profile's finding may carry. A profile we cannot
#: tie to the client does not get to raise a critical: the remediation would send
#: someone to edit a listing that may not be theirs, and the fix they actually need
#: first is to confirm which listing is. Deliberately not applied to the
#: corroborated grade - that evidence is good enough to act on.
UNVERIFIED_SEVERITY_CAP = "minor"

_SEVERITY_ORDER: tuple[str, ...] = ("info", "minor", "major", "critical")


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def site_text_of(page: ParsedHTML) -> str:
    """All of one crawled page's human-readable text, lowercased.

    ``body_text`` is the load-bearing part and the part the old NAP check omitted -
    a footer NAP block is body text, not a heading. Title / meta / headings stay in
    because a contact page routinely carries the address in an ``<h2>``, and
    including them costs nothing.
    """
    parts = [page.title or "", page.meta_description or "", page.body_text or ""]
    parts.extend(h.text for h in page.headings)
    return " ".join(p for p in parts if p).lower()


def _address_tokens(formatted_address: str) -> set[str]:
    """The distinctive words of a formatted address (4+ chars, lowercased)."""
    return {t.lower() for t in re.findall(r"\w+", formatted_address or "") if len(t) >= 4}


def _street_number(formatted_address: str) -> str:
    """The leading street number of a formatted address, or ''."""
    match = re.match(r"\s*(\d{1,6})\b", formatted_address or "")
    return match.group(1) if match else ""


def _postal_digits(formatted_address: str) -> str:
    """The postal code's DIGITS, from the tail of a formatted address, or ''.

    Digits rather than the formatted token, for the same reason the phone is matched
    on digits: a site writes "CA 90017" where Google writes "CA90017", and comparing
    the formatted strings fails on spacing alone. The LAST 4-6 digit run wins because
    a formatted address ends "…, CA 90017, USA" - the street number is at the front.
    """
    runs = re.findall(r"\d{4,6}", formatted_address or "")
    return runs[-1] if runs else ""


def _number_tokens(text: str) -> set[str]:
    """The distinct whole numbers appearing in some text.

    Matching against TOKENS, not against a concatenated digit stream: joining every
    digit on the page into one string makes "1200" and "90017" match across unrelated
    numbers that happen to sit beside each other, which is a coincidence reported as
    an address match.
    """
    return set(re.findall(r"\d+", text or ""))


def identity_of(place: Place, parsed_pages: list[ParsedHTML] | None = None) -> str:
    """Grade the evidence that ``place`` is the audited business's own profile.

    Returns one of :data:`IDENTITY_DOMAIN` / :data:`IDENTITY_CORROBORATED` /
    :data:`IDENTITY_UNVERIFIED` / :data:`IDENTITY_UNCHECKED`. Pure, and free: the
    corroboration pass reads the pages the crawl already fetched.
    """
    if place.identity_verified:
        return IDENTITY_DOMAIN
    pages = parsed_pages or []
    if not pages or not place.place_id:
        # Nothing to corroborate against, which is NOT the same as having looked and
        # found nothing. The finding says which.
        return IDENTITY_UNCHECKED

    address = place.formatted_address or ""
    phone_digits = _digits_only(place.phone or "")[-10:]
    street = _street_number(address)
    postal = _postal_digits(address)
    # The address's own WORDS ("wilshire", "blvd"), so two coincidental numbers on a
    # page cannot pass as an address.
    words = {t for t in _address_tokens(address) if not t.isdigit()}

    for page in pages:
        text = site_text_of(page)
        if phone_digits and phone_digits in _digits_only(text):
            return IDENTITY_CORROBORATED
        # THREE signals together, because each alone is far too weak: "1200" appears on
        # any page that counts something, a postal code is shared by a whole district,
        # and a street word like "main" is everywhere. All three on one page is an
        # address.
        numbers = _number_tokens(text)
        if (
            street and postal and words
            and street in numbers
            and postal in numbers
            and any(word in text for word in words)
        ):
            return IDENTITY_CORROBORATED
    return IDENTITY_UNVERIFIED


def _cap_severity(severity: str, cap: str) -> str:
    """``severity``, lowered to ``cap`` when it is worse than it."""
    try:
        return severity if _SEVERITY_ORDER.index(severity) <= _SEVERITY_ORDER.index(cap) else cap
    except ValueError:
        return severity


def qualify_for_identity(verdict: Verdict, place: Place, identity: str) -> Verdict:
    """Apply the identity grade to one GBP-derived verdict.

    Every grade records ``gbp_identity`` in the evidence, so a reader can always see
    on what basis the profile was treated as the client's. An UNPROVEN profile
    (``unverified`` or ``unchecked``) additionally: scales confidence down, caps severity at
    :data:`UNVERIFIED_SEVERITY_CAP`, carries the candidate's name + address so a
    human can check the match in seconds, and PREPENDS the remediation with the
    confirmation step - because "add your hours" is the wrong first instruction when
    we cannot show the listing is yours.

    ``n_a`` verdicts are returned untouched: they measured nothing about a profile,
    so there is nothing to qualify.
    """
    if verdict.status == "n_a":
        return verdict

    evidence = {**verdict.evidence, "gbp_identity": identity}
    confidence = round(verdict.confidence * IDENTITY_CONFIDENCE.get(identity, 1.0), 4)
    severity = verdict.severity
    remediation = verdict.remediation

    if identity in IDENTITY_UNPROVEN:
        evidence["gbp_identity_basis"] = _IDENTITY_BASIS[identity]
        evidence["gbp_candidate_name"] = place.name or ""
        evidence["gbp_candidate_address"] = place.formatted_address or ""
        if place.website:
            evidence["gbp_candidate_website"] = place.website
        severity = _cap_severity(severity, UNVERIFIED_SEVERITY_CAP)
        confirm = (
            f"FIRST confirm this Google Business Profile is yours - it was matched by "
            f"name only: {place.name or 'unnamed'}"
            + (f", {place.formatted_address}" if place.formatted_address else "")
            + ". If it is not, this finding describes someone else's listing."
        )
        remediation = f"{confirm} {remediation}" if remediation else confirm

    return Verdict(
        status=verdict.status,
        score=verdict.score,
        severity=severity,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=evidence,
        remediation=remediation,
        references=verdict.references,
    )


def check_gbp_completeness(place: Place) -> Verdict:
    """LOC-001 / LOC-003 GBP optimization + completeness."""
    if place.error:
        return Verdict(
            "n_a", 0.0, "info", 0.3,
            {"reason": place.error,
             "operator_note": "Places API unavailable. Check GOOGLE_PLACES_API_KEY "
                              "and that the Places API is enabled for the project."},
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


def check_nap_consistency_on_site(
    place: Place, parsed_pages: list[ParsedHTML]
) -> Verdict:
    """LOC-013 NAP consistency between GBP and the site's footer/contact-page.

    WHERE IT LOOKS, and why that was the whole bug. This used to join each page's
    title, meta description and headings and scan that, on the stated assumption
    that "on a footer-laden site the relevant tokens are usually here". They are
    not: a NAP block is footer BODY text, and a contact page's address is a
    paragraph. So a site with a perfect footer NAP on every page scored
    ``fail`` / ``critical`` - "Neither GBP address nor phone appears on the site" -
    about text sitting in ``ParsedHTML.body_text``, which the crawl had already
    parsed and which cost nothing to read. :func:`site_text_of` reads it.

    Address matching stays token-based (a site writes "Suite 4" where Google writes
    "Ste 4", so an exact-string compare would fail on formatting alone), but the
    phone is matched on DIGITS, which is exact - formatting cannot hide it.
    """
    if place.error or not place.formatted_address:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": place.error or "no GBP data"})
    gbp_addr_tokens = _address_tokens(place.formatted_address)
    gbp_phone_digits = _digits_only(place.phone or "")[-10:]
    pages_with_addr_match = 0
    pages_with_phone_match = 0
    for p in parsed_pages:
        text = site_text_of(p)
        token_hits = sum(1 for t in gbp_addr_tokens if t in text)
        if gbp_addr_tokens and token_hits >= max(2, int(len(gbp_addr_tokens) * 0.3)):
            pages_with_addr_match += 1
        if gbp_phone_digits and gbp_phone_digits in _digits_only(text):
            pages_with_phone_match += 1
    # What the check actually read, so a disputed verdict is traceable to the
    # evidence rather than to the reader's guess about where we looked.
    basis = {
        "pages_checked": len(parsed_pages),
        "address_matches": pages_with_addr_match,
        "phone_matches": pages_with_phone_match,
        "read": "title, meta description, headings and body text",
    }
    if pages_with_addr_match == 0 and pages_with_phone_match == 0:
        return Verdict(
            "fail", 2.0, "critical", 0.7,
            {**basis, "gbp_address": place.formatted_address, "gbp_phone": place.phone},
            "Neither GBP address nor phone appears on the site. Add NAP block to footer and contact page.",
        )
    if pages_with_addr_match < max(1, len(parsed_pages) // 5):
        return Verdict(
            "warn", 6.0, "major", 0.7, basis,
            "NAP appears on few pages. Ensure footer NAP is consistent on every page and matches GBP.",
        )
    return Verdict("pass", 10.0, "info", 0.8, basis)


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
        return Verdict("n_a", 0.0, "info", 0.3,
                       {"reason": summary.error,
                        "operator_note": "Citation discovery needs SERPER_API_KEY."})
    if summary.total_checked == 0:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": "no citations data"})
    inconsistent = summary.inconsistent_count
    not_observed = summary.not_observed_count
    avg = summary.average_nap_score or 0
    if not_observed == 0 and inconsistent == 0:
        return Verdict(
            "pass", 10.0, "info", 0.6,
            {"checked": summary.total_checked, "avg_nap_score": avg},
        )
    # A directory that did not surface in two broad queries is UNMEASURED, not a
    # confirmed missing listing - so it carries a fraction of the weight of an
    # observed NAP mismatch, which IS evidence. Scoring the two alike (0.5 each)
    # let absence-of-evidence drive the verdict and the remediation told the
    # client to "claim" listings that may already exist.
    score = max(0.0, 10.0 - not_observed * 0.2 - inconsistent * 1.0)
    sev = "critical" if inconsistent >= 5 else "major" if inconsistent >= 2 else "minor"
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity=sev,
        confidence=0.6,
        evidence={
            "checked": summary.total_checked,
            "listed": summary.found_count,
            "not_observed": not_observed,
            "inconsistent": inconsistent,
            "avg_nap_score": avg,
            "method": "serper-snippet-inference",
            "measurement_note": (
                "Presence is inferred from a SERP sample, not a per-directory fetch. "
                "'not_observed' means this method did not see a listing - it is NOT "
                "evidence the listing is absent."
            ),
        },
        remediation=(
            f"{inconsistent} tier-1 directories show NAP drift in their SERP snippets; "
            f"{not_observed} did not surface at all. Audit each inconsistent listing for "
            "name/address/phone variance vs the GBP canonical first - that is measured. "
            "Then check the not-observed directories directly (Yelp, Facebook, Foursquare, "
            "Apple Maps, Bing Places) and claim only the ones genuinely absent."
        ),
    )


#: The GBP-DERIVED checks - the ones whose whole subject is the matched Google
#: Business Profile, and which therefore describe the wrong business if the match is
#: wrong. Every one is qualified by :func:`qualify_for_identity`.
#:
#: LOC-013 is deliberately NOT in here even though it takes a ``place``: its subject
#: is the SITE (does the site publish a NAP at all), and that question is worth
#: answering whoever the profile belongs to. It carries ``gbp_identity`` for context
#: without the severity cap, because a site with no NAP block anywhere is a real
#: finding regardless.
GBP_DERIVED_CHECKS: frozenset[str] = frozenset({"LOC-001", "LOC-002", "LOC-004", "LOC-008", "LOC-021"})


def iter_local_findings(
    *, place: Place | None, citations: CitationSummary | None, parsed_pages: list[ParsedHTML]
) -> Iterable[tuple[str, str, str, Verdict]]:
    """Yield (check_id, category, owner_agent, verdict) for local SEO checks.

    Every GBP-derived verdict passes through :func:`qualify_for_identity` HERE rather
    than inside each check. One seam means a GBP check added later cannot ship
    without the identity discount, which is exactly how the original defect
    survived: the guarantee lived in ``find_place``'s docstring and in nothing that
    ran.
    """
    if place is not None:
        identity = identity_of(place, parsed_pages)
        gbp: list[tuple[str, str, str, Verdict]] = [
            ("LOC-001", "local-seo", "D1", check_gbp_completeness(place)),
            ("LOC-002", "local-seo", "D1", check_gbp_categories(place)),
            ("LOC-004", "local-seo", "D1", check_gbp_photos(place)),
            ("LOC-008", "local-seo", "D1", check_gbp_hours(place)),
            ("LOC-021", "local-seo", "D3", check_review_health(place)),
        ]
        for check_id, category, agent, verdict in gbp:
            yield (check_id, category, agent, qualify_for_identity(verdict, place, identity))
        if parsed_pages:
            nap = check_nap_consistency_on_site(place, parsed_pages)
            # Context, not a discount - see GBP_DERIVED_CHECKS.
            if nap.status != "n_a":
                nap = Verdict(
                    nap.status, nap.score, nap.severity, nap.confidence,
                    {**nap.evidence, "gbp_identity": identity}, nap.remediation, nap.references,
                )
            yield ("LOC-013", "local-seo", "D2", nap)
    if parsed_pages:
        yield ("LOC-032", "local-seo", "D4", check_local_business_schema(parsed_pages))
    if citations is not None:
        yield ("LOC-012", "local-seo", "D2", check_citation_consistency(citations))
