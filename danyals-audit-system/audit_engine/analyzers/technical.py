"""Technical SEO analyzers used by /audit (Team B coverage).

Deterministic core for ~25 technical checks. Higher-judgement checks delegate
to the Team B agents via the orchestrator.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.crawlers.basic import CrawledPage
from audit_engine.parsers.robots import RobotsTxt
from audit_engine.parsers.sitemap import Sitemap


SECURITY_HEADERS_RECOMMENDED = {
    "strict-transport-security": "HSTS - protects against downgrade attacks",
    "content-security-policy": "CSP - mitigates XSS / data injection",
    "x-content-type-options": "Prevents MIME-sniffing attacks",
    "x-frame-options": "Clickjacking protection (legacy; CSP frame-ancestors preferred)",
    "referrer-policy": "Controls Referer header leakage",
    "permissions-policy": "Controls browser feature access",
}


def check_robots_validation(robots: RobotsTxt | None) -> Verdict:
    """TECH-001 Robots.txt validation."""
    if robots is None or robots.status_code == 0:
        return Verdict("fail", 0.0, "major", 1.0, {"reason": "robots.txt fetch failed"},
                       "Publish a /robots.txt with at least a User-agent: * and Sitemap: directive.")
    if robots.status_code == 404:
        return Verdict("warn", 5.0, "major", 1.0, {"status": 404},
                       "robots.txt returns 404. Add one with sitemap reference and any disallow rules.")
    if robots.error:
        return Verdict("warn", 5.0, "major", 1.0, {"error": robots.error}, robots.error)
    issues: list[str] = []
    if not robots.sitemaps:
        issues.append("no Sitemap: directive present")
    if robots.suspicious_directives:
        issues.append(f"suspicious directives detected: {len(robots.suspicious_directives)}")
    if not issues:
        return Verdict("pass", 10.0, "info", 1.0,
                       {"groups": len(robots.groups), "sitemaps": len(robots.sitemaps)})
    score = 6.0 if "no Sitemap:" in issues[0] else 4.0
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major",
        confidence=1.0,
        evidence={"issues": issues, "suspicious": robots.suspicious_directives[:3]},
        remediation="Resolve listed issues. Add 'Sitemap: <full url>' if missing.",
    )


def check_sitemap_validation(sitemaps: list[Sitemap]) -> Verdict:
    """TECH-002 + TECH-003 + TECH-004 Sitemap validity rollup."""
    if not sitemaps:
        return Verdict("fail", 0.0, "critical", 1.0, {"sitemaps_found": 0},
                       "No XML sitemap discovered. Publish /sitemap.xml and reference it from robots.txt.")
    errors = [{"url": s.url, "error": s.error} for s in sitemaps if s.error]
    total_urls = sum(len(s.urls) for s in sitemaps)
    if errors:
        return Verdict(
            "warn", 6.0, "major", 1.0,
            {"sitemaps_found": len(sitemaps), "url_count": total_urls, "errors": errors[:5]},
            "Some sitemaps returned errors. Fix XML validity and HTTP status.",
        )
    return Verdict(
        "pass", 10.0, "info", 1.0,
        {"sitemaps_found": len(sitemaps), "url_count": total_urls},
    )


def check_broken_pages(pages: list[CrawledPage]) -> Verdict:
    """TECH-011 / TECH-012 / TECH-014 Broken page + 4xx + 5xx rollup."""
    fours = [p for p in pages if p.http_status and 400 <= p.http_status < 500 and p.http_status != 404]
    fofs = [p for p in pages if p.http_status == 404]
    fives = [p for p in pages if p.http_status and p.http_status >= 500]
    total_bad = len(fours) + len(fofs) + len(fives)
    if total_bad == 0:
        return Verdict("pass", 10.0, "info", 1.0, {"pages_checked": len(pages), "broken": 0})
    score = max(0.0, 10.0 - total_bad)
    severity = "critical" if fives else "major"
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity=severity,
        confidence=1.0,
        evidence={
            "4xx_non_404": len(fours),
            "404": len(fofs),
            "5xx": len(fives),
            "examples_5xx": [p.url for p in fives[:5]],
            "examples_404": [p.url for p in fofs[:5]],
        },
        remediation=f"{total_bad} pages return non-2xx. Fix or remove from sitemap and internal links.",
    )


def check_redirect_chains(pages: list[CrawledPage]) -> Verdict:
    """TECH-015 Redirect chain detection."""
    chains = [p for p in pages if len(p.redirect_chain) >= 2]
    if not chains:
        return Verdict("pass", 10.0, "info", 1.0, {"redirect_chains": 0})
    score = max(0.0, 10.0 - len(chains))
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major",
        confidence=1.0,
        evidence={
            "chains_count": len(chains),
            "examples": [
                {"url": p.url, "chain_length": len(p.redirect_chain), "chain": p.redirect_chain}
                for p in chains[:5]
            ],
        },
        remediation=f"{len(chains)} URLs redirect through 2+ hops; collapse to a single 301.",
    )


def check_https_redirect(pages: list[CrawledPage]) -> Verdict:
    """TECH-058 HTTP to HTTPS redirect validation.

    Tested on homepage only for /audit-quick; full audit can scan more.
    """
    if not pages:
        return Verdict("n_a", 0.0, "info", 1.0, {})
    home = pages[0]
    is_https = home.final_url.startswith("https://")
    if not is_https:
        return Verdict("fail", 0.0, "critical", 1.0,
                       {"final_url": home.final_url},
                       "Site does not redirect HTTP to HTTPS. Enforce HTTPS via 301.")
    return Verdict("pass", 10.0, "info", 1.0, {"final_url": home.final_url})


def check_security_headers(pages: list[CrawledPage]) -> Verdict:
    """TECH-085 Security header analysis.

    Note: our CrawledPage stores headers indirectly via http_status only; deep
    header capture is a Phase 1B enhancement. For now we emit n_a if no header
    data is available, so the agent can pick up.
    """
    return Verdict(
        "n_a", 0.0, "info", 0.4,
        {"reason": "header capture not implemented in basic crawler; defer to Team B5"},
    )


def check_hreflang_reciprocity(pages: list[CrawledPage]) -> Verdict:
    """TECH-061 Hreflang reciprocity (site-wide)."""
    hreflang_map: dict[str, dict[str, str]] = {}
    for p in pages:
        if not p.parsed or not p.parsed.hreflang:
            continue
        hreflang_map[p.url] = {e.lang: e.href for e in p.parsed.hreflang}

    if not hreflang_map:
        return Verdict("n_a", 0.0, "info", 1.0, {"pages_with_hreflang": 0})

    missing: list[dict] = []
    for src_url, langs in hreflang_map.items():
        for lang, target_url in langs.items():
            if lang == "x-default" or target_url == src_url:
                continue
            target_langs = hreflang_map.get(target_url)
            if target_langs is None:
                missing.append({"from": src_url, "to": target_url, "issue": "target has no hreflang"})
                continue
            # The target must have a back-reference to some pair under the original site.
            if src_url not in target_langs.values():
                missing.append({"from": src_url, "to": target_url, "issue": "no reciprocal hreflang"})

    if not missing:
        return Verdict("pass", 10.0, "info", 1.0, {"pages_with_hreflang": len(hreflang_map)})
    score = max(0.0, 10.0 - len(missing))
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major",
        confidence=0.9,
        evidence={"missing_count": len(missing), "examples": missing[:5]},
        remediation="Hreflang must be reciprocal: each target page must reference back to its peers.",
    )


def check_duplicate_metadata(pages: list[CrawledPage]) -> Verdict:
    """TECH-077 Duplicate metadata analysis (description-level)."""
    descs = [(p.url, p.parsed.meta_description.strip()) for p in pages if p.parsed and p.parsed.meta_description]
    if len(descs) <= 1:
        return Verdict("n_a", 0.0, "info", 1.0, {"pages_with_description": len(descs)})
    seen: dict[str, list[str]] = {}
    for url, d in descs:
        seen.setdefault(d, []).append(url)
    dupes = {d: urls for d, urls in seen.items() if len(urls) > 1}
    if not dupes:
        return Verdict("pass", 10.0, "info", 1.0, {"pages_with_description": len(descs), "duplicate_descriptions": 0})
    score = max(0.0, 10.0 - len(dupes) * 2.0)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major" if len(dupes) >= 3 else "minor",
        confidence=1.0,
        evidence={
            "duplicate_descriptions": len(dupes),
            "examples": [{"description": d[:80], "urls": urls[:5]} for d, urls in list(dupes.items())[:3]],
        },
        remediation=f"{len(dupes)} description(s) reused across pages; make each unique to the page intent.",
    )


def check_canonical_chain(pages: list[CrawledPage]) -> Verdict:
    """TECH-020 + TECH-021 Canonical chain + conflict detection."""
    canon_map = {
        p.url: p.parsed.canonical
        for p in pages
        if p.parsed and p.parsed.canonical
    }
    conflicts: list[dict] = []
    for url, canon in canon_map.items():
        target_canon = canon_map.get(canon)
        if target_canon and target_canon != canon:
            conflicts.append({"page": url, "canonical": canon, "canonical_of_canonical": target_canon})
    if not conflicts:
        return Verdict("pass", 10.0, "info", 1.0, {"checked": len(canon_map)})
    score = max(0.0, 10.0 - len(conflicts) * 2.0)
    return Verdict(
        status=status_from_score(score),
        score=score,
        severity="major",
        confidence=1.0,
        evidence={"conflicts_count": len(conflicts), "examples": conflicts[:3]},
        remediation="Canonical chains weaken signal. Each page's canonical must point to a self-canonical target.",
    )


def iter_site_wide_technical(
    *, sitemaps: list[Sitemap], robots: RobotsTxt | None, pages: list[CrawledPage]
) -> Iterable[tuple[str, str, str, Verdict]]:
    """Yield (check_id, category, owner_agent, verdict) for site-wide technical
    checks."""
    yield ("TECH-001", "technical", "B1", check_robots_validation(robots))
    yield ("TECH-002", "technical", "B1", check_sitemap_validation(sitemaps))
    yield ("TECH-011", "technical", "B1", check_broken_pages(pages))
    yield ("TECH-015", "technical", "B1", check_redirect_chains(pages))
    yield ("TECH-020", "technical", "B1", check_canonical_chain(pages))
    yield ("TECH-058", "technical", "B5", check_https_redirect(pages))
    yield ("TECH-061", "technical", "B5", check_hreflang_reciprocity(pages))
    yield ("TECH-077", "technical", "B1", check_duplicate_metadata(pages))
    yield ("TECH-085", "technical", "B5", check_security_headers(pages))
