"""What the incoming links SAY, how they are labelled, and who sends them.

Three questions live in this module because they are answered from the same
fetched object:

* **Anchors** - the text other sites use to link here. It is the only part of a
  backlink the site being audited does not control, which is exactly why an
  anchor distribution that looks chosen rather than earned is the classic
  footprint of bought or automated links.
* **Link attributes** - ``nofollow``, ``sponsored`` and ``ugc``. Since Google's
  2019 "Evolving nofollow" announcement these are hints rather than directives,
  so they change what a link is WORTH; they are not defects in themselves.
* **Toxicity** - the provider's spam scores and the network the links come
  from. Reported as something to review, never as something to disavow on
  sight: disavowing healthy links is both the commoner and the costlier
  mistake, and Google's own disavow guidance says the tool can harm a site when
  used without a manual action to justify it.

**Why one fetched profile rather than one call per check.** ``backlinks/summary``
returns the whole profile in a single request - referring domains, IPs and
subnets, spam scores, and the distributions by TLD, country, platform, link
type, link attribute and semantic location - and a second request returns the
anchor distribution. Two requests, about five cents, answer all thirty-nine
backlink checks. Fetching per check would multiply the bill by nineteen and
would let two checks disagree about the same site because they sampled the
profile at different moments. The checks here therefore take a
``BacklinkProfile`` and compute; none of them calls out.

Every numeric threshold carries its source. Google publishes almost no backlink
numbers, so most of these are marked JUDGEMENT with the reasoning that produced
them rather than dressed up as an official ratio.
"""

from __future__ import annotations

import re
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check
from audit_engine.integrations.dataforseo import ANCHOR_LIMIT, BacklinkProfile

# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------

# JUDGEMENT: Google publishes no anchor-text ratio, and asking for one misreads
# how the signal works. This is set where a single phrase stops looking like the
# way independent people would describe a page: past a fifth of every referring
# domain using the identical commercial phrase, somebody chose the wording.
EXACT_ANCHOR_SINGLE_FAIL = 0.20
EXACT_ANCHOR_SINGLE_WARN = 0.10
# JUDGEMENT: a commercial site earns some keyword anchors honestly, so the
# aggregate band is deliberately loose. Half the profile is the point at which
# the mix stops resembling anything an editorial link pattern produces.
EXACT_ANCHOR_TOTAL_FAIL = 0.50
EXACT_ANCHOR_TOTAL_WARN = 0.30

# JUDGEMENT: bare URLs and "click here" are what directory, profile and
# comment links produce. Some is normal and healthy. Above this share the
# profile is telling Google the site is popular without telling it what for.
GENERIC_ANCHOR_WARN = 0.70

# JUDGEMENT: variety, expressed as distinct anchors per referring domain.
# 219 domains that between them produced 8 distinct anchors were not writing
# their own link text. Below one distinct anchor per twenty domains the
# distribution is a template rather than a distribution.
ANCHOR_VARIETY_FAIL = 0.05
ANCHOR_VARIETY_WARN = 0.15

# Google Search Central, "Evolving nofollow - new ways to identify the nature of
# links" (2019): nofollow, sponsored and ugc became hints for ranking purposes
# from 1 March 2020. A hint-only profile still carries discovery and referral
# value, which is why nothing below fails a site for it.
# JUDGEMENT: the bands themselves. A profile where four links in five are
# hint-only has very little that Google will count as an endorsement.
FOLLOWED_DOMAIN_SHARE_WARN = 0.20
NOFOLLOW_DOMAIN_SHARE_WARN = 0.80
# JUDGEMENT: passive link acquisition - social posts, comments, forum
# signatures, most directories - arrives nofollowed. A profile of this size with
# none at all was assembled deliberately.
NOFOLLOW_ABSENT_MIN_DOMAINS = 30

# JUDGEMENT: a declared paid or user-generated link is correctly labelled by the
# publisher, so it is never a defect. It is a value statement: past these shares
# most of the profile is made of links Google is told not to count.
SPONSORED_SHARE_WARN = 0.20
UGC_SHARE_WARN = 0.30

# Google Search Central spam policies, "Link spam", lists "widely distributed
# links in the footers or templates of various sites" as a link scheme.
# JUDGEMENT: the shares. A template link repeats on every page of the linking
# site, so the signature is a footer and header concentration plus many linking
# pages per domain.
SITEWIDE_SHARE_FAIL = 0.50
SITEWIDE_SHARE_WARN = 0.30
SITEWIDE_PAGES_PER_DOMAIN = 10.0

