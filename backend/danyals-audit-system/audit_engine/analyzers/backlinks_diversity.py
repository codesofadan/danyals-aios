"""Diversity, link types, and the competitive position this audit does not buy.

Sixteen checks that read one fetched :class:`BacklinkProfile`: how spread out
the referring hosts are, what KIND of link each one is, which of them already
land on a dead page, and the competitor comparisons nobody paid for.

**Why one profile rather than one call per check.** ``backlinks/summary``
returns every distribution read here - IPs, subnets, countries, TLDs, platform
types, link types - in a single response, and a second request adds the anchor
text. Two requests, about five cents, answer all thirty-nine backlink checks.
One call per check would multiply the bill by nineteen and return the same
numbers nineteen times.

**What these distributions actually are.** The client asks the provider for
``internal_list_limit: 10``, so each distribution is the ten largest buckets and
not the whole tail: on a real response ``referring_links_tld`` and
``referring_links_countries`` both come back with exactly ten entries summing to
less than the link count. So a share here is a share of what was itemised, and a
category missing from a distribution that is AT the limit may simply sit below
the cut. Missing-below-the-cut is n_a, missing-with-room-to-spare is zero, and
``_absent_bucket_is_zero`` is the only place that distinction is made.

Google publishes almost no numeric thresholds for backlinks, so nearly every
constant below is marked JUDGEMENT with the reason it sits where it does.
Nothing here tells a client to disavow. Disavowing healthy links is the more
common and the more expensive mistake, so every concentration finding says
review the domains first.
"""

from __future__ import annotations

from typing import Any

from audit_engine.analyzers.common import Verdict
from audit_engine.analyzers.registry import check
from audit_engine.integrations.dataforseo import BacklinkProfile

#: Mirrors ``internal_list_limit`` in the summary request. A distribution
#: holding this many buckets was probably cut short; one holding fewer was not.
INTERNAL_LIST_LIMIT = 10

# JUDGEMENT: no published Google figure exists for host diversity. Shared
# hosting is normal and cheap, so a profile can sit well under one IP per domain
# and still be entirely honest. 0.70 is where the average host starts carrying
# more than one of this site's referring domains; below 0.40 the average host
# carries two and a half of them, which shared hosting alone rarely produces
# across an otherwise unrelated set of sites.
IP_DIVERSITY_GOOD = 0.70
IP_DIVERSITY_POOR = 0.40

# JUDGEMENT: a /24 is the block one provider hands to one customer, so IPs that
# share a subnet usually share a rack and an operator. Same reasoning, same
# shape, one notch tighter at the bottom because subnet clustering has fewer
# innocent explanations than shared hosting does.
SUBNET_DIVERSITY_GOOD = 0.70
SUBNET_DIVERSITY_POOR = 0.45

# JUDGEMENT: below ten referring domains any of these ratios is noise - one
# extra domain moves it by ten points - so a thin profile is never failed on a
# ratio, only reported with the confidence lowered.
DIVERSITY_SAMPLE_FLOOR = 10

# JUDGEMENT: a business that sells abroad legitimately earns most of its links
# abroad, so a low home-country share cannot fail on its own. The pattern worth
# reporting is a low home share PLUS one unrelated country holding a third of
# the profile, which is the shape a bought network leaves.
HOME_COUNTRY_HEALTHY_SHARE = 0.25
HOME_COUNTRY_THIN_SHARE = 0.10
FOREIGN_CONCENTRATION_SHARE = 0.35

#: Neither key names a country: the empty string is a link the provider could
#: not place, and WW is not an assigned ISO 3166-1 alpha-2 code. Scoring either
#: for or against local relevance would be inventing a fact.
UNATTRIBUTED_COUNTRY_KEYS = frozenset({"", "WW"})

#: The default choice worldwide, so a profile dominated by them is the expected
#: shape of the web rather than a cluster worth explaining.
GENERIC_TLDS = frozenset({"com", "net", "org"})

