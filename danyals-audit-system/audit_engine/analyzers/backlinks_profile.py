"""Volume, authority, quality and history, read off ONE fetched profile.

Twelve of the thirty-nine backlink checks ask the same question from different
angles: is there a link profile at all, where did it come from, how strong is
it, and is it rotting. Those angles share one input, so they share one fetch.

``backlinks/summary`` is billed per REQUEST, not per field. Fetching it once and
answering twelve checks costs about 2.4 cents; fetching it per check would cost
twelve times that and, worse, would give twelve slightly different snapshots of
one site to disagree over. That is why every function here takes an already
fetched :class:`~audit_engine.integrations.dataforseo.BacklinkProfile` rather
than a target string.

**What the profile is, and what it is not.** It is a set of scalars and
distributions describing the profile as it stands today. It carries no per-link
list, no month-by-month history and no competitor data. Three checks below
therefore report ``n_a`` with a reason a client can read, rather than answering
a nearby question under the wrong heading.

**One empty profile, one finding.** A site with no backlinks is a valid and
common answer, not an error. OFF-002 and OFF-004 carry that finding, because
"no authority" and "no profile" are the two sentences a client needs. Every
other check here returns ``n_a`` on an empty profile: twelve failures for one
fact reads as twelve problems.

**Thresholds.** Google publishes almost nothing for backlinks - no authority
metric, no safe acquisition rate, no toxicity ratio. So every band below is
either the provider's own documented scale or is marked ``JUDGEMENT`` with the
reason it was chosen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check
from audit_engine.integrations.dataforseo import BacklinkProfile

# --------------------------------------------------------------------------
# Scales and bands
# --------------------------------------------------------------------------

#: The provider documents ``rank`` as a 0-1000 score from an internal PageRank
#: over its own link graph. The SCALE is the provider's. The bands are not.
RANK_SCALE_MAX = 1000

# JUDGEMENT: Google publishes no domain authority metric and the provider
# publishes no bands for its own, so these two lines are ours. They sit low
# because the scale is logarithmic: clearing 100 takes a handful of genuine
# editorial links, clearing 300 usually takes years of them.
RANK_LOW = 100
RANK_ESTABLISHED = 300

# JUDGEMENT: past roughly thirty links per referring domain the extra volume is
# repetition - one footer, blogroll or sidebar widget rendered on every page of
# a single site. Google consolidates repeated links from one domain, so the
# extra links are not extra signal. This is a "read the number differently"
# threshold, never a penalty threshold.
LINKS_PER_DOMAIN_TEMPLATED = 30.0

# JUDGEMENT: fewer subnets than half the referring domains means a large share
# of those domains share hosting. That is equally true of a cheap link network
# and of one honest regional host, which is why it can only ever prompt a look.
SUBNET_SPREAD_LOW = 0.5

# JUDGEMENT: above 60% of PLACED links sitting in a header or footer, the
# profile is template placements rather than editorial mentions. Google
# discounts sitewide template links; it does not act against them.
TEMPLATE_PLACEMENT_HIGH = 0.6

# JUDGEMENT: below 80% root domains, a sizeable part of the profile comes from
# free subdomain hosts, which is a different quality of link from the same
# count earned on domains someone paid to register.
ROOT_DOMAIN_SHARE_LOW = 0.8

# JUDGEMENT: a broken backlink is the cheapest recoverable equity in SEO, one
# redirect each, so 1% is worth raising and past 5% the loss is material.
BROKEN_SHARE_REVIEW = 0.01
BROKEN_SHARE_MATERIAL = 0.05

# JUDGEMENT: Google has never published an acquisition rate and no rate is a
# penalty on its own. Fifty new referring domains a month, sustained across the
# whole life of a small site, is simply unusual enough to read the list before
# trusting it.
VELOCITY_REVIEW_RD_PER_MONTH = 50.0

# JUDGEMENT: a loss recorded inside the last quarter is usually recoverable -
# the linking page normally still exists and its editor still remembers why the
# link was there.
LOST_RECENT_DAYS = 90

# JUDGEMENT: a lifetime average over less than a month is one month's noise
# presented as a rate.
MIN_AGE_FOR_RATE_DAYS = 30

#: The provider scores spam 0-100 across the referring set.
SPAM_SCALE_MAX = 100
# JUDGEMENT: half the scale. Below it, the number is describing the ordinary
# tail of scraped and directory links that every profile on the web carries.
SPAM_REVIEW = 50

# JUDGEMENT: five hundred links is enough volume that its failure to produce
# any authority is the finding, rather than the site simply being new.
VOLUME_WITHOUT_AUTHORITY_BACKLINKS = 500

#: Mean Gregorian month, so a monthly rate does not swing with the calendar.
DAYS_PER_MONTH = 30.44

#: Where on a referring page a link sits. The provider's own vocabulary.
TEMPLATE_LOCATIONS = ("header", "footer")
EDITORIAL_LOCATIONS = ("article", "main", "section")


# --------------------------------------------------------------------------
# Guards. n_a means NOT MEASURED - never a zero dressed up as a score.
# --------------------------------------------------------------------------

def _na(reason: str, **ev: Any) -> Verdict:
    """Confidence 0.0 keeps an unmeasured check out of the weighted mean, and
    a measurement that never happened can carry no remediation."""
    return Verdict("n_a", 0.0, "info", 0.0, {"reason": reason, **ev})


def _unavailable(profile: BacklinkProfile | None) -> Verdict | None:
    """No fetch and a failed fetch are both "not measured", and neither is a
    site with bad links. Every check starts here."""
    if profile is None:
        return _na("the backlink profile was not fetched for this audit")
    if profile.error:
        return _na(f"the backlink data could not be retrieved: {profile.error}")
    return None


def _empty(profile: BacklinkProfile) -> bool:
    return not profile.has_links and profile.backlinks <= 0


def _parse_stamp(stamp: str | None) -> datetime | None:
    """The provider stamps ``2023-06-22 09:41:04 +00:00``. A stamp we cannot
    parse must read as absent, never as today."""
    if not stamp:
        return None
    text = stamp.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace(" +", "+").replace(" ", "T", 1))
    except ValueError:
        return None


def _age_days(stamp: str | None) -> int | None:
    when = _parse_stamp(stamp)
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - when).days)


def _rank_of(profile: BacklinkProfile) -> int:
    """The dataclass stores a rank of 0 as ``None``, so both mean "no measured
    strength" and both must read as 0 to a client."""
    return int(profile.rank or 0)