# The provider scores spam 0-100, higher being worse, for the incoming profile
# and for the target itself.
# JUDGEMENT: the bands. Google publishes no toxicity scale at all, and the score
# is a third party's model, so these are set well clear of the middle - a warn
# at a fifth of the scale, a fail past two fifths - because the cost of acting
# on a false positive here is a disavow file that removes healthy links.
SPAM_SCORE_FAIL = 40
SPAM_SCORE_WARN = 20
TARGET_SPAM_FAIL = 30
TARGET_SPAM_WARN = 10

# JUDGEMENT: domains per subnet. Unrelated sites share subnets constantly -
# shared hosting, Blogspot, Wix, Shopify, every CDN - so this cannot prove a
# link farm and the wording never claims it does. It flags the arithmetic that
# a private network produces: many "different" domains, few actual networks.
SUBNET_RATIO_FAIL = 3.0
SUBNET_RATIO_WARN = 1.5
# JUDGEMENT: below this many referring domains the ratio is noise. Three domains
# on two subnets is 1.5 and means nothing at all.
SUBNET_MIN_DOMAINS = 15

# --------------------------------------------------------------------------
# Anchor classification
# --------------------------------------------------------------------------

#: Labels that describe the ACT of linking rather than the destination.
_GENERIC_ANCHORS = frozenset({
    "click here", "click", "here", "read more", "read this", "more", "learn more",
    "this", "this page", "this article", "this post", "this site", "this website",
    "this link", "link", "website", "web site", "site", "homepage", "home page",
    "home", "visit", "visit us", "visit site", "visit website", "visit our website",
    "go", "go here", "view", "view more", "see more", "see here", "check it out",
    "source", "sources", "reference", "continue reading", "full article",
    "download", "next", "previous", "back", "top", "url", "www", "read",
})

#: A bare address used as the link text. Not generic in the "click here" sense,
#: but it says nothing about the page either, so the two are reported together.
_URL_ANCHOR = re.compile(
    r"https?://\S+|www\.\S+|[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/\S*)?", re.IGNORECASE
)


def _squash(text: str) -> str:
    """Letters and digits only, so "Smile On" matches the host label "smileon"."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _brand_token(target: str) -> str:
    host = re.sub(r"^https?://", "", (target or "").strip().lower()).split("/")[0]
    label = host.removeprefix("www.").split(".")[0]
    # A one or two letter label appears inside ordinary words, so it would mark
    # unrelated anchors as branded and hide a real over-optimisation problem.
    return label if len(label) >= 3 else ""


def _clean(text: str, limit: int = 60) -> str:
    """Anchor text is written by third parties and arrives as they wrote it -
    newlines, runs of spaces, occasionally a whole paragraph. Neither a report
    line nor a log entry should inherit that."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def _classify(anchor: str, brand: str) -> str:
    text = anchor.strip()
    if not text:
        return "empty"
    lower = text.lower()
    # URL first: a naked link to the site's own domain is a URL anchor, and
    # counting it as branded would flatter the brand share.
    if _URL_ANCHOR.fullmatch(lower):
        return "url"
    if lower in _GENERIC_ANCHORS:
        return "generic"
    if brand and brand in _squash(lower):
        return "branded"
    return "keyword"


def _anchor_mix(profile: BacklinkProfile) -> dict[str, int]:
    """Referring domains per anchor class. Values are domain counts, not link
    counts, because one domain linking a thousand times is still one vote."""
    brand = _brand_token(profile.target)
    mix = {"url": 0, "generic": 0, "branded": 0, "keyword": 0, "empty": 0}
    for anchor, domains in (profile.anchors or {}).items():
        mix[_classify(anchor, brand)] += int(domains or 0)
    return mix


def _share(part: float, whole: float) -> float:
    """Clamped: an anchor can be reported against more domains than the summary
    counted, and a share over 1.0 renders as a raw number rather than a
    percentage, which reads as a defect in the report rather than in the data."""
    if whole <= 0:
        return 0.0
    return min(1.0, max(0.0, part / whole))


def _pct(value: float) -> int:
    return round(value * 100)


# --------------------------------------------------------------------------
# Guards. n_a means NOT MEASURED - never a zero, never a remediation.
# --------------------------------------------------------------------------