#: TLDs that sit at the top of published abuse tables - Spamhaus ranks
#: registries by abuse rate and Interisle's phishing reports do the same.
#: JUDGEMENT: which of them appear here is our call, and it is a prompt to LOOK,
#: never a verdict. Google has said repeatedly that a TLD is not itself a
#: ranking signal, so the finding is about a cluster of throwaway domains.
HIGH_ABUSE_TLDS = frozenset({
    "xyz", "top", "buzz", "icu", "cyou", "sbs", "cfd", "bond", "rest", "quest",
    "click", "link", "monster", "loan", "men", "gq", "cf", "ml", "ga", "tk",
})

# JUDGEMENT: one TLD holding a quarter of an itemised profile means a single
# national or platform cluster is a quarter of the link graph, which is rarely
# how links arrive on their own. Generic TLDs are exempt for the reason above.
SINGLE_TLD_CONCENTRATION = 0.25
# JUDGEMENT: a sixth of the profile on high-abuse extensions is past what a
# normal spread produces by accident, and is worth an hour of review.
HIGH_ABUSE_TLD_SHARE = 0.15

# JUDGEMENT thresholds for link KIND. None of these is a Google number. Each is
# the point at which one category stops being part of a mix and starts being the
# profile, which is what makes a pattern visible from outside.
NEWS_HEAVY_SHARE = 0.25
FORUM_HEAVY_SHARE = 0.20
REDIRECT_HEAVY_SHARE = 0.15
IMAGE_HEAVY_SHARE = 0.30

# JUDGEMENT: any backlink landing on a dead page is recoverable value, so one is
# reported. Past a twentieth of the whole profile the losses stop being tidy-up
# and start being a measurable share of the site's earned authority.
BROKEN_BACKLINK_SERIOUS_SHARE = 0.05

#: Substrings, not exact keys. The provider owns its category names, and a
#: hardcoded key the response never contains would score every site zero while
#: looking like a working check.
FORUM_WORDS = ("forum", "message", "board")
PROFILE_WORDS = ("profile", "social", "bookmark", "directory")
VIDEO_WORDS = ("video", "youtube", "vimeo", "tube")
REDIRECT_WORDS = ("redirect",)
NEWS_WORDS = ("news", "press")
IMAGE_WORDS = ("image",)

_DISAVOW = ("Review those domains before disavowing anything: disavowing healthy links is "
            "the more common and the more expensive mistake.")


# --------------------------------------------------------------------------
# Guards. Every one of them exists so that "we did not measure it" can never be
# reported as a zero.
# --------------------------------------------------------------------------

def _na(reason: str, **ev: Any) -> Verdict:
    return Verdict("n_a", 0.0, "info", 0.0, {"reason": reason, **ev})


def _unavailable(profile: BacklinkProfile | None) -> Verdict | None:
    """No profile means NOT MEASURED. It never means a score of zero."""
    if profile is None:
        return _na("the backlink profile was not fetched for this audit, so nothing in this "
                   "group was measured")
    if profile.error:
        return _na(f"the backlink provider returned no profile for this domain: "
                   f"{str(profile.error)[:110]}")
    return None


def _no_links(profile: BacklinkProfile) -> Verdict | None:
    """A site with no backlinks is a valid answer. A DISTRIBUTION over nothing
    is not: a diversity share of nought links is arithmetic, not a finding."""
    if profile.referring_domains <= 0 and profile.backlinks <= 0:
        return _na("this domain has no backlinks at all, so there is no distribution to "
                   "spread out, concentrate or classify")
    return None


def _total(dist: dict[str, int]) -> int:
    return sum(int(v or 0) for v in dist.values())


def _buckets(dist: dict[str, int], words: tuple[str, ...]) -> tuple[int, list[str]]:
    """Count and name every bucket whose key contains one of ``words``."""
    hits = {k: int(v or 0) for k, v in dist.items() if any(w in k.lower() for w in words)}
    return sum(hits.values()), sorted(hits)