# --------------------------------------------------------------------------
# Authority
# --------------------------------------------------------------------------

@check("OFF-002", scope="backlinks")
def check_domain_rating(profile: BacklinkProfile) -> Verdict:
    """OFF-002 - the provider's 0-1000 domain rank.

    An empty profile is a REAL FINDING here, not n_a: no links is precisely why
    the rank is nothing, and that is the sentence the client needs to read.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    rank = _rank_of(profile)
    ev = {
        "domain_rank": rank,
        "rank_scale_max": RANK_SCALE_MAX,
        "referring_domains": profile.referring_domains,
        "backlinks": profile.backlinks,
        "metric_note": "a third-party link-graph score on a 0-1000 logarithmic scale, "
                       "not a Google metric; Google publishes no domain authority number",
        "threshold_basis": "judgement; the provider publishes no bands for its own scale",
    }
    if _empty(profile):
        return Verdict(
            "fail", 0.0, "major", 1.0, ev,
            f"No other site links to this domain: 0 referring domains, 0 backlinks, "
            f"rank {rank} of {RANK_SCALE_MAX}. Authority has to be earned from somewhere "
            f"else first, so the first ten links matter more here than any on-page work.",
        )
    if rank >= RANK_ESTABLISHED:
        return Verdict("pass", 10.0, "info", 0.8, ev)
    if rank >= RANK_LOW:
        return Verdict("pass", 8.0, "info", 0.8, ev)
    return Verdict(
        "warn", 5.0, "minor", 0.8, ev,
        f"{profile.referring_domains} referring domains have produced a rank of {rank} "
        f"of {RANK_SCALE_MAX}, below the {RANK_LOW} mark. The links exist but they are "
        f"not carrying much strength, which points at where they come from rather than "
        f"how many there are.",
    )


@check("OFF-070", scope="backlinks")
def check_trust_flow(profile: BacklinkProfile) -> Verdict:
    """OFF-070 - trust, by PROXY.

    Trust Flow is Majestic's metric and this audit does not buy Majestic, so
    this reads the two things the profile does carry: the 0-1000 domain rank and
    the 0-100 spam score of the referring set. The evidence says "proxy" out
    loud, because a client holding a Majestic number beside this one is not
    looking at the same measurement.

    An empty profile is n_a: there is no referring set to score. OFF-002 and
    OFF-004 carry the finding that it is empty.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so there is no referring set to score for trust")
    rank = _rank_of(profile)
    spam = profile.backlinks_spam_score
    spam_known = spam is not None and spam >= 0
    ev = {
        "domain_rank": rank,
        "rank_scale_max": RANK_SCALE_MAX,
        "backlinks_spam_score": spam if spam_known else None,
        "spam_scale_max": SPAM_SCALE_MAX,
        "target_spam_score": profile.target_spam_score,
        "referring_domains": profile.referring_domains,
        "metric_note": "proxy: Majestic Trust Flow is not purchased for this audit, so "
                       "trust is read from the provider's 0-1000 domain rank and its "
                       "0-100 spam score for the referring set",
        "threshold_basis": "judgement; neither Google nor the provider publishes bands",
    }
    if spam_known and spam >= SPAM_REVIEW:
        return Verdict(
            "warn", 5.0, "minor", 0.5, ev,
            f"The referring set scores {spam} of {SPAM_SCALE_MAX} on the provider's spam "
            f"scale, against a rank of {rank} of {RANK_SCALE_MAX}. Pull the referring "
            f"domain list and review it before disavowing anything: Google ignores most "
            f"low-quality links on its own, and disavowing healthy links is the commoner "
            f"and far more expensive mistake.",
        )
    if rank >= RANK_ESTABLISHED:
        return Verdict("pass", 10.0, "info", 0.5 if spam_known else 0.4, ev)
    if rank >= RANK_LOW:
        return Verdict("pass", 8.0, "info", 0.5 if spam_known else 0.4, ev)
    return Verdict(
        "warn", 6.0, "minor", 0.5 if spam_known else 0.4, ev,
        f"Rank {rank} of {RANK_SCALE_MAX} from {profile.referring_domains} referring "
        f"domains. On this proxy the profile is clean rather than strong: nothing here "
        f"looks spammy, there is simply not much trust flowing in yet.",
    )