def _na(reason: str, **ev: Any) -> Verdict:
    return Verdict("n_a", 0.0, "info", 0.0, {"reason": reason, **ev})


def _unusable(profile: BacklinkProfile | None) -> Verdict | None:
    """No profile, or a profile that is an error message, measured nothing."""
    if profile is None:
        return _na("the backlink profile was not fetched, so nothing about this site's "
                   "incoming links was measured")
    if not profile.ok:
        return _na("the backlink profile could not be retrieved, so nothing about this "
                   "site's incoming links was measured",
                   fetch_error=profile.error)
    return None


def _no_links(profile: BacklinkProfile, what: str) -> Verdict | None:
    """A site with no backlinks is a valid and common answer, not an error.

    It is a real finding, and the profile-volume checks report it. Repeating
    "this site has no links" in eleven more cards would bury the one card that
    says it, so the anchor, attribute and network checks stand down instead.
    """
    if not profile.has_links:
        return _na(f"the site has no referring domains, so there is no {what} to analyse",
                   referring_domains=profile.referring_domains)
    return None


def _no_anchors(profile: BacklinkProfile) -> Verdict | None:
    """The anchor distribution is a SECOND request, and the client returns an
    empty map rather than failing the whole profile when it does not land."""
    if not profile.anchors:
        return _na("the anchor text of this site's incoming links was not returned, so "
                   "the anchor mix could not be measured",
                   referring_domains=profile.referring_domains)
    return None


# --------------------------------------------------------------------------
# Anchors
# --------------------------------------------------------------------------

@check("OFF-020", scope="backlinks")
def check_exact_match_anchors(profile: BacklinkProfile) -> Verdict:
    """OFF-020 - commercial keyword anchors, and how concentrated they are.

    No backlinks means no anchor text, so that case is n_a rather than a
    finding: the referring-domain checks already report the absence itself.

    The honest limit, stated in the evidence as well as here: this audit does
    not buy the site's target keyword list, so no anchor can be declared an
    exact match against a named keyword. What IS measurable is the anchor that
    is neither the brand, nor a bare URL, nor a generic label - which is the
    anchor somebody chose for ranking - and the share of referring domains
    repeating it.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "anchor text")) is not None:
        return na
    if (na := _no_anchors(profile)) is not None:
        return na

    domains = profile.referring_domains
    brand = _brand_token(profile.target)
    mix = _anchor_mix(profile)
    keyword_anchors = {
        a: n for a, n in profile.anchors.items() if _classify(a, brand) == "keyword"
    }
    top_anchor, top_domains = ("", 0)
    if keyword_anchors:
        top_anchor, top_domains = max(keyword_anchors.items(), key=lambda kv: kv[1])
    # One domain linking with two keyword anchors is counted under both, so the
    # class total can exceed the domain count. Cap what is printed: "150 of 120
    # referring domains" reads as a defect in the audit, not in the profile.
    keyword_domains = min(mix["keyword"], domains)
    top_domains = min(top_domains, domains)
    top_share = _share(top_domains, domains)
    total_share = _share(keyword_domains, domains)

    ev = {
        "top_keyword_anchor": _clean(top_anchor) or None,
        "top_keyword_anchor_domains": top_domains,
        "top_keyword_anchor_share": round(top_share, 3),
        "keyword_anchor_share": round(total_share, 3),
        "referring_domains": domains,
        "distinct_anchors_examined": len(profile.anchors),
        "method": "anchors that are not the brand name, not a bare URL and not a generic "
                  "label are counted as commercial keyword anchors; the target keyword "
                  "list is not purchased for this audit, so a match against a named "
                  "keyword is not asserted",
        "threshold_basis": "judgement; Google publishes no anchor-text ratio",
    }

    if top_share >= EXACT_ANCHOR_SINGLE_FAIL or total_share >= EXACT_ANCHOR_TOTAL_FAIL:
        return Verdict(
            "fail", 2.0, "critical", 0.75, ev,
            f'{top_domains} of {domains} referring domains ({_pct(top_share)}%) link here '
            f'with the phrase "{_clean(top_anchor)}", and {keyword_domains} domains '
            f'({_pct(total_share)}%) use a commercial keyword phrase of some kind. '
            f'Independent sites do not converge on the same wording. Dilute rather than '
            f'strip: earn brand-name and bare-URL links so the phrase\'s share falls, '
            f'which is faster and safer than trying to get existing links edited.',
        )
    if top_share >= EXACT_ANCHOR_SINGLE_WARN or total_share >= EXACT_ANCHOR_TOTAL_WARN:
        return Verdict(
            "warn", 6.0, "major", 0.75, ev,
            f'{top_domains} of {domains} referring domains ({_pct(top_share)}%) use the '
            f'anchor "{_clean(top_anchor)}", with {_pct(total_share)}% of the profile on '
            f'commercial keyword phrases. That is not yet a footprint, but the next round '
            f'of link building should ask for brand-name anchors rather than keywords.',
        )
    return Verdict("pass", 10.0, "info", 0.75, ev)


@check("OFF-022", scope="backlinks")
def check_generic_anchors(profile: BacklinkProfile) -> Verdict:
    """OFF-022 - "click here", "read more" and bare URLs.

    No backlinks means no anchor text, so that case is n_a.

    These anchors are not a defect. Every real profile carries them, and a
    profile with none at all is the suspicious one. They are counted because a
    profile made almost entirely of them is passing authority without telling
    Google what the site is about.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "anchor text")) is not None:
        return na
    if (na := _no_anchors(profile)) is not None:
        return na

    domains = profile.referring_domains
    mix = _anchor_mix(profile)
    # Capped for the same reason as OFF-020: a domain can appear under more than
    # one anchor, and a count above the domain count reads as a broken report.
    uninformative = min(mix["generic"] + mix["url"], domains)
    share = _share(uninformative, domains)

    ev = {
        "generic_anchor_domains": mix["generic"],
        "bare_url_anchor_domains": mix["url"],
        "uninformative_anchor_share": round(share, 3),
        "branded_anchor_domains": mix["branded"],
        "referring_domains": domains,
        "threshold_basis": "judgement; no published ratio exists for generic anchors",
    }

    if share >= GENERIC_ANCHOR_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.75, ev,
            f"{uninformative} of {domains} referring domains ({_pct(share)}%) link with a "
            f"bare address or a label such as \"click here\". Those links still pass "
            f"authority, but they describe nothing, so none of them tells Google what this "
            f"site should rank for. Ask for the page's own topic as the link text on the "
            f"next placements.",
        )
    return Verdict("pass", 10.0, "info", 0.75, ev)