def _absent_bucket_is_zero(dist: dict[str, int]) -> bool:
    """Can "not in this distribution" be read as "none of them"?

    Only when the response was not cut short. At the limit a smaller category
    can exist below the tenth bucket, and calling that zero would report an
    unmeasured thing as a measured absence.
    """
    return 0 < len(dist) < INTERNAL_LIST_LIMIT


# --------------------------------------------------------------------------
# Diversity: how many DIFFERENT places the links come from
# --------------------------------------------------------------------------

@check("OFF-028", scope="backlinks")
def check_referring_ip_diversity(profile: BacklinkProfile) -> Verdict:
    """OFF-028 - do the referring domains sit on separate machines?

    No backlinks at all is n_a here: a ratio over nothing measures nothing.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    domains, ips = profile.referring_domains, profile.referring_ips
    if domains <= 0 or ips <= 0:
        return _na("the provider resolved no IP addresses behind the referring domains, so "
                   "they cannot be told apart by host",
                   referring_domains=domains, referring_ips=ips)
    # Can exceed 1.0: one domain served from several IPs is ordinary CDN
    # behaviour and is not extra diversity, so it is clamped rather than scored.
    share = min(1.0, ips / domains)
    per_ip = domains / ips
    thin = domains < DIVERSITY_SAMPLE_FLOOR
    confidence = 0.4 if thin else 0.85
    ev = {"referring_domains": domains, "referring_ips": ips,
          "ip_diversity_share": round(share, 3), "domains_per_ip": round(per_ip, 2),
          "threshold_basis": "judgement; Google publishes no host-diversity figure"}
    if share >= IP_DIVERSITY_GOOD:
        return Verdict("pass", 10.0, "info", confidence, ev)
    if share >= IP_DIVERSITY_POOR or thin:
        return Verdict("warn", 6.0, "minor", confidence, ev,
                       f"{domains:,} referring domains resolve to {ips:,} IP addresses, about "
                       f"{per_ip:.1f} domains per host. Shared hosting explains a good deal of "
                       f"that and is not a defect on its own. Pull the domains that share a "
                       f"host and check whether they are unrelated sites or one operator's set. "
                       f"{_DISAVOW}")
    return Verdict("fail", 3.0, "major", confidence, ev,
                   f"{domains:,} referring domains resolve to only {ips:,} IP addresses, about "
                   f"{per_ip:.1f} domains per host. At that concentration most of the separate "
                   f"sites linking here are the same machine, which is how a private link "
                   f"network looks from outside. Identify the shared hosts first. {_DISAVOW}")


@check("OFF-029", scope="backlinks")
def check_referring_subnet_diversity(profile: BacklinkProfile) -> Verdict:
    """OFF-029 - do those IP addresses sit in separate network blocks?

    Tighter than OFF-028 by design: a shared IP can be shared hosting, but IPs
    clustered in one /24 usually mean one provider, one rack, one owner.
    No backlinks at all is n_a for the same reason as OFF-028.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    ips, subnets = profile.referring_ips, profile.referring_subnets
    if ips <= 0 or subnets <= 0:
        return _na("the provider reported no subnet breakdown for the referring IP addresses",
                   referring_ips=ips, referring_subnets=subnets)
    share = min(1.0, subnets / ips)
    per_subnet = ips / subnets
    thin = profile.referring_domains < DIVERSITY_SAMPLE_FLOOR
    confidence = 0.4 if thin else 0.85
    ev = {"referring_ips": ips, "referring_subnets": subnets,
          "subnet_diversity_share": round(share, 3), "ips_per_subnet": round(per_subnet, 2),
          "threshold_basis": "judgement; Google publishes no subnet-diversity figure"}
    if share >= SUBNET_DIVERSITY_GOOD:
        return Verdict("pass", 10.0, "info", confidence, ev)
    if share >= SUBNET_DIVERSITY_POOR or thin:
        return Verdict("warn", 6.0, "minor", confidence, ev,
                       f"{ips:,} referring IP addresses fall into {subnets:,} network blocks, "
                       f"about {per_subnet:.1f} addresses per block. One hosting company can "
                       f"produce that legitimately. Check which block the largest group sits in "
                       f"and who owns it. {_DISAVOW}")
    return Verdict("fail", 3.0, "major", confidence, ev,
                   f"{ips:,} referring IP addresses fall into only {subnets:,} network blocks, "
                   f"about {per_subnet:.1f} addresses per block. Links that all originate from "
                   f"one block are the clearest footprint a link network leaves, because the "
                   f"addresses were bought together. {_DISAVOW}")