@check("OFF-071", scope="backlinks")
def check_citation_flow(profile: BacklinkProfile) -> Verdict:
    """OFF-071 - citation volume, by PROXY.

    Citation Flow is Majestic's metric and is not purchased. Raw link volume is
    the proxy, and the evidence says so. The pattern worth naming is volume
    WITHOUT authority: plenty of links, almost no rank, which is what a scraped,
    bought or template-repeated profile looks like from the outside.

    An empty profile is n_a: OFF-004 already reports that there is no volume.
    Low-but-real volume is left to OFF-005, which owns the count itself.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so there is no citation volume to read")
    rank = _rank_of(profile)
    ev = {
        "backlinks": profile.backlinks,
        "referring_domains": profile.referring_domains,
        "referring_pages": profile.referring_pages,
        "domain_rank": rank,
        "rank_scale_max": RANK_SCALE_MAX,
        "metric_note": "proxy: Majestic Citation Flow is not purchased for this audit, so "
                       "citation volume is read as the count of live backlinks and the "
                       "pages carrying them",
        "threshold_basis": "judgement; volume alone has no published safe or unsafe level",
    }
    if profile.backlinks >= VOLUME_WITHOUT_AUTHORITY_BACKLINKS and rank < RANK_LOW:
        return Verdict(
            "warn", 5.0, "minor", 0.5, ev,
            f"{profile.backlinks:,} backlinks from {profile.referring_domains} referring "
            f"domains have produced a rank of only {rank} of {RANK_SCALE_MAX}. Volume that "
            f"does not convert into authority usually means the links are repeated, scraped "
            f"or paid for. Review the referring list before disavowing anything; disavowing "
            f"healthy links is the commoner and more expensive mistake.",
        )
    if rank >= RANK_LOW:
        return Verdict("pass", 10.0, "info", 0.5, ev)
    return Verdict("pass", 8.0, "info", 0.5, ev)


# --------------------------------------------------------------------------
# Shape and volume
# --------------------------------------------------------------------------

@check("OFF-004", scope="backlinks")
def check_backlink_profile(profile: BacklinkProfile) -> Verdict:
    """OFF-004 - the shape of the profile: how many links, from how many places.

    An empty profile is a REAL FINDING here, not n_a. The shape of an empty
    profile is the single most important thing this audit can say about it, and
    this check is where that sentence belongs.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    domains = profile.referring_domains
    per_domain = round(profile.backlinks / domains, 2) if domains else 0.0
    subnet_spread = round(profile.referring_subnets / domains, 2) if domains else 0.0
    ev = {
        "backlinks": profile.backlinks,
        "referring_domains": domains,
        "referring_main_domains": profile.referring_main_domains,
        "referring_pages": profile.referring_pages,
        "referring_ips": profile.referring_ips,
        "referring_subnets": profile.referring_subnets,
        "referring_domains_nofollow": profile.referring_domains_nofollow,
        "backlinks_per_referring_domain": per_domain,
        "subnets_per_referring_domain": subnet_spread,
        "templated_ratio_threshold": LINKS_PER_DOMAIN_TEMPLATED,
        "threshold_basis": "judgement; Google publishes no profile shape targets",
    }
    if _empty(profile):
        return Verdict(
            "fail", 0.0, "major", 1.0, ev,
            "There is no backlink profile to analyse: 0 backlinks from 0 referring "
            "domains. Every other off-page measurement in this report is empty for the "
            "same reason, so the first task is acquiring links at all, not tidying them.",
        )
    concerns: list[str] = []
    if per_domain > LINKS_PER_DOMAIN_TEMPLATED:
        concerns.append(
            f"{profile.backlinks:,} backlinks come from only {domains} referring domains "
            f"({per_domain} per domain), so most of the volume is one link repeated across "
            f"a site rather than {domains} separate endorsements"
        )
    if subnet_spread < SUBNET_SPREAD_LOW:
        concerns.append(
            f"{domains} referring domains sit on only {profile.referring_subnets} subnets, "
            f"so a large share of them share hosting"
        )
    if not concerns:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    return Verdict(
        "warn", 6.0, "minor", 0.9, ev,
        "Profile shape worth reading before the headline count: "
        + "; ".join(concerns)
        + ". Neither is a penalty on its own, and neither is a reason to disavow; both "
          "mean the profile is narrower than the backlink total suggests.",
    )


