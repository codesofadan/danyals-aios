"""Free consolidated narrative report.

Composes a single unified Markdown audit report from the deterministic
findings, written in the Khurram Malik report structure:
    Executive Summary -> Scorecard -> Content / Indexing / Linking /
    Local / AI Search sections, each with Analysis / Recommendations /
    Guidelines.

Pure Python, zero API spend. Same input as the Claude narrative reporter,
so the two are drop-in interchangeable based on the runtime mode the user
selects (free / ai).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from audit_engine.config import get_branding

SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "info": 3}


CATEGORY_BUCKETS: dict[str, dict[str, Any]] = {
    "content": {
        "title": "CONTENT OVERVIEW",
        "subtitle": "On-page content, titles, meta, headings, and images.",
        "check_prefixes": ("ON-",),
        "subcategories": (
            "titles",
            "meta-description",
            "headings",
            "content-quality",
            "keywords",
            "images",
            "url-structure",
        ),
        "color_band": "Blue",
    },
    "indexing": {
        "title": "INDEXING & TECHNICAL OVERVIEW",
        "subtitle": "Crawlability, indexability, redirects, speed, and security.",
        "check_prefixes": ("TECH-",),
        "subcategories": (
            "robots-sitemap",
            "indexability",
            "redirects",
            "canonical",
            "errors",
            "performance",
            "security",
            "mobile",
            "international",
            "duplication",
        ),
        "color_band": "Green",
    },
    "linking": {
        "title": "LINKING & AUTHORITY OVERVIEW",
        "subtitle": "Backlinks, anchor distribution, and internal link structure.",
        "check_prefixes": ("OFF-", "ON-061", "ON-063"),
        "subcategories": (
            "authority",
            "backlinks",
            "anchors",
            "toxicity",
            "internal-links",
        ),
        "color_band": "Yellow",
    },
    "local": {
        "title": "LOCAL SEO & GBP OVERVIEW",
        "subtitle": "Google Business Profile, NAP consistency, citations, and reviews.",
        "check_prefixes": ("LOC-",),
        "subcategories": ("gbp", "nap", "citations", "reviews", "schema"),
        "color_band": "Purple",
    },
    "ai_search": {
        "title": "AI SEARCH READINESS",
        "subtitle": "llms.txt, AI-bot crawlability, structured data for AI Overviews.",
        "check_prefixes": ("ON-073", "ON-079"),
        "subcategories": ("schema", "geo-ai"),
        "color_band": "Cyan",
    },
}


def _bucket_for(check_id: str) -> str | None:
    for bucket, cfg in CATEGORY_BUCKETS.items():
        if any(check_id.startswith(p) for p in cfg["check_prefixes"]):
            return bucket
    return None


def _color_band(score: float | None) -> str:
    if score is None:
        return "N/A"
    if score >= 80:
        return "Green (Minor Issues If Any)"
    if score >= 50:
        return "Yellow (Some Issues)"
    return "Red (Major Issues)"


def _evidence_inline(ev_json: str | None, *, max_kv: int = 3, max_len: int = 140) -> str:
    if not ev_json:
        return ""
    try:
        ev = json.loads(ev_json)
    except json.JSONDecodeError:
        return ev_json[:max_len]
    if not isinstance(ev, dict):
        return str(ev)[:max_len]
    parts = []
    for k, v in list(ev.items())[:max_kv]:
        if isinstance(v, (list, dict)):
            v = json.dumps(v, default=str)[:60]
        parts.append(f"{k}={v}")
    out = ", ".join(parts)
    return out if len(out) <= max_len else out[: max_len - 3] + "..."


def _sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda f: (
            SEVERITY_RANK.get(f.get("severity", "info"), 99),
            f.get("score") if f.get("score") is not None else 0,
        ),
    )


def _top_critical(findings: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    failing = [f for f in findings if f.get("status") in ("fail", "warn")]
    return _sort_findings(failing)[:n]


def _top_passing(findings: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    passing = [f for f in findings if f.get("status") == "pass" and (f.get("score") or 0) >= 8]
    return sorted(passing, key=lambda f: -(f.get("score") or 0))[:n]


def _quick_wins(findings: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    """Highest-impact, lowest-effort. Heuristic: major severity, has remediation,
    not a site-wide rewrite (i.e. not 'thin content' type checks)."""
    candidates = [
        f
        for f in findings
        if f.get("status") in ("fail", "warn")
        and f.get("remediation")
        and f.get("severity") in ("critical", "major")
        and f.get("check_id") not in ("ON-023",)  # thin content takes time
    ]
    return _sort_findings(candidates)[:n]


def _phase_buckets(findings: list[dict[str, Any]]) -> tuple[list, list, list]:
    """Split actionable findings into 30/60/90-day phases by severity."""
    actionable = [f for f in findings if f.get("status") in ("fail", "warn")]
    crit = [f for f in actionable if f.get("severity") == "critical"]
    maj = [f for f in actionable if f.get("severity") == "major"]
    min_ = [f for f in actionable if f.get("severity") == "minor"]
    return crit + maj[:4], maj[4:], min_


GUIDELINES: dict[str, str] = {
    "titles": (
        "Title tags should be 30-60 characters with the primary keyword near the start. "
        "Every page needs a unique title that describes the specific page topic, not the brand alone. "
        "Pixel width matters more than character count - aim under 580 px to avoid truncation in SERPs."
    ),
    "meta-description": (
        "Meta descriptions should be 140-160 characters, unique per page, and contain a clear value proposition "
        "or call to action. Missing or duplicate meta descriptions cost click-through rate, even when rankings hold."
    ),
    "headings": (
        "Each page needs exactly one H1 that mirrors the page topic and ideally appears as a question or "
        "entity-led phrase. H2/H3 should follow nested order without skipping levels - it is a structural "
        "signal for both search engines and AI Overviews."
    ),
    "content-quality": (
        "Aim for at least 300 words of unique, helpful content per indexable page. Below 200 words the page "
        "risks being classified as thin under Google's Helpful Content guidance, suppressing rankings sitewide."
    ),
    "keywords": (
        "Each page should target one primary keyword or entity. Title clashes between pages cause "
        "cannibalization - the engine has to pick which page to rank, and both lose authority."
    ),
    "images": (
        "Every meaningful image needs descriptive alt text containing the page entity (no keyword stuffing). "
        "File names should be human-readable (sofa-set-lahore.jpg, not IMG_2034.jpg). Use WebP or AVIF for "
        "weights above 200 KB."
    ),
    "url-structure": (
        "URLs should be lowercase, hyphen-separated, under 100 characters, and reflect the page topic. Avoid "
        "underscores and query parameters in canonical URLs."
    ),
    "robots-sitemap": (
        "robots.txt should allow indexing of all canonical URLs and block utility paths only. The XML sitemap "
        "must list every indexable URL with a current lastmod timestamp and be referenced from robots.txt."
    ),
    "indexability": (
        "Every page Google should rank must be: 200 OK, free of noindex, canonical-to-self (or to a stronger "
        "equivalent), and not disallowed in robots.txt. Mix-ups between these are the most common cause of "
        "phantom traffic loss."
    ),
    "redirects": (
        "Use 301 redirects (permanent) for moved URLs. 302 (temporary) does not pass link equity and should "
        "only be used for time-limited promotions. Avoid redirect chains - point each old URL directly at the "
        "final destination."
    ),
    "canonical": (
        "Canonical tags resolve duplicate-content ambiguity. Every page should either self-canonicalize or "
        "point cleanly at the master URL of the duplicate group. Conflicting canonicals are a frequent cause "
        "of indexation issues."
    ),
    "performance": (
        "Core Web Vitals are a confirmed ranking signal. Target LCP under 2.5 s, CLS under 0.1, INP under "
        "200 ms. Lazy-load below-the-fold images, defer non-critical JS, and ship modern image formats."
    ),
    "security": (
        "HTTPS is table stakes. Add HSTS, set a Content-Security-Policy header, and ensure no mixed-content "
        "warnings. Modern browsers and Search Console both penalize HTTP."
    ),
    "mobile": (
        "Mobile-first indexing means Google ranks based on the mobile rendering. Viewport meta tag, readable "
        "font sizes (>=16 px), tap targets >=48 px, no horizontal scroll."
    ),
    "international": (
        "Hreflang annotations must be reciprocal, use valid language-region codes, and include a self-reference. "
        "Errors silently break international rankings without throwing visible warnings."
    ),
    "duplication": (
        "Duplicate titles, meta, or boilerplate content fragment indexation strength. Consolidate near-duplicate "
        "pages with 301 redirects, or differentiate them with unique value-add content."
    ),
    "authority": (
        "Domain Authority is a relative metric. Focus on referring-domain diversity (different TLDs, niches, "
        "geographies) over raw backlink count. One link from a topical authority beats 100 from low-quality blogs."
    ),
    "backlinks": (
        "Audit referring domains quarterly. Disavow obviously spammy or unrelated link sources. Track lost "
        "backlinks - some are recoverable with a quick outreach."
    ),
    "anchors": (
        "Anchor text distribution should be majority branded or naked-URL, with exact-match anchors below 5 % "
        "of total. Over-optimized anchor profiles are a frequent trigger for manual actions."
    ),
    "toxicity": (
        "Toxic backlinks from spam directories, link farms, or PBNs accumulate quietly. A spam-score-weighted "
        "audit catches them before they suppress legitimate authority."
    ),
    "internal-links": (
        "Every important page should have internal links from at least three other pages. Orphan pages cannot "
        "rank. Use entity-rich anchor text instead of 'click here'. Keep click depth under 4 from the homepage."
    ),
    "gbp": (
        "Google Business Profile completeness drives map-pack visibility. Primary category, address, phone, "
        "website, hours, photos (>=10), service list, and weekly posts all contribute."
    ),
    "nap": (
        "Name / Address / Phone must match exactly across the website, GBP, and every citation. Even spacing "
        "or abbreviation differences (Street vs St) fragment local entity strength."
    ),
    "citations": (
        "Top-tier directories (Yelp, BBB, industry-specific) carry more weight than dozens of low-quality "
        "citations. Verify the listing is claimed, NAP-consistent, and links to the correct site."
    ),
    "reviews": (
        "Review velocity (new reviews per month) and recency matter as much as average rating. A 4.6 with 200 "
        "recent reviews outperforms a 4.9 with 12 reviews from 2 years ago."
    ),
    "schema": (
        "Schema.org markup turns content into structured facts AI search engines and SERP features can lift. "
        "LocalBusiness, Organization, Article, FAQ, HowTo, and Product are the highest-value types for most sites."
    ),
    "geo-ai": (
        "AI-bot crawlability (GPTBot, ClaudeBot, PerplexityBot, Google-Extended) determines whether ChatGPT, "
        "Claude, Perplexity, and AI Overviews can cite your content. llms.txt at /llms.txt provides a guide to "
        "AI crawlers, analogous to sitemap.xml for traditional search."
    ),
}


def _subcategory_for(check_id: str, check_name: str) -> str:
    name = (check_name or "").lower()
    cid = check_id.upper()
    if any(k in name for k in ("title",)) or cid in ("ON-034", "ON-036"):
        return "titles"
    if "meta description" in name or cid in ("ON-038",):
        return "meta-description"
    if "h1" in name or "heading" in name or cid in ("ON-041", "ON-042", "ON-043"):
        return "headings"
    if "thin content" in name or "content quality" in name or cid in ("ON-023",):
        return "content-quality"
    if "keyword" in name or cid in ("ON-013",):
        return "keywords"
    if "alt" in name or "image" in name or cid in ("ON-067",):
        return "images"
    if "url" in name and "redirect" not in name and "canonical" not in name:
        return "url-structure"
    if "robots" in name or "sitemap" in name or cid in ("TECH-001", "TECH-002"):
        return "robots-sitemap"
    if "indexability" in name or "noindex" in name or cid in ("ON-080",):
        return "indexability"
    if "redirect" in name:
        return "redirects"
    if "canonical" in name:
        return "canonical"
    if "speed" in name or "lcp" in name or "cls" in name or "performance" in name or cid in ("TECH-010",):
        return "performance"
    if "https" in name or "security" in name or "ssl" in name:
        return "security"
    if "viewport" in name or "mobile" in name:
        return "mobile"
    if "hreflang" in name or "international" in name:
        return "international"
    if "duplicate" in name:
        return "duplication"
    if "authority" in name or "domain authority" in name or "da" in cid:
        return "authority"
    if "backlink" in name or "referring" in name:
        return "backlinks"
    if "anchor" in name:
        return "anchors"
    if "spam" in name or "toxic" in name:
        return "toxicity"
    if "internal" in name or "orphan" in name or "broken" in name:
        return "internal-links"
    if "gbp" in name or "business profile" in name:
        return "gbp"
    if "nap" in name:
        return "nap"
    if "citation" in name:
        return "citations"
    if "review" in name:
        return "reviews"
    if "schema" in name or "localbusiness" in name:
        return "schema"
    if "llms" in name or "gptbot" in name or "ai bot" in name or "ai search" in name:
        return "geo-ai"
    return "other"


def _section_for_finding(f: dict[str, Any]) -> tuple[str, str]:
    """Return (bucket_key, subcategory)."""
    cid = f.get("check_id", "")
    bucket = _bucket_for(cid) or "content"
    sub = _subcategory_for(cid, f.get("check_name", ""))
    return bucket, sub


def render_consolidated(
    *,
    domain: str,
    run_uuid: str,
    profile: str,
    started_at: str,
    duration_sec: float,
    pages_crawled: int,
    scores: dict[str, float | None],
    findings: list[dict[str, Any]],
    brand_name: str | None = None,
) -> str:
    """Compose the full unified Markdown report."""
    if not brand_name:
        brand_name = get_branding().brand_name

    severity_counts = Counter(f.get("severity", "info") for f in findings)
    failing = [f for f in findings if f.get("status") in ("fail", "warn")]
    overall = scores.get("overall")

    # Bucket findings
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORY_BUCKETS}
    for f in findings:
        bucket, _ = _section_for_finding(f)
        buckets.setdefault(bucket, []).append(f)

    lines: list[str] = []
    add = lines.append

    # ---- Cover ----
    add(f"# SEO Audit | {domain}")
    add("")
    add(f"**Prepared by** {brand_name}  ")
    add(f"**Run ID** `{run_uuid}`  ")
    add(f"**Started** {started_at}  ")
    add(f"**Pages crawled** {pages_crawled}  ")
    add(f"**Audit duration** {duration_sec:.1f}s  ")
    add("")
    add("---")
    add("")

    # ---- Executive Summary ----
    add("## Executive Summary")
    add("")
    overall_label = (
        f"an overall SEO-ability score of **{overall:.1f}/100** ({_color_band(overall)})"
        if overall is not None
        else "an incomplete overall score (some data sources unavailable)"
    )
    add(
        f"`{domain}` has scored {overall_label}. "
        f"The audit evaluated **{len(findings)} checks** across on-page, technical, off-page, and local SEO "
        f"dimensions, surfacing **{severity_counts.get('critical', 0)} critical**, "
        f"**{severity_counts.get('major', 0)} major**, **{severity_counts.get('minor', 0)} minor**, "
        f"and **{severity_counts.get('info', 0)} informational** findings."
    )
    add("")

    quick_wins = _quick_wins(findings)
    if quick_wins:
        add("### Top Action Items (start here)")
        for f in quick_wins:
            cid = f.get("check_id", "")
            name = f.get("check_name", "")
            sev = f.get("severity", "info").upper()
            rem = (f.get("remediation") or "").strip()
            add(f"- **[{sev}] `{cid}` {name}** - {rem}")
        add("")

    critical = _top_critical(findings, n=5)
    if critical:
        add("### Top Critical Findings")
        for f in critical:
            cid = f.get("check_id", "")
            name = f.get("check_name", "")
            ev = _evidence_inline(f.get("evidence_json"))
            add(f"- `{cid}` {name} - {ev}")
        add("")

    # ---- Scorecard ----
    add("## Scorecard")
    add("")
    add("A score of 100 is perfect execution; a score of 1 means the element is missing entirely.")
    add("Color band: **Red** (1-49) major issues, **Yellow** (50-79) some issues, **Green** (80-100) minor issues if any.")
    add("")
    add("| Dimension | Score | Band |")
    add("|---|---:|---|")
    for label, key in (
        ("Overall", "overall"),
        ("On-Page (Content)", "on_page"),
        ("Indexing & Technical", "technical"),
        ("Off-Page (Linking)", "off_page"),
        ("Local SEO & GBP", "local"),
    ):
        s = scores.get(key)
        s_str = f"{s:.1f}" if isinstance(s, (int, float)) else "-"
        add(f"| {label} | {s_str} | {_color_band(s if isinstance(s, (int, float)) else None)} |")
    add("")

    # ---- Per-bucket sections ----
    for bucket_key, cfg in CATEGORY_BUCKETS.items():
        items = buckets.get(bucket_key, [])
        if not items:
            continue

        add(f"## {cfg['title']}")
        add(f"_{cfg['subtitle']}_")
        add("")

        # Bucket score - average of per-finding 0-10 scores, rescaled to 0-100
        if items:
            avg = sum(f.get("score") or 0 for f in items) / max(len(items), 1)
            bucket_score = avg * 10.0
            add(f"**Section Score:** {bucket_score:.1f}/100 ({_color_band(bucket_score)})")
            add("")

        # Group by subcategory
        by_sub: dict[str, list[dict[str, Any]]] = {}
        for f in items:
            _, sub = _section_for_finding(f)
            by_sub.setdefault(sub, []).append(f)

        # Render subcategories in spec order, then "other"
        ordered_subs = [s for s in cfg["subcategories"] if s in by_sub] + [
            s for s in by_sub if s not in cfg["subcategories"]
        ]
        for sub in ordered_subs:
            sub_items = by_sub[sub]
            sub_label = sub.replace("-", " ").title()
            add(f"### {sub_label}")
            add("")

            failing_sub = [f for f in sub_items if f.get("status") in ("fail", "warn")]
            passing_sub = [f for f in sub_items if f.get("status") == "pass"]

            # Analysis
            add("**Analysis.** ", )
            if failing_sub:
                worst = _sort_findings(failing_sub)[:5]
                bullets = []
                for f in worst:
                    cid = f.get("check_id", "")
                    name = f.get("check_name", "")
                    ev = _evidence_inline(f.get("evidence_json"))
                    sev = f.get("severity", "info").upper()
                    bullets.append(f"  - [{sev}] `{cid}` {name}: {ev}")
                add("")
                add(f"The audit flagged {len(failing_sub)} issue(s) in this area "
                    f"({sum(1 for f in failing_sub if f.get('severity')=='critical')} critical, "
                    f"{sum(1 for f in failing_sub if f.get('severity')=='major')} major, "
                    f"{sum(1 for f in failing_sub if f.get('severity')=='minor')} minor).")
                add("")
                for b in bullets:
                    add(b)
            else:
                add("")
                add(f"All {len(sub_items)} checks in this area passed. {len(passing_sub)} pages or signals "
                    "evaluated cleanly.")
            add("")

            # Recommendations
            add("**Recommendations.**")
            recs = []
            for f in _sort_findings(failing_sub)[:6]:
                cid = f.get("check_id", "")
                rem = (f.get("remediation") or "").strip()
                if rem:
                    recs.append(f"- `{cid}`: {rem}")
            if recs:
                add("")
                for r in recs:
                    add(r)
            else:
                add("")
                add("- No issues require action in this area. Maintain current practice and re-audit next cycle.")
            add("")

            # Guidelines
            guideline = GUIDELINES.get(sub)
            if guideline:
                add("**Guidelines.**")
                add("")
                add(guideline)
                add("")

    # ---- Strengths ----
    strengths = _top_passing(findings, n=6)
    if strengths:
        add("## Strengths")
        add("")
        add("These areas already perform well and serve as a foundation to build on.")
        add("")
        for f in strengths:
            cid = f.get("check_id", "")
            name = f.get("check_name", "")
            score = f.get("score")
            score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "-"
            add(f"- `{cid}` {name} - score {score_str}/10")
        add("")

    # ---- 30-60-90 Plan ----
    phase_30, phase_60, phase_90 = _phase_buckets(findings)
    add("## 30 / 60 / 90 Day Action Plan")
    add("")

    def _phase_block(title: str, items: list[dict[str, Any]], cap: int = 6) -> None:
        add(f"### {title}")
        if not items:
            add("")
            add("_No action items in this phase._")
            add("")
            return
        add("")
        for f in items[:cap]:
            cid = f.get("check_id", "")
            name = f.get("check_name", "")
            sev = f.get("severity", "info").upper()
            rem = (f.get("remediation") or "").strip()
            line = f"- **[{sev}] `{cid}` {name}**"
            if rem:
                line += f" - {rem}"
            add(line)
        add("")

    _phase_block("Days 0-30 (Critical + High-Impact Fixes)", phase_30)
    _phase_block("Days 30-60 (Major Issues)", phase_60)
    _phase_block("Days 60-90 (Minor Optimizations + Strategic Work)", phase_90)

    # ---- Methodology ----
    add("## Methodology")
    add("")
    add(f"This audit evaluated `{domain}` across **{len(findings)} checks** drawn from a {profile}-profile "
        "checklist. Deterministic Python analyzers ran for crawl, parsing, schema, and rate-limited integration "
        "calls. Findings carry severity, score, evidence, and remediation in machine-readable form for the "
        "accompanying `findings.json` and SQLite history.")
    add("")
    add("- **Audit started:** " + started_at)
    add("- **Wall-clock duration:** " + f"{duration_sec:.1f}s")
    add("- **Pages crawled:** " + str(pages_crawled))
    add("- **Profile:** " + profile)
    add("- **Run UUID:** `" + run_uuid + "`")
    add("")

    add("---")
    add("")
    add(f"_Prepared by {brand_name}. Findings are auditable - each `check_id` resolves to the underlying "
        "evidence in `findings.json` and the SQLite database. For per-finding deep dives run "
        "`seo-audit fix <check-id> --run " + run_uuid + "`._")
    add("")

    return "\n".join(lines)