@check("OFF-030", scope="backlinks")
def check_country_relevance(profile: BacklinkProfile) -> Verdict:
    """OFF-030 - do the links come from where the business trades?

    Scored against the country the provider reports for this domain, and only
    over links it could place: the blank bucket and WW name no country.
    No backlinks at all is n_a.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    home = str(profile.info.get("country") or "").strip().upper()
    countries = {str(k).strip().upper(): int(v or 0) for k, v in profile.countries.items()}
    if not home:
        return _na("the provider reported no country for this domain, so there is nothing to "
                   "judge the referring countries against")
    located = {k: v for k, v in countries.items() if k not in UNATTRIBUTED_COUNTRY_KEYS}
    total = sum(located.values())
    if total <= 0:
        return _na("the provider could not place any referring link in a country",
                   home_country=home, unattributed_links=_total(countries))
    home_links = located.get(home, 0)
    home_share = home_links / total
    foreign = {k: v for k, v in located.items() if k != home}
    top_foreign, top_foreign_links = (max(foreign.items(), key=lambda kv: kv[1])
                                      if foreign else ("", 0))
    top_foreign_share = top_foreign_links / total
    ev = {"home_country": home, "home_country_share": round(home_share, 3),
          "top_foreign_country": top_foreign or None,
          "top_foreign_country_share": round(top_foreign_share, 3),
          "located_links": total,
          "unattributed_links": _total(countries) - total,
          "threshold_basis": "judgement; a country mix is a relevance signal, not a rule"}
    largest_is_home = bool(home_links) and home_links >= top_foreign_links
    if largest_is_home or home_share >= HOME_COUNTRY_HEALTHY_SHARE:
        return Verdict("pass", 10.0, "info", 0.7, ev)
    if home_share < HOME_COUNTRY_THIN_SHARE and top_foreign_share >= FOREIGN_CONCENTRATION_SHARE:
        return Verdict("fail", 4.0, "major", 0.7, ev,
                       f"{home_links:,} of {total:,} placed referring links come from {home}, "
                       f"the country the provider reports for this domain, while {top_foreign} "
                       f"holds {top_foreign_links:,}. One unrelated country holding that much of "
                       f"a profile is more often a purchased network than earned coverage, "
                       f"though an export market or an offshore site build can produce it too. "
                       f"{_DISAVOW}")
    return Verdict("warn", 6.0, "minor", 0.7, ev,
                   f"Only {home_links:,} of {total:,} placed referring links come from {home}. "
                   f"If the business sells beyond {home} that is expected; if it does not, most "
                   f"of this profile carries no local relevance and the next links earned should "
                   f"be from {home} sites that its customers actually read.")


@check("OFF-031", scope="backlinks")
def check_tld_distribution(profile: BacklinkProfile) -> Verdict:
    """OFF-031 - the extensions the referring domains use.

    Reads the ten largest TLD buckets, so every share is a share of what the
    provider itemised rather than of the whole profile. No backlinks at all,
    or no TLD breakdown, is n_a.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    tld = {str(k).strip().lower(): int(v or 0) for k, v in profile.tld.items() if k}
    itemised = _total(tld)
    if itemised <= 0:
        return _na("the provider returned no TLD breakdown for the referring links")
    top_tld, top_links = max(tld.items(), key=lambda kv: kv[1])
    top_share = top_links / itemised
    # The final label is what identifies the registry: com.vn is a Vietnamese
    # domain, blogspot.com is a Blogger subdomain, and neither is a .com.
    abuse = {k: v for k, v in tld.items() if k.rsplit(".", 1)[-1] in HIGH_ABUSE_TLDS}
    abuse_share = sum(abuse.values()) / itemised
    ev = {"top_tld": top_tld, "top_tld_share": round(top_share, 3),
          "high_abuse_tld_share": round(abuse_share, 3),
          "tlds_itemised": len(tld), "links_itemised": itemised,
          "high_abuse_tlds": sorted(abuse)[:3],
          "note": "the ten largest TLD buckets only; shares are of the links itemised",
          "threshold_basis": "judgement; a TLD is not a ranking signal, a cluster is a pattern"}
    if abuse_share >= HIGH_ABUSE_TLD_SHARE:
        return Verdict("warn", 6.0, "minor", 0.7, ev,
                       f"{sum(abuse.values()):,} of {itemised:,} itemised referring links sit on "
                       f"{', '.join(sorted(abuse)[:5])}, extensions that rank at the top of "
                       f"published abuse tables. That is a reason to open the list, not a verdict "
                       f"on it: plenty of real sites use them. {_DISAVOW}")
    if top_tld not in GENERIC_TLDS and top_share >= SINGLE_TLD_CONCENTRATION:
        return Verdict("warn", 6.0, "minor", 0.7, ev,
                       f"{top_links:,} of {itemised:,} itemised referring links, {top_share:.0%}, "
                       f"come from .{top_tld} alone. One national or platform cluster that size "
                       f"is rarely how links arrive on their own, so check whether those domains "
                       f"are related to each other. {_DISAVOW}")
    return Verdict("pass", 10.0, "info", 0.7, ev)