@check("OFF-011", scope="backlinks")
def check_high_authority_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-011 - how much of the profile sits on real domains, and what strength
    that produced.

    The purchased summary scores the TARGET, not each link, so "how many links
    come from high authority sites" cannot be counted here; that needs the
    per-link endpoint this audit does not buy. What can be measured is stated:
    the share of referring domains that are root domains rather than free
    subdomains, read against the rank those links actually produced.

    An empty profile is n_a: there is nothing to classify. OFF-002 and OFF-004
    carry that finding.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no referring domains were found, so none can be classified by authority")
    domains = profile.referring_domains
    root_share = round(profile.referring_main_domains / domains, 3) if domains else 0.0
    rank = _rank_of(profile)
    ev = {
        "referring_domains": domains,
        "referring_main_domains": profile.referring_main_domains,
        "root_domain_share": root_share,
        "domain_rank": rank,
        "rank_scale_max": RANK_SCALE_MAX,
        "limit": "per-link authority scores are not purchased for this audit, so this "
                 "reports the two aggregate signals the profile does carry",
        "threshold_basis": "judgement; no published threshold exists for either signal",
    }
    problems: list[str] = []
    if root_share < ROOT_DOMAIN_SHARE_LOW:
        problems.append(
            f"only {profile.referring_main_domains} of {domains} referring domains are root "
            f"domains ({round(root_share * 100)}%), so the rest are subdomains on shared or "
            f"free hosts"
        )
    if rank < RANK_LOW:
        problems.append(
            f"{domains} referring domains have produced a rank of {rank} of {RANK_SCALE_MAX}, "
            f"which is what a profile of low-authority sources looks like in aggregate"
        )
    if not problems:
        return Verdict("pass", 9.0, "info", 0.5, ev)
    # NOT .capitalize(): it lowercases everything after the first character,
    # so a sentence carrying a second clause comes back with its wording flattened.
    said = "; ".join(problems)
    return Verdict(
        "warn", 6.0, "minor", 0.5, ev,
        said[:1].upper() + said[1:]
        + ". Target the next links at sites that already rank for your topic; ten of those "
          "move the number that thousands of directory profiles do not.",
    )