@check("OFF-023", scope="backlinks")
def check_anchor_diversity(profile: BacklinkProfile) -> Verdict:
    """OFF-023 - variety in the anchor text, not variety in the domains.

    OFF-036 and OFF-038 ask whether the LINKING SITES are distinct. This asks
    whether the WORDING is, which catches the case that domain diversity misses:
    two hundred genuinely different sites all linking with the same eight
    phrases were handed those phrases.

    No backlinks means no anchor text, so that case is n_a.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "anchor text")) is not None:
        return na
    if (na := _no_anchors(profile)) is not None:
        return na

    domains = profile.referring_domains
    distinct = len(profile.anchors)
    top_anchor, top_domains = max(profile.anchors.items(), key=lambda kv: kv[1])
    top_domains = min(top_domains, domains)
    variety = distinct / domains if domains else 0.0

    ev = {
        "distinct_anchors": distinct,
        "referring_domains": domains,
        "top_anchor": _clean(top_anchor) or None,
        "top_anchor_share": round(_share(top_domains, domains), 3),
        "distinct_anchors_per_domain": round(variety, 3),
        "threshold_basis": "judgement; variety is measured as distinct anchors per "
                           "referring domain",
    }

    # The provider returns the top 200 anchors per request. Hitting that ceiling
    # is itself the answer: the wording varies more than the request can show.
    if distinct >= ANCHOR_LIMIT:
        return Verdict("pass", 10.0, "info", 0.7,
                       {**ev, "method": f"the anchor request returns at most {ANCHOR_LIMIT} "
                                        f"distinct anchors and that ceiling was reached, so "
                                        f"the real variety is higher than the count shown"})
    if variety <= ANCHOR_VARIETY_FAIL:
        return Verdict(
            "fail", 3.0, "major", 0.75, ev,
            f"{domains} referring domains between them produced only {distinct} distinct "
            f"anchor phrases, the commonest being \"{_clean(top_anchor)}\" on {top_domains} "
            f"of them. A distribution that narrow is a template, not a set of independent "
            f"editorial decisions. Vary the wording on every future placement.",
        )
    if variety <= ANCHOR_VARIETY_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.75, ev,
            f"{distinct} distinct anchor phrases across {domains} referring domains, led by "
            f"\"{_clean(top_anchor)}\" on {top_domains}. The wording repeats more than "
            f"independent linking usually produces.",
        )
    return Verdict("pass", 10.0, "info", 0.75, ev)


# --------------------------------------------------------------------------
# Link attributes
#
# Google Search Central, "Evolving nofollow" (2019): nofollow, sponsored and ugc
# are hints for ranking purposes as of 1 March 2020. They change what a link is
# worth. None of them is a defect in the site being audited, so nothing here
# returns a fail.
# --------------------------------------------------------------------------

@check("OFF-024", scope="backlinks")
def check_dofollow_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-024 - the links that can carry an endorsement.

    No backlinks means no attribute mix, so that case is n_a.

    A floor, not an exact count: the provider counts a referring domain as
    nofollow when it sends a nofollow link, and subtracting those whole removes
    any domain that also sends a followed link. The evidence says so rather than
    presenting the subtraction as precise.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "link attribute mix")) is not None:
        return na

    domains = profile.referring_domains
    followed = max(0, domains - profile.referring_domains_nofollow)
    share = _share(followed, domains)

    ev = {
        "followed_domains": followed,
        "followed_domain_share": round(share, 3),
        "referring_domains": domains,
        "nofollow_domains": profile.referring_domains_nofollow,
        "method": "domains the provider counts as nofollow are excluded whole, so the "
                  "followed count is a floor rather than an exact figure",
        "threshold_basis": "judgement; nofollow has been a ranking hint rather than a "
                           "directive since March 2020",
    }

    if share < FOLLOWED_DOMAIN_SHARE_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.8, ev,
            f"Only {followed} of {domains} referring domains ({_pct(share)}%) send a link "
            f"that is followed throughout. The rest are hints, which Google may still use "
            f"for discovery but is not obliged to count as an endorsement. Link building "
            f"from here should target editorial placements rather than more directory and "
            f"profile listings.",
        )
    return Verdict("pass", 10.0, "info", 0.8, ev)


@check("OFF-025", scope="backlinks")
def check_nofollow_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-025 - the hint-only share, in both directions.

    No backlinks means no attribute mix, so that case is n_a.

    Too many nofollow domains says the profile is mostly hints. NONE at all, on
    a profile of any size, says something stranger: social posts, comments,
    forum signatures and most directories arrive nofollowed, so a profile that
    picked up none of them was assembled rather than accumulated.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "link attribute mix")) is not None:
        return na

    domains = profile.referring_domains
    nofollow = profile.referring_domains_nofollow
    share = _share(nofollow, domains)

    ev = {
        "nofollow_domains": nofollow,
        "nofollow_domain_share": round(share, 3),
        "referring_domains": domains,
        "nofollow_linking_pages": profile.referring_pages_nofollow,
        "threshold_basis": "judgement; nofollow is a ranking hint, not a penalty",
    }

    if nofollow == 0 and domains >= NOFOLLOW_ABSENT_MIN_DOMAINS:
        return Verdict(
            "warn", 6.0, "minor", 0.7, ev,
            f"Not one of the {domains} referring domains sends a nofollow link. Passive "
            f"mentions - social posts, comments, forum signatures, most directories - "
            f"arrive nofollowed, so a profile of this size with none of them looks placed "
            f"rather than earned. Worth checking who built these links.",
        )
    if share >= NOFOLLOW_DOMAIN_SHARE_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.8, ev,
            f"{nofollow} of {domains} referring domains ({_pct(share)}%) send nofollow "
            f"links. They still bring visitors and help discovery, but Google is only "
            f"hinted at rather than told to count them, so the profile carries less "
            f"ranking weight than its size suggests.",
        )
    return Verdict("pass", 10.0, "info", 0.8, ev)


@check("OFF-026", scope="backlinks")
def check_sponsored_links(profile: BacklinkProfile) -> Verdict:
    """OFF-026 - links the publisher declared as paid.

    No backlinks means no attribute mix, so that case is n_a.

    A rel=sponsored link is a publisher doing exactly what Google's link spam
    policy asks of them, so it is never a defect in this site. It is counted
    because a declared paid link is by design not counted as an endorsement:
    the money bought a referral, not a ranking signal.

    Note the limit, which the evidence key name carries: this counts links
    LABELLED sponsored. An undeclared paid link is invisible here, so a count of
    zero is not proof that nothing was bought.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "link attribute mix")) is not None:
        return na

    labelled = int(profile.link_attributes.get("sponsored", 0) or 0)
    pages = profile.referring_pages
    share = _share(labelled, pages)

    ev = {
        "links_labelled_sponsored": labelled,
        "share_of_linking_pages": round(share, 3),
        "linking_pages": pages,
        "method": "counts links the linking site labelled rel=sponsored; an undeclared "
                  "paid link carries no label and is not visible to this measurement",
        "threshold_basis": "judgement; a declared paid link is correct behaviour by the "
                           "publisher, so this is a value statement, not a defect",
    }

    if share >= SPONSORED_SHARE_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.7, ev,
            f"{labelled} of {pages} linking pages ({_pct(share)}%) declare their link as "
            f"paid. Those publishers labelled it correctly, and the labelling is what keeps "
            f"the site clear of the link spam policy, but a declared paid link is not "
            f"counted as an endorsement. Budget spent on more of them buys referral traffic "
            f"rather than authority.",
        )
    return Verdict("pass", 10.0, "info", 0.7, ev)