# --------------------------------------------------------------------------
# Link types: what KIND of link each one is
# --------------------------------------------------------------------------

@check("OFF-055", scope="backlinks")
def check_press_release_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-055 - links from sites the provider classifies as news.

    The data cannot tell earned coverage from a syndicated paid release, so a
    heavy share is reported as something to check rather than as spam. Zero news
    links IS the finding for this check, not an n_a: a business with no press
    coverage has a gap worth naming. No backlinks at all is n_a.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    platforms = profile.platform_types
    tags = _total(platforms)
    if tags <= 0:
        return _na("the provider returned no platform breakdown for the referring links")
    news_links, names = _buckets(platforms, NEWS_WORDS)
    if not names and not _absent_bucket_is_zero(platforms):
        return _na("the provider itemised only its ten largest platform categories and news is "
                   "not among them, so any smaller news bucket sits below the cut")
    # The platform buckets overlap - one referring page can be tagged blogs AND
    # cms - so they sum past the link count. The only denominator this response
    # supports is the tag total, and the evidence says so rather than implying a
    # share of pages.
    share = news_links / tags
    ev = {"news_links": news_links, "news_tag_share": round(share, 3),
          "platform_tags_counted": tags,
          "threshold_basis": "judgement; Google's link spam policy names paid press-release "
                             "links but publishes no share"}
    if news_links <= 0:
        return Verdict("warn", 6.0, "minor", 0.65, ev,
                       f"None of the {tags:,} platform tags on this profile is news, so the site "
                       f"has no link from an outlet the provider recognises as one. One placement "
                       f"in a genuine publication is the kind of link this profile has none of.")
    if share >= NEWS_HEAVY_SHARE:
        return Verdict("warn", 6.0, "minor", 0.65, ev,
                       f"{news_links:,} of {tags:,} platform tags are news, {share:.0%} of the "
                       f"profile. A single release syndicated across dozens of outlets produces "
                       f"exactly this shape. Google's link spam policy treats links in a paid "
                       f"release that pass ranking credit as link spam, so any release you paid "
                       f"to distribute should carry rel=sponsored or rel=nofollow. {_DISAVOW}")
    return Verdict("pass", 10.0, "info", 0.65, ev)