@check("OFF-015", scope="backlinks")
def check_homepage_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-015 - where each link sits on the page that carries it.

    The split between links pointing at the homepage and links pointing at inner
    pages needs the per-link endpoint and is not purchased, so this check does
    not guess at it. What the profile does carry is the semantic location of
    each link on the REFERRING page: a link inside an article body is an
    editorial mention, a link repeated in a header or footer is a template
    placement, and Google weighs the two very differently.

    An empty profile is n_a: there are no placements to locate.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so there are no link placements to locate")
    locations = profile.semantic_locations or {}
    template = sum(int(locations.get(k, 0) or 0) for k in TEMPLATE_LOCATIONS)
    editorial = sum(int(locations.get(k, 0) or 0) for k in EDITORIAL_LOCATIONS)
    classified = sum(int(v or 0) for k, v in locations.items() if k.strip())
    unknown = sum(int(v or 0) for k, v in locations.items() if not k.strip())
    share = round(template / classified, 3) if classified else 0.0
    ev = {
        "referring_pages": profile.referring_pages,
        "links_in_article": int(locations.get("article", 0) or 0),
        "links_in_main": int(locations.get("main", 0) or 0),
        "links_in_section": int(locations.get("section", 0) or 0),
        "links_in_header": int(locations.get("header", 0) or 0),
        "links_in_footer": int(locations.get("footer", 0) or 0),
        "links_with_no_recorded_location": unknown,
        "editorial_placements": editorial,
        "template_placements": template,
        "template_placement_share": share,
        "template_share_threshold": TEMPLATE_PLACEMENT_HIGH,
        "limit": "which URL each link points at is not purchased, so this measures the "
                 "placement of the link on the referring page, not the page it targets",
        "threshold_basis": "judgement; Google discounts sitewide template links but "
                           "publishes no ratio",
    }
    if not classified:
        return _na(
            f"the provider recorded no placement for any of the {profile.referring_pages} "
            f"referring pages, so nothing can be said about where the links sit",
            **ev,
        )
    # Confidence tracks how much of the profile was actually located. A profile
    # where most links have a blank location is a weak read, not a wrong one.
    located_share = classified / max(1, classified + unknown)
    confidence = 0.7 if located_share >= 0.5 else 0.5
    if share >= TEMPLATE_PLACEMENT_HIGH:
        return Verdict(
            "warn", 6.0, "minor", confidence, ev,
            f"{template} of {classified} placed links sit in a header or footer "
            f"({round(share * 100)}%) against {editorial} in article or main content. "
            f"Sitewide template links are consolidated and discounted, so the profile is "
            f"thinner than the {profile.backlinks:,} backlink count suggests. Weight the "
            f"next placements towards editorial mentions inside page copy.",
        )
    return Verdict("pass", 10.0, "info", confidence, ev)


@check("OFF-016", scope="backlinks")
def check_deep_page_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-016 - whether there are enough links to reach past the homepage.

    Which URLs the links point at is not in the purchased data. One thing is
    still provable from two counts: a site cannot have more linked pages than it
    has backlinks, so a site with fewer backlinks than pages certainly has pages
    carrying none. That is what this reports, and the evidence names the limit.

    An empty profile is n_a here, as is a site the provider reported no page
    count for.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so no page of this site has one")
    pages = profile.crawled_pages
    if pages <= 0:
        return _na(
            "the provider reported no page count for this site, so link coverage cannot "
            "be compared against its size",
            backlinks=profile.backlinks,
            referring_pages=profile.referring_pages,
        )
    unlinkable = max(0, pages - profile.backlinks)
    ev = {
        "backlinks": profile.backlinks,
        "referring_pages": profile.referring_pages,
        "crawled_pages": pages,
        "backlinks_per_crawled_page": round(profile.backlinks / pages, 2),
        "pages_that_can_hold_no_backlink": unlinkable,
        "limit": "the per-URL split between homepage and inner pages is not purchased; "
                 "crawled_pages is the provider's own count of this site's pages, not a "
                 "full crawl of it",
        "threshold_basis": "arithmetic, not judgement: linked pages cannot exceed backlinks",
    }
    if unlinkable > 0:
        return Verdict(
            "fail", 3.0, "major", 0.8, ev,
            f"{profile.backlinks:,} backlinks across {pages:,} pages: at least {unlinkable:,} "
            f"of those {'pages carries' if unlinkable == 1 else 'pages carry'} no external link "
            f"at all. Deep pages that rank have to be "
            f"reached internally instead, so link the money pages from the pages that do have "
            f"external links, and point the next campaigns at inner URLs rather than the home page.",
        )
    return Verdict("pass", 8.0, "info", 0.5, ev)


