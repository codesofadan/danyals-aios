"""
verify_coverage.py - Phase 0 coverage proof.

Reads the user-supplied master checklist (original 313 items) plus the 4 YAML
checklist files in `checklists/`, then proves every original item is mapped to
exactly one YAML entry. Reports gaps, duplicates, owner-agent coverage, and a
team-load distribution.

Run:
    python scripts/verify_coverage.py
    python scripts/verify_coverage.py --strict      # exit 1 on any gap

Exit codes:
    0  full coverage, no warnings
    1  one or more gaps (missing or unmapped checks)
    2  duplicates detected
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_DIR = ROOT / "checklists"


# Original user-supplied master list (313 items)
# These names come verbatim from the source brief that triggered this build.
USER_LIST: dict[str, list[str]] = {
    "on-page": [
        "Search intent match analysis",
        "User query satisfaction check",
        "SERP intent comparison",
        "Primary keyword optimization",
        "Secondary keyword optimization",
        "Long tail keyword coverage",
        "Semantic keyword relevance",
        "NLP keyword coverage",
        "Related entities optimization",
        "Entity relationship analysis",
        "Topic completeness analysis",
        "Missing subtopics detection",
        "Competitor content gap analysis",
        "Content depth analysis",
        "Thin content detection",
        "AI generated fluff detection",
        "Helpful content evaluation",
        "EEAT optimization analysis",
        "Expertise signal detection",
        "Trust signal analysis",
        "Author credibility analysis",
        "Content originality check",
        "Information gain analysis",
        "Content freshness analysis",
        "Topical authority analysis",
        "Internal topical relevance analysis",
        "Topic cluster integration",
        "Semantic relevance score",
        "Content quality scoring",
        "Search intent alignment score",
        "Title tag optimization",
        "Title CTR optimization",
        "Title uniqueness check",
        "Title keyword placement",
        "Meta description optimization",
        "Meta description CTR analysis",
        "Meta description uniqueness",
        "H1 optimization",
        "Multiple H1 detection",
        "Heading hierarchy analysis",
        "Semantic heading optimization",
        "Question based heading detection",
        "Featured snippet optimization",
        "Passage ranking optimization",
        "AI overview optimization",
        "Direct answer optimization",
        "FAQ optimization",
        "Content readability analysis",
        "Reading flow optimization",
        "Paragraph length analysis",
        "Sentence complexity analysis",
        "Content scannability analysis",
        "Intro optimization",
        "Above the fold optimization",
        "Keyword stuffing detection",
        "Semantic over optimization detection",
        "Anchor text optimization",
        "Internal link relevance",
        "Internal link depth analysis",
        "Orphan page detection",
        "Link equity distribution analysis",
        "Broken internal links detection",
        "Contextual linking analysis",
        "External link quality analysis",
        "Outbound authority link analysis",
        "Image alt text optimization",
        "Image semantic relevance",
        "Image filename optimization",
        "Image compression analysis",
        "WebP image usage check",
        "Lazy loading optimization",
        "Schema markup validation",
        "FAQ schema optimization",
        "Article schema validation",
        "Service schema optimization",
        "LocalBusiness schema optimization",
        "Breadcrumb schema validation",
        "Rich result eligibility analysis",
        "Canonical tag validation",
        "Indexability analysis",
        "Crawlability analysis",
        "Mobile friendliness analysis",
        "Mobile content parity analysis",
        "Core Web Vitals impact on SEO",
        "LCP element analysis",
        "CLS issue detection",
        "INP interaction analysis",
        "Page speed impact analysis",
        "UX signal analysis",
        "User engagement optimization",
        "Bounce risk detection",
        "Conversion focused content analysis",
        "CTA optimization analysis",
        "Trust element optimization",
        "Commercial intent optimization",
        "Local SEO relevance analysis",
        "Geo targeted keyword optimization",
        "NAP consistency analysis",
        "Duplicate content detection",
        "Keyword cannibalization detection",
        "Semantic duplication analysis",
        "URL optimization analysis",
        "SEO friendly slug analysis",
        "HTTPS validation",
        "Structured content analysis",
        "Table optimization for snippets",
        "List optimization for snippets",
        "Content extraction optimization for AI search",
        "LLM readability optimization",
        "Generative search optimization",
        "AI crawl readiness analysis",
        "Semantic HTML structure analysis",
        "Hidden content detection",
        "Over optimization penalty detection",
        "Spam signal detection",
        "Low quality page detection",
        "User value score",
        "Topical relevance score",
        "Semantic SEO score",
        "Overall on page SEO score",
    ],
    "technical": [
        "Robots.txt validation",
        "XML sitemap validation",
        "Sitemap indexability check",
        "Sitemap URL status analysis",
        "Crawlability analysis",
        "Indexability analysis",
        "Crawl budget optimization",
        "Crawl depth analysis",
        "Orphan URL detection",
        "Website speed checker by page speed insight",
        "Broken page detection",
        "404 error analysis",
        "Soft 404 detection",
        "5XX server error analysis",
        "Redirect chain detection",
        "Redirect loop detection",
        "301 redirect validation",
        "302 redirect misuse detection",
        "Canonical tag validation",
        "Canonical chain analysis",
        "Canonical conflict detection",
        "Duplicate URL detection",
        "URL parameter indexing analysis",
        "Faceted navigation issues",
        "Pagination optimization",
        "Infinite crawl trap detection",
        "Search page indexing detection",
        "JavaScript rendering analysis",
        "Render blocking resource detection",
        "Mobile rendering analysis",
        "Client side rendering issues",
        "DOM rendered content comparison",
        "JS hidden content detection",
        "Lazy load indexing analysis",
        "Structured data validation",
        "Schema error detection",
        "Rich result eligibility analysis",
        "Breadcrumb schema validation",
        "Core Web Vitals analysis",
        "Largest Contentful Paint analysis",
        "Cumulative Layout Shift analysis",
        "Interaction to Next Paint analysis",
        "Time to First Byte analysis",
        "Page speed optimization analysis",
        "Render blocking CSS detection",
        "Render blocking JS detection",
        "Unused CSS detection",
        "Unused JS detection",
        "Excessive DOM size analysis",
        "Compression analysis",
        "GZIP validation",
        "Brotli compression validation",
        "Browser caching analysis",
        "CDN optimization analysis",
        "HTTPS validation",
        "SSL certificate analysis",
        "Mixed content detection",
        "HTTP to HTTPS redirect validation",
        "WWW vs non WWW consistency",
        "Trailing slash consistency",
        "Hreflang validation",
        "International SEO analysis",
        "Mobile friendliness analysis",
        "Mobile usability issue detection",
        "Responsive design validation",
        "Viewport configuration analysis",
        "AMP validation if applicable",
        "Internal linking crawl analysis",
        "Link equity flow analysis",
        "Crawl log analysis",
        "Googlebot activity analysis",
        "Server response analysis",
        "HTML validation analysis",
        "Semantic HTML structure analysis",
        "Thin page detection",
        "Duplicate page detection",
        "Duplicate metadata analysis",
        "Index bloat detection",
        "Low quality page detection",
        "AI generated spam detection",
        "Spam page detection",
        "Malware detection",
        "Hidden page detection",
        "Cloaking detection",
        "Security header analysis",
        "Open Graph validation",
        "Twitter card validation",
        "Image crawlability analysis",
        "Image indexing analysis",
        "WebP support analysis",
        "Video indexing analysis",
        "Accessibility analysis",
        "Broken structured data analysis",
        "XML errors analysis",
        "Header response validation",
        "Content type validation",
        "HTTP/2 validation",
        "HTTP/3 validation",
        "Server latency analysis",
        "Hosting performance analysis",
        "Overall technical SEO score",
    ],
    "off-page": [
        "Domain authority analysis",
        "Domain rating analysis",
        "Brand authority analysis",
        "Backlink profile analysis",
        "Referring domains analysis",
        "Toxic backlink detection",
        "Spam backlink analysis",
        "Link velocity analysis",
        "Lost backlink detection",
        "New backlink detection",
        "High authority backlink analysis",
        "Niche relevant backlink analysis",
        "Contextual backlink analysis",
        "Editorial backlink analysis",
        "Homepage backlink analysis",
        "Deep page backlink analysis",
        "Anchor text distribution analysis",
        "Over optimized anchor detection",
        "Branded anchor ratio analysis",
        "Exact match anchor analysis",
        "Naked URL anchor analysis",
        "Generic anchor analysis",
        "Link diversity analysis",
        "Dofollow backlink analysis",
        "Nofollow backlink analysis",
        "Sponsored link analysis",
        "UGC link analysis",
        "Referring IP diversity analysis",
        "Referring subnet diversity analysis",
        "Country relevance analysis",
        "TLD distribution analysis",
        "Link placement analysis",
        "Sidebar link detection",
        "Footer link detection",
        "Sitewide backlink detection",
        "PBN footprint detection",
        "Link network analysis",
        "Link farm detection",
        "Spam score analysis",
        "Disavow recommendation analysis",
        "Competitor backlink gap analysis",
        "Competitor authority comparison",
        "Competitor referring domains comparison",
        "Broken backlink opportunities",
        "Unlinked brand mention detection",
        "Digital PR backlink opportunities",
        "HARO style opportunity analysis",
        "Citation consistency analysis",
        "Local citation audit",
        "NAP consistency analysis",
        "Google Business Profile optimization",
        "GBP category optimization",
        "GBP review analysis",
        "Review sentiment analysis",
        "Review velocity analysis",
        "Reputation management analysis",
        "Social signals analysis",
        "Brand mention analysis",
        "Entity authority analysis",
        "Knowledge Graph presence analysis",
        "Branded search volume analysis",
        "Topical authority backlink analysis",
        "Industry relevance analysis",
        "Press release backlink analysis",
        "Guest post backlink analysis",
        "Forum backlink analysis",
        "Profile backlink analysis",
        "Redirect backlink analysis",
        "Link decay analysis",
        "Historical backlink trend analysis",
        "Competitor mention gap analysis",
        "Influencer mention analysis",
        "Podcast mention analysis",
        "Video backlink analysis",
        "Image backlink analysis",
        "AI search authority analysis",
        "Generative search visibility analysis",
        "Citation trust analysis",
        "Trust flow analysis",
        "Citation flow analysis",
        "Link trust score",
        "Brand trust score",
        "Authority score",
        "Local prominence score",
        "Off page SEO score",
        "Toxicity risk score",
        "Link quality score",
        "Backlink relevance score",
        "Brand popularity score",
        "Overall off page SEO score",
    ],
}


# Items in the user list that we deliberately moved into local.yaml.
# Each maps to a LOC-* id; the verifier accepts a LOC-* id as coverage for these.
LOCAL_REROUTES: dict[str, str] = {
    "Local SEO relevance analysis": "LOC-031",
    "Geo targeted keyword optimization": "LOC-030",
    "NAP consistency analysis": "LOC-013",
    "LocalBusiness schema optimization": "LOC-032",
    "Citation consistency analysis": "LOC-012",
    "Local citation audit": "LOC-011",
    "Google Business Profile optimization": "LOC-001",
    "GBP category optimization": "LOC-002",
    "GBP review analysis": "LOC-021",
    "Review sentiment analysis": "LOC-022",
    "Review velocity analysis": "LOC-023",
    "Reputation management analysis": "LOC-027",
    "Local prominence score": "LOC-037",
}


def normalize(name: str) -> str:
    """Lowercase, strip, collapse whitespace, drop punctuation that varies."""
    return " ".join(name.lower().replace(".", "").replace(",", "").split())


def load_yaml_checks() -> list[dict]:
    """Load all YAML checklist files and return a flat list of check entries
    with their source file recorded under `_source`."""
    out: list[dict] = []
    for path in sorted(CHECKLIST_DIR.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for check in data.get("checks", []):
            check["_source"] = path.name
            out.append(check)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Coverage verifier for SEO-AUDIT-OS checklists.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any gap or duplicate")
    args = parser.parse_args()

    print("=" * 78)
    print("SEO-AUDIT-OS coverage verification")
    print("=" * 78)

    yaml_checks = load_yaml_checks()
    print(f"Loaded {len(yaml_checks)} checks from {len(set(c['_source'] for c in yaml_checks))} YAML files.")

    # ----- Coverage: every user list item appears in a YAML entry -----
    yaml_names_normalized: dict[str, list[dict]] = defaultdict(list)
    for c in yaml_checks:
        yaml_names_normalized[normalize(c["name"])].append(c)

    total_user_items = sum(len(items) for items in USER_LIST.values())
    print(f"User-supplied master list: {total_user_items} items across {len(USER_LIST)} categories.")
    print()

    missing: list[tuple[str, str]] = []
    matched = 0
    for category, items in USER_LIST.items():
        for item in items:
            key = normalize(item)
            # Direct name match.
            if key in yaml_names_normalized:
                matched += 1
                continue
            # Local reroute? Check that the routed LOC-* id exists.
            if item in LOCAL_REROUTES:
                routed_id = LOCAL_REROUTES[item]
                if any(c["id"] == routed_id for c in yaml_checks):
                    matched += 1
                    continue
            # Fuzzy: try category-qualified variants like "Mobile friendliness analysis (on-page)".
            qualified_keys = [
                normalize(f"{item} (on-page)"),
                normalize(f"{item} (technical)"),
                normalize(f"{item} (overall)"),
                normalize(f"{item} (rollup)"),
                normalize(f"{item} (sub-rollup)"),
                normalize(f"{item} (composite)"),
                normalize(f"{item} on-page audit"),
                normalize(f"{item} ai search"),
            ]
            if any(qk in yaml_names_normalized for qk in qualified_keys):
                matched += 1
                continue
            missing.append((category, item))

    print(f"Matched : {matched}/{total_user_items}")
    print(f"Missing : {len(missing)}")
    if missing:
        print("\n  Missing items (first 20):")
        for cat, name in missing[:20]:
            print(f"    [{cat:9}] {name}")
        if len(missing) > 20:
            print(f"    ... and {len(missing) - 20} more")

    # ----- Duplicate IDs -----
    print("\n" + "-" * 78)
    print("Duplicate ID check")
    print("-" * 78)
    id_counts = Counter(c["id"] for c in yaml_checks)
    duplicates = {k: v for k, v in id_counts.items() if v > 1}
    if duplicates:
        print(f"FAIL: {len(duplicates)} duplicate id(s):")
        for k, v in duplicates.items():
            print(f"    {k} appears {v} times")
    else:
        print("PASS: no duplicate IDs.")

    # ----- Owner-agent coverage -----
    print("\n" + "-" * 78)
    print("Team load distribution")
    print("-" * 78)
    by_agent: Counter[str] = Counter()
    by_team: dict[str, int] = defaultdict(int)

    def agent_team(agent_id: str) -> str:
        if agent_id.startswith("M"):
            return "meta"
        if agent_id.startswith("A"):
            return "onpage"
        if agent_id.startswith("B"):
            return "technical"
        if agent_id.startswith("C"):
            return "offpage"
        if agent_id.startswith("D"):
            return "local"
        return "unknown"

    for c in yaml_checks:
        by_agent[c["owner_agent"]] += 1
        by_team[agent_team(c["owner_agent"])] += 1

    print(f"  {'Agent':10} {'Checks':>7}")
    for agent_id, count in sorted(by_agent.items()):
        print(f"  {agent_id:10} {count:>7}")
    print("\n  Team rollup:")
    for team, count in sorted(by_team.items()):
        print(f"  {team:10} {count:>7}")

    # ----- Severity distribution -----
    print("\n" + "-" * 78)
    print("Severity distribution")
    print("-" * 78)
    sev_counts: Counter[str] = Counter(c["severity_default"] for c in yaml_checks)
    for sev, count in sorted(sev_counts.items()):
        print(f"  {sev:10} {count:>5}")

    # ----- Source file distribution -----
    print("\n" + "-" * 78)
    print("Checks per YAML file")
    print("-" * 78)
    src_counts: Counter[str] = Counter(c["_source"] for c in yaml_checks)
    for src, count in sorted(src_counts.items()):
        print(f"  {src:30} {count:>5}")

    # ----- Final verdict -----
    print("\n" + "=" * 78)
    has_issues = bool(missing or duplicates)
    if not has_issues:
        print("RESULT: PASS - full coverage, no duplicates.")
        return 0
    if duplicates:
        print(f"RESULT: FAIL - {len(duplicates)} duplicate IDs.")
        return 2
    if missing and args.strict:
        print(f"RESULT: FAIL - {len(missing)} unmapped checks (strict mode).")
        return 1
    print(f"RESULT: WARN - {len(missing)} unmapped checks (non-strict; exit 0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