@check("OFF-057", scope="backlinks")
def check_forum_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-057 - links from forums and message boards.

    Zero is a pass, not an n_a, whenever the platform list was short enough to
    prove the absence. No backlinks at all is n_a.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    platforms = profile.platform_types
    tags = _total(platforms)
    if tags <= 0:
        return _na("the provider returned no platform breakdown for the referring links")
    forum_links, names = _buckets(platforms, FORUM_WORDS)
    if not names and not _absent_bucket_is_zero(platforms):
        return _na("the provider itemised only its ten largest platform categories and no forum "
                   "category is among them, so a smaller one may sit below the cut")
    share = forum_links / tags
    ev = {"forum_links": forum_links, "forum_tag_share": round(share, 3),
          "platform_tags_counted": tags, "forum_categories": names[:3],
          "threshold_basis": "judgement; Google's link spam policy names optimised forum links "
                             "but publishes no share"}
    if forum_links <= 0:
        return Verdict("pass", 10.0, "info", 0.65, ev)
    if share >= FORUM_HEAVY_SHARE:
        return Verdict("warn", 6.0, "minor", 0.65, ev,
                       f"{forum_links:,} of {tags:,} platform tags are forum or message-board "
                       f"pages, {share:.0%} of the profile. Google's link spam policy names forum "
                       f"comments and signatures carrying optimised links, and most forum links "
                       f"are nofollow or ugc anyway, so they rarely earn what their volume "
                       f"suggests. Check whether they were placed by hand or at scale. {_DISAVOW}")
    return Verdict("pass", 9.0, "info", 0.65, ev)


@check("OFF-058", scope="backlinks")
def check_profile_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-058 - links from directory, social and forum PROFILE pages.

    Usually n_a, and honestly so: the provider's platform vocabulary has no
    profile category, so profile links are scattered inside the organization and
    unknown buckets and cannot be counted out of them. When a future response
    does carry such a category, this measures it.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    platforms = profile.platform_types
    tags = _total(platforms)
    if tags <= 0:
        return _na("the provider returned no platform breakdown for the referring links")
    profile_links, names = _buckets(platforms, PROFILE_WORDS)
    if not names:
        return _na("the provider's platform categories do not separate profile pages, so links "
                   "from directory and social profiles cannot be counted out of the wider "
                   "buckets they sit in",
                   platform_categories=sorted(platforms)[:3], platform_tags_counted=tags)
    share = profile_links / tags
    ev = {"profile_links": profile_links, "profile_tag_share": round(share, 3),
          "platform_tags_counted": tags, "profile_categories": names[:3],
          "threshold_basis": "judgement; profile links are low value, not a penalty"}
    if share >= FORUM_HEAVY_SHARE:
        return Verdict("warn", 6.0, "minor", 0.6, ev,
                       f"{profile_links:,} of {tags:,} platform tags are profile pages, "
                       f"{share:.0%} of the profile. Profile links are cheap to create in bulk "
                       f"and are usually nofollow, so a profile built mostly of them is not "
                       f"earning the authority its link count implies. {_DISAVOW}")
    return Verdict("pass", 10.0, "info", 0.6, ev)


