"""Off-page analyzers used by /audit (Team C coverage).

Deterministic checks compute anchor distribution, naked-URL/branded ratios,
DA/spam summaries from Moz data. Higher-judgement checks (toxic link review,
unlinked mentions, PBN footprint reasoning) belong to Team C agents.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable
from urllib.parse import urlparse

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.integrations.moz import BacklinkProfile, DomainAuthority


def _is_naked_url(anchor: str) -> bool:
    a = (anchor or "").lower().strip()
    if not a:
        return False
    return bool(re.fullmatch(r"https?://\S+|[a-z0-9.-]+\.[a-z]{2,}(/\S*)?", a))


def _is_generic(anchor: str) -> bool:
    return (anchor or "").lower().strip() in {
        "click here", "here", "read more", "more", "this", "this page",
        "this article", "this post", "link", "website", "site", "homepage", "home",
    }


def check_domain_authority(da: DomainAuthority) -> Verdict:
    """OFF-001 Domain authority analysis (informational)."""
    if da.error:
        return Verdict(
            "n_a", 0.0, "info", 0.4,
            {"reason": da.error, "target": da.target},
            "Configure MOZ_ACCESS_ID + MOZ_SECRET_KEY in .env to enable backlink/DA analysis.",
        )
    if da.domain_authority is None:
        return Verdict("n_a", 0.0, "info", 0.5, {"target": da.target, "reason": "no data"})
    # Informational: no fail just because DA is low. Surface the number.
    return Verdict(
        "pass", 10.0, "info", 1.0,
        {
            "domain_authority": da.domain_authority,
            "spam_score": da.spam_score,
            "linking_root_domains": da.linking_root_domains,
        },
    )


def check_referring_domains(profile: BacklinkProfile) -> Verdict:
    """OFF-005 Referring domains analysis (informational + low-volume warning)."""
    if profile.error:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": profile.error})
    rd = profile.referring_domains
    if rd is None:
        return Verdict("n_a", 0.0, "info", 0.5, {"reason": "no data"})
    if rd < 10:
        return Verdict(
            "warn", 4.0, "major", 1.0,
            {"referring_domains": rd},
            f"Only {rd} referring domain(s). Low link diversity; target reputable industry links.",
        )
    return Verdict("pass", 10.0, "info", 1.0, {"referring_domains": rd})


def check_anchor_distribution(profile: BacklinkProfile, *, domain: str) -> tuple[Verdict, Verdict, Verdict, Verdict]:
    """OFF-017 Anchor distribution + OFF-018 over-optimized + OFF-019 branded ratio + OFF-021 naked URL ratio.

    Returns four verdicts. Empty data -> all n_a.
    """
    if profile.error or not profile.anchor_distribution:
        na = Verdict("n_a", 0.0, "info", 0.4, {"reason": profile.error or "no anchor data"})
        return (na, na, na, na)

    total = sum(profile.anchor_distribution.values())
    brand_token = (
        urlparse(domain).netloc.split(".")[0]
        if "://" in domain
        else domain.split(".")[0]
    ).lower()

    branded = 0
    naked = 0
    exact_count: Counter[str] = Counter()
    generic = 0

    for anchor, count in profile.anchor_distribution.items():
        a = (anchor or "").lower().strip()
        if not a:
            continue
        if brand_token in a:
            branded += count
        if _is_naked_url(a):
            naked += count
        if _is_generic(a):
            generic += count
        exact_count[a] += count

    most_common_anchor, most_common_count = (
        exact_count.most_common(1)[0] if exact_count else ("", 0)
    )

    branded_ratio = branded / total if total else 0
    naked_ratio = naked / total if total else 0
    most_common_ratio = most_common_count / total if total else 0

    # OFF-017 Distribution rollup
    dist_evidence = {
        "total_anchors": total,
        "branded_ratio": round(branded_ratio, 2),
        "naked_ratio": round(naked_ratio, 2),
        "generic": generic,
        "most_common_anchor": most_common_anchor,
        "most_common_count": most_common_count,
    }
    if branded_ratio < 0.3:
        dist_verdict = Verdict(
            "warn", 6.0, "major", 0.8, dist_evidence,
            f"Branded anchor ratio {branded_ratio:.0%}; healthy local profiles are 40-70% branded.",
        )
    else:
        dist_verdict = Verdict("pass", 10.0, "info", 0.9, dist_evidence)

    # OFF-018 Over-optimized (any single non-branded anchor > 20% of profile)
    if most_common_count and not (brand_token in most_common_anchor) and most_common_ratio > 0.2:
        over = Verdict(
            "fail", 3.0, "critical", 0.9,
            {"anchor": most_common_anchor, "share": round(most_common_ratio, 2), "count": most_common_count},
            f"Anchor '{most_common_anchor}' is {most_common_ratio:.0%} of all anchors. Risk of unnatural-link penalty.",
        )
    else:
        over = Verdict("pass", 10.0, "info", 0.9, {"most_common_share": round(most_common_ratio, 2)})

    # OFF-019 Branded anchor ratio
    if branded_ratio >= 0.4:
        branded_v = Verdict("pass", 10.0, "info", 0.9, {"branded_ratio": round(branded_ratio, 2)})
    elif branded_ratio >= 0.3:
        branded_v = Verdict("warn", 7.0, "minor", 0.9, {"branded_ratio": round(branded_ratio, 2)})
    else:
        branded_v = Verdict(
            "warn", 5.0, "major", 0.9,
            {"branded_ratio": round(branded_ratio, 2)},
            "Branded anchor share is low. Build editorial links that use the brand name as anchor.",
        )

    # OFF-021 Naked URL ratio (informational; both extremes flag)
    if 0.05 <= naked_ratio <= 0.25:
        naked_v = Verdict("pass", 10.0, "info", 0.9, {"naked_ratio": round(naked_ratio, 2)})
    else:
        naked_v = Verdict(
            "warn", 7.0, "minor", 0.8,
            {"naked_ratio": round(naked_ratio, 2)},
            f"Naked URL anchor share is {naked_ratio:.0%}; healthy range is roughly 5-25%.",
        )

    return (dist_verdict, over, branded_v, naked_v)


def check_spam_score(da: DomainAuthority) -> Verdict:
    """OFF-039 Spam score analysis."""
    if da.error or da.spam_score is None:
        return Verdict("n_a", 0.0, "info", 0.4, {"reason": da.error or "no data"})
    score = da.spam_score
    if score >= 31:
        return Verdict(
            "fail", 1.0, "critical", 1.0, {"spam_score": score},
            f"Spam score {score}/100 is high. Audit incoming links and consider a disavow file.",
        )
    if score >= 11:
        return Verdict(
            "warn", 5.0, "major", 1.0, {"spam_score": score},
            f"Spam score {score}/100 is moderate. Review toxic links and outreach quality.",
        )
    return Verdict("pass", 10.0, "info", 1.0, {"spam_score": score})


def iter_off_page_findings(
    *, da: DomainAuthority, profile: BacklinkProfile, domain: str
) -> Iterable[tuple[str, str, str, Verdict]]:
    yield ("OFF-001", "off-page", "C1", check_domain_authority(da))
    yield ("OFF-005", "off-page", "C1", check_referring_domains(profile))
    yield ("OFF-039", "off-page", "C2", check_spam_score(da))
    dist, over, branded, naked = check_anchor_distribution(profile, domain=domain)
    yield ("OFF-017", "off-page", "C2", dist)
    yield ("OFF-018", "off-page", "C2", over)
    yield ("OFF-019", "off-page", "C2", branded)
    yield ("OFF-021", "off-page", "C2", naked)