@check("OFF-027", scope="backlinks")
def check_ugc_links(profile: BacklinkProfile) -> Verdict:
    """OFF-027 - links from comments, forums and other user-generated space.

    No backlinks means no attribute mix, so that case is n_a.

    Same shape as OFF-026 and the same limit: this counts links LABELLED ugc.
    Plenty of comment and forum links carry a plain nofollow or no label at all,
    so a low count is not proof that the profile was not built this way.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "link attribute mix")) is not None:
        return na

    labelled = int(profile.link_attributes.get("ugc", 0) or 0)
    pages = profile.referring_pages
    share = _share(labelled, pages)

    ev = {
        "links_labelled_ugc": labelled,
        "share_of_linking_pages": round(share, 3),
        "linking_pages": pages,
        "method": "counts links the linking site labelled rel=ugc; a comment or forum link "
                  "that carries only a plain nofollow is not visible to this measurement",
        "threshold_basis": "judgement; user-generated links are normal in any profile",
    }

    if share >= UGC_SHARE_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.7, ev,
            f"{labelled} of {pages} linking pages ({_pct(share)}%) are labelled as "
            f"user-generated, which means comments, forum posts and profile pages. Anyone "
            f"can place those, so Google discounts them heavily. The profile needs "
            f"editorial links from sites that chose to cite this one.",
        )
    return Verdict("pass", 10.0, "info", 0.7, ev)


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------

@check("OFF-035", scope="backlinks")
def check_sitewide_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-035 - template links repeated across every page of a linking site.

    No backlinks means no placements to analyse, so that case is n_a.

    Google's link spam policy names "widely distributed links in the footers or
    templates of various sites" as a link scheme. The measurable signature is a
    footer and header concentration together with many linking pages per
    referring domain: one placement, multiplied by the size of the other site.

    The provider leaves a large share of placements unclassified. That share is
    reported rather than folded into either side, because assuming an
    unclassified link sits in the body would understate the problem and
    assuming it sits in a footer would invent one.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "link placement")) is not None:
        return na
    locations = profile.semantic_locations or {}
    total = sum(int(v or 0) for v in locations.values())
    if total <= 0:
        return _na("the provider did not report where on the page these links sit, so "
                   "sitewide placement could not be measured",
                   referring_domains=profile.referring_domains)

    template = int(locations.get("footer", 0) or 0) + int(locations.get("header", 0) or 0)
    unclassified = int(locations.get("", 0) or 0)
    share = _share(template, total)
    domains = profile.referring_domains
    pages_per_domain = (profile.referring_pages / domains) if domains else 0.0

    ev = {
        "links_in_footer_or_header": template,
        "footer_or_header_share": round(share, 3),
        "linking_pages": total,
        "linking_pages_per_domain": round(pages_per_domain, 1),
        "placement_unclassified": unclassified,
        "threshold_basis": "Google link spam policy names widely distributed footer and "
                           "template links as a scheme; the shares are judgement",
    }

    heavy_repeat = pages_per_domain >= SITEWIDE_PAGES_PER_DOMAIN
    if share >= SITEWIDE_SHARE_FAIL or (heavy_repeat and share >= SITEWIDE_SHARE_WARN):
        return Verdict(
            "fail", 3.0, "major", 0.7, ev,
            f"{template} of {total} linking pages ({_pct(share)}%) place their link in a "
            f"footer or header, at {round(pages_per_domain, 1)} linking pages per referring "
            f"domain. That is one template placement repeated across each linking site, "
            f"which Google's link spam policy lists as a scheme. Identify the sites "
            f"involved and move the links into page copy, or have them removed.",
        )
    if share >= SITEWIDE_SHARE_WARN:
        return Verdict(
            "warn", 6.0, "minor", 0.7, ev,
            f"{template} of {total} linking pages ({_pct(share)}%) sit in a footer or "
            f"header. A partner or supplier credit in a footer is ordinary; a block of them "
            f"is not. Worth checking which sites these are before anything is changed.",
        )
    return Verdict("pass", 10.0, "info", 0.7, ev)


# --------------------------------------------------------------------------
# Toxicity
#
# Google Search Console help, "Disavow links to your site", is explicit that the
# tool is advanced, that it can harm a site's performance when used incorrectly,
# and that most sites should not use it without a manual action. Every finding
# below therefore says review, and none of them says disavow.
# --------------------------------------------------------------------------

@check("OFF-007", scope="backlinks")
def check_toxic_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-007 - the spam score of the incoming profile.

    No backlinks means nothing that could be toxic, so that case is n_a, as is a
    profile the provider scored no spam value for.

    The score is a third party's model of the linking sites, not a Google
    signal, and it has no published mapping to any Google action. It is reported
    as a prompt to look at the worst linking domains by hand. Disavowing healthy
    links costs more than leaving spam links alone, so the remediation asks for
    a review and stops there.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "incoming link")) is not None:
        return na
    score = profile.backlinks_spam_score
    if score is None or score < 0:
        return _na("the link provider returned no spam score for this profile, so its "
                   "toxicity was not measured",
                   referring_domains=profile.referring_domains)

    ev = {
        "link_spam_score": score,
        "referring_domains": profile.referring_domains,
        "linking_pages": profile.referring_pages,
        "threshold_basis": "provider spam score, 0 to 100, higher is worse; the bands are "
                           "judgement because no published mapping to a Google action exists",
    }

    if score >= SPAM_SCORE_FAIL:
        return Verdict(
            "fail", 3.0, "critical", 0.6, ev,
            f"The incoming link profile scores {score} out of 100 for spam across "
            f"{profile.referring_domains} referring domains. Pull the referring-domain list "
            f"and "
            f"review the worst of them by hand before anything is disavowed: disavowing "
            f"healthy links is the commoner and the more expensive mistake, and the tool is "
            f"meant for sites facing a manual action.",
        )
    if score >= SPAM_SCORE_WARN:
        return Verdict(
            "warn", 6.0, "major", 0.6, ev,
            f"The incoming link profile scores {score} out of 100 for spam across "
            f"{profile.referring_domains} referring domains. That is a prompt to review the "
            f"worst "
            f"referring domains by hand, not to disavow. Most profiles of this size carry "
            f"some junk that Google already ignores.",
        )
    return Verdict("pass", 10.0, "info", 0.6, ev)


@check("OFF-008", scope="backlinks")
def check_spam_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-008 - the site's OWN spam score, read against the incoming one.

    Distinct from OFF-007, which scores the links arriving. This one leads on
    the score the provider gives the audited domain itself, because the two
    answer different questions. A clean site with a spammy inbound profile is
    being linked to by junk it did not ask for. A site that scores badly itself
    has a problem no disavow file can reach.

    n_a when neither score was returned, and when the site has no links and no
    score of its own - there is nothing to read.
    """
    if (na := _unusable(profile)) is not None:
        return na
    target_score = profile.target_spam_score
    # A spam score computed over no incoming links is not a measurement of
    # anything, and reporting a clean 0 next to "0 referring domains" reads as
    # reassurance the data cannot support.
    link_score = profile.backlinks_spam_score if profile.has_links else None
    if target_score is None and link_score is None:
        return _na("neither the site nor its incoming links was given a spam score, so "
                   "this was not measured",
                   referring_domains=profile.referring_domains)
    if target_score is not None and target_score < 0:
        target_score = None
    if link_score is not None and link_score < 0:
        link_score = None
    if target_score is None and link_score is None:
        return _na("the provider returned no usable spam score for the site or its "
                   "incoming links, so this was not measured",
                   referring_domains=profile.referring_domains)

    ev = {
        "site_spam_score": target_score,
        "link_spam_score": link_score,
        "referring_domains": profile.referring_domains,
        "threshold_basis": "provider spam scores, 0 to 100, higher is worse; the bands are "
                           "judgement, and the site's own score is read first because no "
                           "disavow file changes it",
    }

    if target_score is not None and target_score >= TARGET_SPAM_FAIL:
        return Verdict(
            "fail", 2.0, "critical", 0.6, ev,
            f"The site itself scores {target_score} out of 100 for spam, against "
            f"{link_score if link_score is not None else 'no score'} for its incoming "
            f"links. A score attached to the domain rather than to its links points at the "
            f"site's own history, hosting neighbourhood or outbound links, and no disavow "
            f"file touches any of those. Review what the site links OUT to first.",
        )
    if target_score is not None and target_score >= TARGET_SPAM_WARN:
        return Verdict(
            "warn", 6.0, "major", 0.6, ev,
            f"The site itself scores {target_score} out of 100 for spam. It is low, but it "
            f"is not zero, and it is a score against the domain rather than against the "
            f"links pointing at it. Check the site's own outbound links and any pages left "
            f"behind by a previous owner or agency.",
        )
    if link_score is not None and link_score >= SPAM_SCORE_WARN:
        # The site is NOT itself scored as spammy here, so the sentence must not
        # imply it is. Junk pointing at a clean site is the ordinary case.
        own = ("scores 0 out of 100" if target_score == 0
               else f"scores {target_score} out of 100" if target_score is not None
               else "was given no spam score of its own")
        return Verdict(
            "warn", 6.0, "major", 0.6, ev,
            f"The site {own} while its incoming links score {link_score} out of 100. That "
            f"combination is what an unsolicited spam profile looks like: junk pointing at a "
            f"site that did not ask for it. Review the worst referring domains before "
            f"considering a disavow, which is a tool for sites facing a manual action.",
        )
    return Verdict("pass", 10.0, "info", 0.6, ev)