@check("OFF-059", scope="backlinks")
def check_redirect_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-059 - links that reach this site through a redirect.

    A redirect passes credit, so these are real links; the risk is that they
    belong to someone else's domain and can be pointed elsewhere without notice.
    Zero is a pass. No backlinks at all is n_a.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    types = profile.link_types
    classified = _total(types)
    if classified <= 0:
        return _na("the provider returned no link-type breakdown for the referring links")
    redirect_links, names = _buckets(types, REDIRECT_WORDS)
    if not names and not _absent_bucket_is_zero(types):
        return _na("the provider itemised only its ten largest link types and no redirect type "
                   "is among them, so a smaller one may sit below the cut")
    share = redirect_links / classified
    ev = {"redirect_links": redirect_links, "redirect_share": round(share, 3),
          "links_classified": classified,
          "note": "the destination of each redirect is not fetched by this audit",
          "threshold_basis": "judgement; Google names expired-domain redirects as spam but "
                             "publishes no share"}
    if redirect_links <= 0:
        return Verdict("pass", 10.0, "info", 0.7, ev)
    if share >= REDIRECT_HEAVY_SHARE:
        return Verdict("warn", 6.0, "minor", 0.7, ev,
                       f"{redirect_links:,} of {classified:,} classified referring links reach "
                       f"this site through a redirect, {share:.0%} of them. Whoever owns those "
                       f"source domains can repoint them at any time, and buying expired domains "
                       f"to redirect them is named in Google's spam policies. Confirm the "
                       f"redirects are ones you or a partner control. {_DISAVOW}")
    return Verdict("pass", 9.0, "info", 0.7, ev)


@check("OFF-065", scope="backlinks")
def check_video_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-065 - links from video platforms and video pages.

    Normally n_a: neither the link-type nor the platform vocabulary has a video
    category, so a YouTube description link is indistinguishable here from any
    other page. Separating them needs the referring-domain list, which is a
    further billable request this audit does not make.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    types, platforms = profile.link_types, profile.platform_types
    video_links, names = _buckets(types, VIDEO_WORDS)
    platform_links, platform_names = _buckets(platforms, VIDEO_WORDS)
    video_links += platform_links
    names += platform_names
    if not names:
        return _na("neither the link types nor the platform categories the provider returns "
                   "isolate video pages, so video backlinks cannot be counted without buying "
                   "the full referring-domain list",
                   links_classified=_total(types), platform_tags_counted=_total(platforms))
    ev = {"video_links": video_links, "video_categories": names[:3],
          "links_classified": _total(types)}
    if video_links <= 0:
        return Verdict("pass", 9.0, "info", 0.6, ev)
    return Verdict("pass", 10.0, "info", 0.6, ev)


@check("OFF-066", scope="backlinks")
def check_image_backlinks(profile: BacklinkProfile) -> Verdict:
    """OFF-066 - links wrapped around an image rather than around text.

    An image link carries the image's alt text where a text link carries anchor
    text, so a profile made mostly of them is usually badges and widgets rather
    than editorial links. Zero is a pass. No backlinks at all is n_a.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    types = profile.link_types
    classified = _total(types)
    if classified <= 0:
        return _na("the provider returned no link-type breakdown for the referring links")
    image_links, names = _buckets(types, IMAGE_WORDS)
    if not names and not _absent_bucket_is_zero(types):
        return _na("the provider itemised only its ten largest link types and image is not "
                   "among them, so a smaller image bucket sits below the cut")
    share = image_links / classified
    ev = {"image_links": image_links, "image_share": round(share, 3),
          "links_classified": classified,
          "threshold_basis": "judgement; Google names widget links as spam but publishes no share"}
    if share >= IMAGE_HEAVY_SHARE:
        return Verdict("warn", 6.0, "minor", 0.7, ev,
                       f"{image_links:,} of {classified:,} classified referring links, "
                       f"{share:.0%}, are images rather than text. That is the shape a badge or "
                       f"an embeddable widget leaves, and Google's link spam policy names links "
                       f"distributed inside widgets. Check the alt text those images carry, "
                       f"since it is doing the job anchor text would. {_DISAVOW}")
    return Verdict("pass", 10.0, "info", 0.7, ev)


# --------------------------------------------------------------------------
# Reclaimable value
# --------------------------------------------------------------------------

@check("OFF-044", scope="backlinks")
def check_broken_backlink_opportunities(profile: BacklinkProfile) -> Verdict:
    """OFF-044 - links this site already earned that land on a dead page.

    Answers the half of this check the purchased data supports. The other half,
    finding a competitor's dead pages to pitch a replacement, needs a competitor
    profile that is not bought for this audit, and the evidence says so.
    No backlinks at all is n_a: there is nothing earned to reclaim.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    if (na := _no_links(profile)) is not None:
        return na
    broken_links, broken_pages = profile.broken_backlinks, profile.broken_pages
    total = profile.backlinks
    share = broken_links / total if total > 0 else 0.0
    ev = {"broken_backlinks": broken_links, "broken_pages_with_backlinks": broken_pages,
          "backlinks": total, "broken_backlink_share": round(share, 3),
          "note": "the competitor half of this check needs competitor backlink data, which is "
                  "not purchased for this audit",
          "threshold_basis": "judgement; every broken backlink is recoverable value"}
    if broken_links <= 0 and broken_pages <= 0:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    fix = (f"{broken_links:,} of {total:,} backlinks land on a page that does not resolve, "
           f"across {broken_pages:,} pages of this site that hold backlinks and return an error. "
           f"Redirect each of those URLs to the closest live page with a 301. The links are "
           f"already earned, so this is the cheapest link work in the audit.")
    if share >= BROKEN_BACKLINK_SERIOUS_SHARE:
        return Verdict("fail", 4.0, "major", 0.85, ev, fix)
    return Verdict("warn", 7.0, "minor", 0.85, ev, fix)