# --------------------------------------------------------------------------
# History: age, velocity, loss and decay
# --------------------------------------------------------------------------

@check("OFF-006", scope="backlinks")
def check_link_velocity(profile: BacklinkProfile) -> Verdict:
    """OFF-006 - the rate at which links arrived, averaged over the profile's life.

    The purchased summary carries ONE date, the first backlink ever seen, so the
    only honest velocity is a lifetime average. It cannot see a spike, and it
    cannot see last month. The evidence says that rather than implying a trend.

    An empty profile is n_a: there is no rate to average. So is a profile
    younger than a month, where an average is one month of noise.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so there is no acquisition rate to measure")
    age = _age_days(profile.first_seen)
    if age is None:
        return _na(
            "the provider recorded no date for the earliest backlink, so the profile's age "
            "is unknown and no rate can be averaged over it",
            backlinks=profile.backlinks,
            referring_domains=profile.referring_domains,
        )
    if age < MIN_AGE_FOR_RATE_DAYS:
        return _na(
            f"the earliest backlink was found {age} days ago, too short a window to average "
            f"a monthly acquisition rate over",
            backlinks=profile.backlinks,
            referring_domains=profile.referring_domains,
            earliest_backlink_seen=profile.first_seen,
        )
    months = age / DAYS_PER_MONTH
    rd_rate = round(profile.referring_domains / months, 2)
    link_rate = round(profile.backlinks / months, 2)
    ev = {
        "earliest_backlink_seen": profile.first_seen,
        "profile_age_days": age,
        "backlinks": profile.backlinks,
        "referring_domains": profile.referring_domains,
        "referring_domains_per_month": rd_rate,
        "backlinks_per_month": link_rate,
        "review_rate_threshold": VELOCITY_REVIEW_RD_PER_MONTH,
        "limit": "a lifetime average, not a recent rate; the month-by-month series is a "
                 "separate purchase this audit does not make",
        "threshold_basis": "judgement; Google publishes no acquisition rate of any kind",
    }
    if rd_rate >= VELOCITY_REVIEW_RD_PER_MONTH:
        return Verdict(
            "warn", 6.0, "minor", 0.4, ev,
            f"{profile.referring_domains} referring domains arrived over {age} days, an "
            f"average of {rd_rate} a month. No rate is a penalty by itself and this average "
            f"hides whatever the real pattern was, so read the referring domain list and "
            f"confirm these are links you would claim. Do not disavow on a rate alone.",
        )
    return Verdict("pass", 10.0, "info", 0.6, ev)


@check("OFF-009", scope="backlinks")
def check_lost_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-009 - links this site used to have.

    The summary reports the DATE of the most recent recorded loss, not the list
    of what was lost; that list is a separate purchase. A recent loss is worth
    chasing because the linking page usually still exists.

    An empty profile is n_a: nothing can have been lost from a profile that
    never had anything.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so none can be recorded as lost")
    lost_age = _age_days(profile.lost_date)
    ev = {
        "last_recorded_loss": profile.lost_date,
        "days_since_last_loss": lost_age,
        "backlinks": profile.backlinks,
        "referring_domains": profile.referring_domains,
        "broken_backlinks": profile.broken_backlinks,
        "recent_loss_window_days": LOST_RECENT_DAYS,
        "limit": "the provider reports the date of the most recent loss, not the list of "
                 "lost links; that per-link history is not purchased for this audit",
        "threshold_basis": "judgement; a link lost inside a quarter is usually still "
                           "recoverable, which is the only reason the window exists",
    }
    if profile.lost_date is None or lost_age is None:
        return Verdict("pass", 10.0, "info", 0.6, ev)
    if lost_age <= LOST_RECENT_DAYS:
        return Verdict(
            "warn", 6.0, "minor", 0.6, ev,
            f"The most recent backlink loss was recorded on {profile.lost_date}, {lost_age} "
            f"days ago, against {profile.backlinks:,} live backlinks. Open the referring page: "
            f"a link removed this recently is usually recoverable with one email, and if the "
            f"page itself has gone the loss is permanent and worth replacing.",
        )
    return Verdict("pass", 9.0, "info", 0.6, ev)


@check("OFF-010", scope="backlinks")
def check_new_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-010 - newly acquired backlinks. Not answerable from this data.

    Informational by design, and the honest answer is that the profile bought
    for this audit is a snapshot of what is live today with no date on each
    link. Naming a "new" link would need the historical endpoint, which is a
    separate purchase. Reported as n_a for every site, empty or not, rather
    than dressed up as a nearby number.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na(
        "a list of newly acquired backlinks needs the provider's historical endpoint, "
        "which this audit does not purchase; the profile bought here is a snapshot of "
        "what is live today, with no acquisition date on the individual links",
        backlinks=profile.backlinks,
        referring_domains=profile.referring_domains,
        earliest_backlink_seen=profile.first_seen,
    )


@check("OFF-060", scope="backlinks")
def check_link_decay(profile: BacklinkProfile) -> Verdict:
    """OFF-060 - backlinks pointing at URLs on this site that no longer resolve.

    This is decay the site owner caused and the site owner can undo: the link
    was earned, the target page was moved or deleted, and one redirect brings
    the value back.

    An empty profile is n_a: nothing can decay from a profile with no links.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if _empty(profile):
        return _na("no backlinks were found, so none of them can be pointing at a dead URL")
    broken = profile.broken_backlinks
    share = round(broken / profile.backlinks, 4) if profile.backlinks else 0.0
    ev = {
        "broken_backlinks": broken,
        "backlinks": profile.backlinks,
        "broken_backlink_share": share,
        "broken_pages": profile.broken_pages,
        "review_share_threshold": BROKEN_SHARE_REVIEW,
        "material_share_threshold": BROKEN_SHARE_MATERIAL,
        "threshold_basis": "judgement; Google publishes no ratio, but a broken backlink is "
                           "one redirect away from working, so the bar is deliberately low",
    }
    if broken == 0:
        return Verdict("pass", 10.0, "info", 0.9, ev)
    # Google's own guidance: a redirect to an irrelevant page, the home page
    # being the usual choice, is treated as a soft 404 and passes nothing. Say
    # the fix precisely or it will be done the way that does not work.
    fix = (
        "301 each of those URLs to the closest equivalent live page. A redirect to the home "
        "page does not work: Google treats an irrelevant redirect as a soft 404."
    )
    # One broken backlink is still worth a sentence, so the prose has to read
    # correctly at a count of one as well as at a count of nine hundred.
    noun, verb = ("backlink", "points") if broken == 1 else ("backlinks", "point")
    if share >= BROKEN_SHARE_MATERIAL:
        return Verdict(
            "fail", 4.0, "major", 0.9, ev,
            f"{broken:,} of {profile.backlinks:,} {noun} ({round(share * 100, 1)}%) {verb} at "
            f"URLs on this site that return an error, and the provider found "
            f"{profile.broken_pages} broken pages here. {fix}",
        )
    return Verdict(
        "warn", 8.0, "minor", 0.9, ev,
        f"{broken:,} of {profile.backlinks:,} {noun} {verb} at URLs on this site that return "
        f"an error. {fix}",
    )


@check("OFF-061", scope="backlinks")
def check_backlink_trend(profile: BacklinkProfile) -> Verdict:
    """OFF-061 - the direction of the profile over time. Not answerable here.

    A trend needs a series. The purchased profile carries two dates - the first
    backlink ever seen, and the most recent recorded loss - and two dates cannot
    say whether the profile grew or shrank last quarter. The lifetime average in
    OFF-006 is a rate, not a trend, and reporting it under this heading would be
    answering a different question with the same number. n_a for every site,
    with the dates carried as context.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na(
        "a month-by-month backlink history is a separate purchase this audit does not make; "
        "the profile bought here holds one date for the earliest link and one for the most "
        "recent loss, which cannot show whether the profile is growing or shrinking",
        earliest_backlink_seen=profile.first_seen,
        profile_age_days=_age_days(profile.first_seen),
        last_recorded_loss=profile.lost_date,
        backlinks=profile.backlinks,
        referring_domains=profile.referring_domains,
    )