@check("OFF-038", scope="backlinks")
def check_link_farms(profile: BacklinkProfile) -> Verdict:
    """OFF-038 - many domains, few networks.

    A private network buys domains cheaply and hosts them together, so its
    arithmetic signature is a referring-domain count that far exceeds the number
    of distinct subnets behind it.

    Read as a prompt, never as proof, and the wording says so: shared hosting,
    Blogspot, Wix, Shopify and every CDN legitimately put thousands of unrelated
    sites on one subnet, so a high ratio has an innocent explanation at least as
    often as a guilty one.

    n_a when the site has no links, when the provider returned no subnet count,
    and when there are too few referring domains for the ratio to mean anything.
    """
    if (na := _unusable(profile)) is not None:
        return na
    if (na := _no_links(profile, "referring network")) is not None:
        return na

    domains = profile.referring_domains
    subnets = profile.referring_subnets
    if subnets <= 0:
        return _na("the provider returned no subnet count for these referring domains, so "
                   "their network spread was not measured",
                   referring_domains=domains)
    if domains < SUBNET_MIN_DOMAINS:
        return _na(f"only {domains} referring domains, too few for the spread across "
                   f"networks to mean anything",
                   referring_domains=domains, referring_subnets=subnets)

    ratio = domains / subnets
    ev = {
        "referring_domains": domains,
        "referring_subnets": subnets,
        "domains_per_subnet": round(ratio, 2),
        "referring_ips": profile.referring_ips,
        "threshold_basis": "judgement; shared hosting and blog platforms put unrelated "
                           "sites on one subnet, so the ratio prompts a review rather than "
                           "proving a network",
    }

    if ratio >= SUBNET_RATIO_FAIL:
        return Verdict(
            "fail", 3.0, "critical", 0.55, ev,
            f"{domains} referring domains sit on only {subnets} subnets, {round(ratio, 1)} "
            f"domains per network. A private network hosts its domains together and this is "
            f"the arithmetic it produces. Shared hosting produces it innocently too, so "
            f"pull the referring domains grouped by network and look at the largest group "
            f"before anything is disavowed.",
        )
    if ratio >= SUBNET_RATIO_WARN:
        return Verdict(
            "warn", 6.0, "major", 0.55, ev,
            f"{domains} referring domains across {subnets} subnets, {round(ratio, 1)} "
            f"domains per network. Most of that is ordinary shared hosting. Worth grouping "
            f"the referring domains by network once to see whether one operator accounts "
            f"for a block of them.",
        )
    return Verdict("pass", 10.0, "info", 0.55, ev)