# --------------------------------------------------------------------------
# What was not bought. These stay registered, and say so in words a client can
# read, because a check quietly dropped from the run reads as a check that
# passed.
# --------------------------------------------------------------------------

@check("OFF-041", scope="backlinks")
def check_competitor_backlink_gap(profile: BacklinkProfile) -> Verdict:
    """OFF-041 - domains linking to competitors but not to this site.

    Always n_a. The provider is called once, for this domain, so there is no
    competitor profile to subtract from.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na("competitor backlink data is not purchased for this audit, so the domains that "
               "link to competitors and not to this site cannot be listed",
               own_referring_domains=profile.referring_domains, own_backlinks=profile.backlinks)


@check("OFF-042", scope="backlinks")
def check_competitor_authority(profile: BacklinkProfile) -> Verdict:
    """OFF-042 - this domain's authority against its competitors'.

    Always n_a. The site's own rank is measured, but a rank means nothing until
    the competing domains are measured the same way, by the same provider, on
    the same day, and those measurements are not purchased.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na("competitor authority scores are not purchased for this audit, so this domain's "
               "own rank has nothing to be compared against",
               own_rank=profile.rank, own_referring_domains=profile.referring_domains)


@check("OFF-043", scope="backlinks")
def check_competitor_referring_domains(profile: BacklinkProfile) -> Verdict:
    """OFF-043 - referring-domain counts against competitors'.

    Always n_a, for the same reason as OFF-041 and OFF-042.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na("competitor referring-domain counts are not purchased for this audit, so the gap "
               "between this profile and a competitor's cannot be stated",
               own_referring_domains=profile.referring_domains,
               own_referring_main_domains=profile.referring_main_domains)


@check("OFF-052", scope="backlinks")
def check_branded_search_volume(profile: BacklinkProfile) -> Verdict:
    """OFF-052 - how many people search for the brand by name.

    Always n_a. A backlink profile carries no search volume, and the anchor
    text that comes with it counts how others describe the site, not how many
    people look for it.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na("branded search volume is not purchased for this audit; the backlink profile "
               "carries no keyword or search-volume data to derive it from",
               anchors_available=len(profile.anchors))


@check("LOC-030", scope="backlinks")
def check_geo_targeted_keywords(profile: BacklinkProfile) -> Verdict:
    """LOC-030 - whether the pages target the city-and-service phrases.

    Always n_a from here. This check receives the backlink profile, which holds
    no keyword, volume or local-ranking data, and none of that is purchased for
    this audit.
    """
    if (na := _unavailable(profile)) is not None:
        return na
    return _na("geo-targeted keyword data is not purchased for this audit, so the phrases these "
               "pages target cannot be checked against what local customers search for",
               reported_country=str(profile.info.get("country") or "") or None)
