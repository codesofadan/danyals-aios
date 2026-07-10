"""Module 3 - Semantic SEO + Topical Authority + Koray Framework analyzers.

Deterministic, no LLM, no paid API. Covers submodules 3.1 - 3.9 of the
Advanced Audit Tool Features spec:

  3.1 Central Entity & Knowledge Domain Audit
  3.2 Entity Audit (Entity-Based SEO Core)
  3.3 Topical Map & Topical Authority Audit (site-wide)
  3.4 Contextual Structure Audit
  3.5 Query Semantics & Search Intent Audit
  3.6 Lexical Semantics Audit
  3.7 N-Gram Audit (per-page + site-wide overlap)
  3.8 Semantic Content Writing Rules (Koray Framework)
  3.9 Information Quality Audit

Check-ID mapping (one per analyzer function, see checklists/on-page.yaml):

  ON-119  Central entity coherence            check_central_entity_coherence
  ON-120  Knowledge domain consistency        check_knowledge_domain_consistency  (site-wide)
  ON-121  Entity coverage breadth             check_entity_coverage
  ON-122  sameAs / external entity link       check_sameas_presence
  ON-123  Organization schema completeness    check_organization_schema_completeness
  ON-124  Topical clusters                    check_topical_clusters              (site-wide)
  ON-125  Cluster depth                       check_cluster_depth                 (site-wide)
  ON-126  Hub and spoke link integrity        check_hub_spoke_links               (site-wide)
  ON-127  Topical breadth completeness        check_topical_breadth               (site-wide)
  ON-128  Heading-paragraph proximity         check_heading_paragraph_proximity
  ON-129  Section coherence                   check_section_coherence
  ON-130  Search intent classification        check_intent_classification
  ON-131  Intent-content alignment            check_intent_alignment
  ON-132  Lexical diversity (TTR)             check_lexical_diversity
  ON-133  Synonym / variation density         check_synonym_variation_density
  ON-134  N-gram stuffing detection           check_ngram_distribution
  ON-135  Cross-page n-gram overlap           check_cross_page_ngram_overlap      (site-wide)
  ON-136  Macro context connection (Koray)    check_macro_context_connection
  ON-137  Definitional content presence       check_definitional_content
  ON-138  Authoritative source citations      check_authoritative_citations
  ON-139  Question-answer pair coverage       check_qa_pair_coverage
  ON-140  Information density                 check_information_density
  ON-141  Date freshness                      check_date_freshness
  ON-142  Author expertise signals rollup     check_author_expertise_signals
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable
from urllib.parse import urlparse

from audit_engine.analyzers.common import Verdict, status_from_score
from audit_engine.parsers.html import ParsedHTML


# ---------- Shared helpers ---------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+){0,3}\b")
_SENT_RE = re.compile(r"[.!?]+\s")
_WORD_RE = re.compile(r"[A-Za-z]+")
_QUESTION_LEADERS = re.compile(
    r"^\s*(what|why|how|when|where|who|which|can|does|do|is|are|should|will|would|may|could)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with",
    "by", "at", "is", "are", "be", "this", "that", "these", "those", "as",
    "from", "it", "its", "we", "you", "your", "our", "their", "they", "but",
    "not", "if", "than", "then", "so", "do", "does", "did", "will", "have",
    "has", "had", "can", "would", "could", "should", "may", "might", "all",
    "any", "more", "most", "some", "such", "no", "nor", "only", "own", "same",
    "too", "very", "s", "t", "just", "don", "now", "into", "out", "up", "down",
    "off", "over", "under", "again", "further", "once", "here", "there", "when",
    "where", "why", "how", "what",
}

# Authoritative TLDs for source-citation scoring (3.8 Koray)
_AUTH_TLDS = (".gov", ".edu", ".int", ".mil", ".ac.uk", ".gov.uk", ".nhs.uk")
_AUTH_DOMAINS = {
    "wikipedia.org", "wikidata.org", "schema.org", "google.com",
    "developers.google.com", "developer.mozilla.org", "w3.org",
    "ietf.org", "iso.org", "iana.org", "nist.gov",
}

# Intent classification dictionaries (3.5 Query Semantics)
_INTENT_SIGNALS = {
    "transactional": (
        "buy", "order", "shop", "cart", "checkout", "subscribe", "book", "schedule",
        "request a quote", "get a quote", "free quote", "hire", "contact us",
        "call now", "purchase", "rent", "lease", "discount", "deal", "sale",
        "%", "price", "cost", "fee", "rate", "starting at", "from $", "/mo",
    ),
    "commercial": (
        "best", "top", "review", "vs", "versus", "compare", "comparison",
        "alternative", "alternatives", "pros and cons", "pricing",
        "near me", "in {city}",
    ),
    "informational": (
        "what is", "what are", "how to", "how do", "why", "when", "where",
        "guide", "tutorial", "definition", "meaning", "explained", "checklist",
        "examples", "ultimate guide",
    ),
    "navigational": (
        "login", "log in", "sign in", "dashboard", "account", "homepage",
        "official site", "{brand} website",
    ),
}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


def _proper_nouns(text: str) -> list[str]:
    return [m.group(0) for m in _PROPER_NOUN_RE.finditer(text or "")]


def _schema_types(p: ParsedHTML) -> list[str]:
    out: list[str] = []
    for b in p.schema_blocks or []:
        if not isinstance(b, dict):
            continue
        t = b.get("@type")
        if isinstance(t, list):
            out.extend(str(x) for x in t)
        elif t:
            out.append(str(t))
    return out


def _schema_block_of_type(p: ParsedHTML, name: str) -> dict | None:
    for b in p.schema_blocks or []:
        if not isinstance(b, dict):
            continue
        t = b.get("@type")
        if isinstance(t, list) and any(name.lower() == str(x).lower() for x in t):
            return b
        if isinstance(t, str) and t.lower() == name.lower():
            return b
    return None


# ============================================================================
# 3.1 Central Entity & Knowledge Domain
# ============================================================================

def check_central_entity_coherence(p: ParsedHTML) -> Verdict:
    """ON-119 - One central entity should be obvious from the page's
    title, H1, and Organization schema name. Mismatches confuse both
    Google and AI tools about what entity this page represents.
    """
    if not p.title or not p.h1s:
        return Verdict(
            "fail", 2.0, "major", 0.9,
            {"reason": "missing title or h1"},
            "Page lacks either a <title> or a single <h1>. Both must declare the same central entity.",
        )
    title_tokens = set(_tokens(p.title))
    h1_tokens = set(_tokens(p.h1s[0]))
    overlap = (len(title_tokens & h1_tokens) / len(title_tokens | h1_tokens)) if (title_tokens or h1_tokens) else 0.0
    org_block = _schema_block_of_type(p, "Organization") or _schema_block_of_type(p, "LocalBusiness")
    org_name = (org_block or {}).get("name") if isinstance(org_block, dict) else None
    schema_aligned = False
    if isinstance(org_name, str):
        org_tokens = set(_tokens(org_name))
        schema_aligned = bool(org_tokens and (org_tokens & title_tokens))
    score = 0.0
    score += overlap * 7.0
    score += 3.0 if schema_aligned else (1.0 if org_block else 0.0)
    score = round(min(10.0, score), 1)
    ev = {
        "title_h1_overlap": round(overlap, 2),
        "organization_schema_present": org_block is not None,
        "schema_name_aligned": schema_aligned,
        "title": p.title[:120],
        "h1": p.h1s[0][:120],
        "schema_org_name": org_name,
    }
    if score >= 8:
        return Verdict("pass", score, "info", 0.85, ev)
    rem = (
        "Align title, H1, and Organization schema 'name' around one central entity. "
        "All three should mention the same brand / topic in the first 60 characters."
    )
    return Verdict(
        status_from_score(score), score,
        "major" if score < 5 else "minor", 0.85,
        ev, rem,
    )


def check_knowledge_domain_consistency(pages: list[ParsedHTML]) -> Verdict:
    """ON-120 (site-wide) - Across the corpus, the same top-3 tokens should
    appear on most pages. If pages have wildly divergent vocabulary, the
    knowledge domain is fragmented.
    """
    bodies = [p.body_text for p in pages if p.body_text and len(p.body_text) > 200]
    if len(bodies) < 3:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "not enough content pages"})
    corpus_tokens = Counter()
    for b in bodies:
        # Count each token once per page (presence not raw frequency)
        for tok in set(_tokens(b)):
            corpus_tokens[tok] += 1
    top_three = [t for t, _ in corpus_tokens.most_common(3)]
    if not top_three:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no shared tokens"})
    coverage = []
    for tok in top_three:
        coverage.append({"token": tok, "pages_with_token": corpus_tokens[tok], "share": round(corpus_tokens[tok] / len(bodies), 2)})
    avg_share = sum(c["share"] for c in coverage) / len(coverage)
    score = round(min(10.0, avg_share * 12.0), 1)
    ev = {"pages": len(bodies), "top_three_tokens": coverage, "avg_share": round(avg_share, 2)}
    if score >= 7:
        return Verdict("pass", score, "info", 0.8, ev)
    rem = (
        "The top-3 domain tokens appear on under 60% of pages. Strengthen knowledge-domain "
        "consistency by ensuring every page references the central brand + domain terms at least once."
    )
    return Verdict(
        status_from_score(score), score,
        "major" if score < 5 else "minor", 0.8,
        ev, rem,
    )


# ============================================================================
# 3.2 Entity Audit
# ============================================================================

def check_entity_coverage(p: ParsedHTML) -> Verdict:
    """ON-121 - Count distinct proper nouns. Authoritative pages name many
    real-world entities (people, places, products, certifications).
    """
    text = (p.body_text or "")[:30000]
    if not text or len(text) < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too thin"})
    pn = _proper_nouns(text)
    distinct = sorted(set(pn))
    word_count = max(p.word_count or 0, 1)
    density = len(distinct) / (word_count / 100.0)
    score = min(10.0, density * 2.5)
    ev = {
        "distinct_proper_nouns": len(distinct),
        "examples": distinct[:12],
        "density_per_100_words": round(density, 2),
    }
    if score >= 7:
        return Verdict("pass", round(score, 1), "info", 0.7, ev)
    rem = (
        f"Only {len(distinct)} distinct named entities for {word_count} words "
        f"({density:.1f}/100w). Name real places, people, brands, certifications, and standards "
        "so Google can map the page into the knowledge graph."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "minor" if score >= 4 else "major", 0.7,
        ev, rem,
    )


def check_sameas_presence(p: ParsedHTML) -> Verdict:
    """ON-122 - The page's Organization (or Person) schema should include
    `sameAs` pointing to Wikidata + at least 2 verified social profiles.
    This is the strongest entity-disambiguation signal Google has.
    """
    org = _schema_block_of_type(p, "Organization") or _schema_block_of_type(p, "LocalBusiness")
    person = _schema_block_of_type(p, "Person")
    sources: list[dict] = []
    for block in (org, person):
        if block is None:
            continue
        sa = block.get("sameAs")
        if isinstance(sa, list):
            sources.extend({"value": str(x)} for x in sa)
        elif isinstance(sa, str):
            sources.append({"value": sa})
    if not (org or person):
        return Verdict(
            "warn", 4.0, "major", 0.9,
            {"organization_schema": False, "person_schema": False, "sameAs_count": 0},
            "No Organization or Person schema. Add Organization JSON-LD with sameAs pointing to Wikidata + 2-3 social profiles.",
        )
    n = len(sources)
    has_wikidata = any("wikidata.org" in s["value"].lower() for s in sources)
    score = 0.0
    if n >= 3:
        score += 6.0
    elif n >= 1:
        score += n * 2.0
    score += 4.0 if has_wikidata else 0.0
    score = min(10.0, score)
    ev = {
        "sameAs_count": n,
        "wikidata_linked": has_wikidata,
        "examples": [s["value"] for s in sources[:5]],
    }
    if score >= 8:
        return Verdict("pass", round(score, 1), "info", 0.95, ev)
    rem = (
        f"`sameAs` has {n} entries (Wikidata: {has_wikidata}). Target: 3+ links including "
        "a Wikidata entity, LinkedIn company page, and an official social profile."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "major" if score < 4 else "minor", 0.9,
        ev, rem,
    )


def check_organization_schema_completeness(p: ParsedHTML) -> Verdict:
    """ON-123 - Organization schema should have name + url + logo + sameAs
    + contactPoint. Missing fields weaken knowledge-graph eligibility.
    """
    org = _schema_block_of_type(p, "Organization") or _schema_block_of_type(p, "LocalBusiness")
    if not org:
        return Verdict(
            "fail", 2.0, "major", 0.95,
            {"present": False},
            "No Organization / LocalBusiness JSON-LD. Add it to the homepage at minimum: name, url, logo, sameAs, contactPoint.",
        )
    required = ("name", "url")
    boosters = ("logo", "sameAs", "contactPoint", "address", "telephone", "description")
    has_req = [k for k in required if org.get(k)]
    has_boost = [k for k in boosters if org.get(k)]
    score = len(has_req) * 3.0 + len(has_boost) * 0.8
    score = min(10.0, score)
    missing_req = sorted(set(required) - set(has_req))
    missing_boost = sorted(set(boosters) - set(has_boost))
    ev = {
        "required_present": has_req,
        "boosters_present": has_boost,
        "missing_required": missing_req,
        "missing_boosters": missing_boost,
    }
    if not missing_req and len(has_boost) >= 4:
        return Verdict("pass", round(score, 1), "info", 0.95, ev)
    rem = (
        f"Organization schema is missing required: {missing_req}. Boosters missing: {missing_boost}. "
        "Add logo + sameAs + contactPoint to qualify for a Google Knowledge Panel."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "major" if missing_req else "minor", 0.95,
        ev, rem,
    )


# ============================================================================
# 3.3 Topical Map & Topical Authority (site-wide)
# ============================================================================

def _cluster_pages_by_path(pages: list[ParsedHTML]) -> dict[str, list[ParsedHTML]]:
    """Group pages by their first non-empty URL path segment.
    /services/cleaning/ and /services/laundry/ -> 'services' cluster.
    """
    clusters: dict[str, list[ParsedHTML]] = {}
    for p in pages:
        path = urlparse(p.url).path.strip("/")
        first = path.split("/", 1)[0] if path else "home"
        clusters.setdefault(first or "home", []).append(p)
    return clusters


def check_topical_clusters(pages: list[ParsedHTML]) -> Verdict:
    """ON-124 (site-wide) - identify topical clusters and report sizes."""
    if len(pages) < 3:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "corpus too small"})
    clusters = _cluster_pages_by_path(pages)
    summary = sorted(
        ((name, len(pgs)) for name, pgs in clusters.items()),
        key=lambda x: -x[1],
    )
    top_clusters = [{"cluster": n, "pages": c} for n, c in summary[:10]]
    score = min(10.0, len(clusters) * 1.2)
    ev = {
        "cluster_count": len(clusters),
        "top_clusters": top_clusters,
    }
    if len(clusters) >= 4:
        return Verdict("pass", round(score, 1), "info", 0.8, ev)
    rem = (
        f"Only {len(clusters)} URL-path cluster(s). Topical authority requires a clear "
        "structure: e.g., /services/, /locations/, /blog/, /resources/. Create directories for "
        "each major topic so search engines can map the topical footprint."
    )
    return Verdict(
        status_from_score(score), round(score, 1),
        "major" if len(clusters) < 3 else "minor", 0.8,
        ev, rem,
    )


def check_cluster_depth(pages: list[ParsedHTML]) -> Verdict:
    """ON-125 (site-wide) - each cluster should have >= 3 supporting pages
    and >= 400 average words per page. Thin clusters get no topical credit.
    """
    if len(pages) < 3:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "corpus too small"})
    clusters = _cluster_pages_by_path(pages)
    thin = []
    healthy = []
    for name, pgs in clusters.items():
        avg_words = sum(p.word_count or 0 for p in pgs) / max(len(pgs), 1)
        record = {"cluster": name, "pages": len(pgs), "avg_words": int(avg_words)}
        if len(pgs) < 3 or avg_words < 400:
            thin.append(record)
        else:
            healthy.append(record)
    total = len(clusters)
    healthy_ratio = len(healthy) / max(total, 1)
    score = round(min(10.0, healthy_ratio * 12.0), 1)
    ev = {
        "healthy_clusters": healthy[:10],
        "thin_clusters": thin[:10],
        "healthy_ratio": round(healthy_ratio, 2),
    }
    if score >= 8:
        return Verdict("pass", score, "info", 0.8, ev)
    rem = (
        f"{len(thin)} of {total} clusters are thin (<3 pages or <400 avg words). "
        "Strengthen each topical cluster with at least 3 supporting pages of 500+ words."
    )
    return Verdict(
        status_from_score(score), score,
        "major" if score < 5 else "minor", 0.8,
        ev, rem,
    )


def check_hub_spoke_links(pages_with_crawl: dict) -> Verdict:
    """ON-126 (site-wide) - Within each cluster, the 'hub' (shallowest URL,
    usually the cluster root) should link to every spoke; every spoke should
    link back to the hub.

    Expects {"pages": list[ParsedHTML]} as the only key for now.
    """
    pages: list[ParsedHTML] = pages_with_crawl.get("pages") or []
    if len(pages) < 3:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "corpus too small"})
    clusters = _cluster_pages_by_path(pages)
    broken: list[dict] = []
    cluster_count = 0
    for name, pgs in clusters.items():
        if len(pgs) < 2:
            continue
        cluster_count += 1
        # Hub = page whose URL path has the fewest segments
        hub = min(pgs, key=lambda p: len(urlparse(p.url).path.strip("/").split("/")))
        spokes = [p for p in pgs if p.url != hub.url]
        hub_outlinks = {l.href for l in hub.links if l.is_internal}
        missing_from_hub = [s.url for s in spokes if s.url not in hub_outlinks]
        # Backlink check: each spoke should link back to hub
        missing_back = []
        for spoke in spokes:
            spoke_links = {l.href for l in spoke.links if l.is_internal}
            if hub.url not in spoke_links:
                missing_back.append(spoke.url)
        if missing_from_hub or missing_back:
            broken.append({
                "cluster": name,
                "hub": hub.url,
                "missing_from_hub": missing_from_hub[:5],
                "missing_back_to_hub": missing_back[:5],
            })
    if not cluster_count:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no multi-page clusters"})
    healthy = cluster_count - len(broken)
    healthy_ratio = healthy / max(cluster_count, 1)
    score = round(min(10.0, healthy_ratio * 12.0), 1)
    ev = {
        "clusters_checked": cluster_count,
        "broken_clusters": broken[:6],
        "healthy_ratio": round(healthy_ratio, 2),
    }
    if score >= 8:
        return Verdict("pass", score, "info", 0.8, ev)
    rem = (
        "Hub-spoke link integrity is incomplete. Every cluster root (hub) must link to all of its "
        "spoke pages, and every spoke must link back to the hub. This is how topical authority compounds."
    )
    return Verdict(
        status_from_score(score), score,
        "major" if score < 5 else "minor", 0.8,
        ev, rem,
    )


def check_topical_breadth(pages: list[ParsedHTML]) -> Verdict:
    """ON-127 (site-wide) - Heuristic: any single cluster with > 50% of the
    total pages indicates topical imbalance (one mega-section, the rest thin).
    """
    if len(pages) < 5:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "corpus too small"})
    clusters = _cluster_pages_by_path(pages)
    sizes = [(n, len(pgs)) for n, pgs in clusters.items()]
    total = sum(c for _, c in sizes)
    largest_name, largest_size = max(sizes, key=lambda x: x[1])
    dominance = largest_size / max(total, 1)
    if dominance >= 0.7:
        score = 3.0
    elif dominance >= 0.5:
        score = 6.0
    else:
        score = 10.0
    ev = {
        "cluster_count": len(clusters),
        "largest_cluster": largest_name,
        "largest_share": round(dominance, 2),
        "distribution": sorted([{"cluster": n, "pages": c} for n, c in sizes], key=lambda d: -d["pages"])[:8],
    }
    if score >= 8:
        return Verdict("pass", score, "info", 0.8, ev)
    rem = (
        f"Cluster '{largest_name}' holds {dominance:.0%} of all pages. "
        "Distribute content more evenly: target no single cluster above 50% so multiple topical "
        "footprints can rank in parallel."
    )
    return Verdict(
        status_from_score(score), score,
        "minor" if score >= 5 else "major", 0.8,
        ev, rem,
    )


# ============================================================================
# 3.4 Contextual Structure
# ============================================================================

def check_heading_paragraph_proximity(p: ParsedHTML) -> Verdict:
    """ON-128 - For each H2, the section beneath it should reference the
    page's central entity (title H1 tokens) within the first 100 words.
    Sections that drift off-topic confuse passage extraction.
    """
    if not p.paragraphs or not p.h1s:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no headings or paragraphs"})
    central = set(_tokens(p.h1s[0] + " " + (p.title or "")))
    if not central:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no central tokens"})
    # Heuristic: sample the first N paragraphs (proxy for "early-section")
    sample = p.paragraphs[:8]
    if not sample:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no paragraphs"})
    hits = sum(1 for para in sample if set(_tokens(para)) & central)
    ratio = hits / len(sample)
    score = round(min(10.0, ratio * 11.0), 1)
    ev = {
        "sampled_paragraphs": len(sample),
        "paragraphs_referencing_central_entity": hits,
        "ratio": round(ratio, 2),
        "central_tokens": sorted(list(central))[:8],
    }
    if score >= 7:
        return Verdict("pass", score, "info", 0.75, ev)
    rem = (
        f"Only {hits}/{len(sample)} early paragraphs reference the page's central entity. "
        "Each section should connect explicitly to the main topic to maintain contextual coherence."
    )
    return Verdict(
        status_from_score(score), score,
        "minor" if score >= 4 else "major", 0.75,
        ev, rem,
    )


def check_section_coherence(p: ParsedHTML) -> Verdict:
    """ON-129 - Compare H2 wording to the page's H1. Sections whose
    headings share zero tokens with the H1 are off-topic asides.
    """
    if not p.h1s:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no h1"})
    h1_tokens = set(_tokens(p.h1s[0]))
    h2_list = [h.text for h in p.headings if h.level == 2]
    if not h2_list:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no h2 sections"})
    offtopic = []
    for h2 in h2_list:
        if not (set(_tokens(h2)) & h1_tokens):
            offtopic.append(h2)
    # An off-topic ratio > 50% is the red zone; 0-20% is healthy variety
    offtopic_ratio = len(offtopic) / max(len(h2_list), 1)
    score = round(max(0.0, 10.0 - offtopic_ratio * 12.0), 1)
    ev = {
        "h2_count": len(h2_list),
        "offtopic_h2s": offtopic[:6],
        "offtopic_ratio": round(offtopic_ratio, 2),
    }
    if score >= 8:
        return Verdict("pass", score, "info", 0.7, ev)
    rem = (
        f"{len(offtopic)} of {len(h2_list)} H2 sections share no tokens with the H1. "
        "Either rewrite the H2 to connect to the central topic, or move the off-topic section to its own page."
    )
    return Verdict(
        status_from_score(score), score,
        "minor" if score >= 5 else "major", 0.7,
        ev, rem,
    )


# ============================================================================
# 3.5 Query Semantics & Search Intent
# ============================================================================

def _classify_intent(p: ParsedHTML) -> tuple[str, dict[str, int]]:
    """Returns (intent_label, signals_per_intent)."""
    text_pool = " ".join(filter(None, [
        p.title or "",
        " ".join(p.h1s or []),
        " ".join(h.text for h in p.headings or []),
        (p.body_text or "")[:3000],
        " ".join(p.button_texts or [])[:300],
    ])).lower()
    counts = {k: 0 for k in _INTENT_SIGNALS}
    for label, signals in _INTENT_SIGNALS.items():
        for s in signals:
            if "{" in s:
                continue
            if s in text_pool:
                counts[label] += 1
    label = max(counts, key=lambda k: counts[k])
    # If everything is 0, default to informational
    if counts[label] == 0:
        return ("informational", counts)
    return (label, counts)


def check_intent_classification(p: ParsedHTML) -> Verdict:
    """ON-130 - Classify the page's intent. The verdict is always 'pass'
    when a clear intent is detected; we surface the label as evidence so
    other tools can audit alignment.
    """
    label, counts = _classify_intent(p)
    top_count = counts[label]
    if top_count == 0:
        return Verdict(
            "warn", 4.0, "major", 0.7,
            {"intent": "ambiguous", "signal_counts": counts},
            "No clear intent signals detected (no commercial / transactional / informational vocabulary). "
            "Add explicit cues - a price, a CTA, a 'how to' heading, etc.",
        )
    return Verdict(
        "pass", 9.0, "info", 0.75,
        {"intent": label, "signal_counts": counts},
    )


def check_intent_alignment(p: ParsedHTML) -> Verdict:
    """ON-131 - Intent vs evidence alignment:
    - transactional pages must have a CTA + a price/quote signal
    - informational pages must have >= 500 words + headings as questions
    - commercial pages should compare or list multiple options
    """
    label, _ = _classify_intent(p)
    word_count = p.word_count or 0
    has_cta = bool(p.button_texts) or any(
        any(s in (link.anchor_text or "").lower() for s in ("book", "quote", "contact", "buy", "subscribe"))
        for link in (p.links or [])
    )
    headings = [h.text for h in p.headings if h.level in (2, 3)]
    has_questions = any(
        h.endswith("?") or _QUESTION_LEADERS.match(h) for h in headings
    )
    has_price = bool(re.search(r"(\$|£|€|/mo|/month|per\s+(month|year))", (p.body_text or "")[:8000]))
    has_compare = any(
        s in (p.body_text or "").lower()[:8000] for s in ("vs.", " vs ", "compared to", "alternative", "comparison")
    )
    score = 5.0
    ev = {
        "intent": label,
        "word_count": word_count,
        "has_cta": has_cta,
        "has_price_signal": has_price,
        "has_question_headings": has_questions,
        "has_comparison_language": has_compare,
    }
    if label == "transactional":
        if has_cta and (has_price or "quote" in (p.body_text or "").lower()[:5000]):
            score = 10.0
        elif has_cta or has_price:
            score = 7.0
        else:
            score = 3.0
            ev["misalignment"] = "transactional page has neither CTA nor price/quote signals"
    elif label == "informational":
        if word_count >= 500 and has_questions:
            score = 10.0
        elif word_count >= 300:
            score = 7.0
        else:
            score = 4.0
            ev["misalignment"] = "informational page under 300 words / no question headings"
    elif label == "commercial":
        if has_compare or has_price:
            score = 9.0
        else:
            score = 5.0
            ev["misalignment"] = "commercial intent lacks comparison or price signals"
    elif label == "navigational":
        score = 9.0
    if score >= 8:
        return Verdict("pass", score, "info", 0.75, ev)
    return Verdict(
        status_from_score(score), score,
        "major" if score < 5 else "minor", 0.75,
        ev,
        f"Page reads as {label}-intent but the on-page evidence does not match. "
        "Add CTA + price for transactional, depth + questions for informational, or comparison structure for commercial.",
    )


# ============================================================================
# 3.6 Lexical Semantics
# ============================================================================

def check_lexical_diversity(p: ParsedHTML) -> Verdict:
    """ON-132 - Type-Token Ratio. Higher = richer vocabulary.
    Healthy long-form content typically sits at 0.35 - 0.55.
    """
    tokens = _tokens(p.body_text or "")
    if len(tokens) < 100:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too few tokens"})
    ttr = len(set(tokens)) / len(tokens)
    if ttr >= 0.4:
        score = 10.0
        status = "pass"
        sev = "info"
        rem = None
    elif ttr >= 0.3:
        score = 7.0
        status = "warn"
        sev = "minor"
        rem = f"TTR {ttr:.2f} - vocabulary is reasonable but could be richer. Vary phrasing and avoid repeating the same noun forms."
    elif ttr >= 0.2:
        score = 4.0
        status = "warn"
        sev = "major"
        rem = f"TTR {ttr:.2f} - low lexical diversity. Replace repeated keyword phrases with synonyms, hypernyms, and varied sentence subjects."
    else:
        score = 2.0
        status = "fail"
        sev = "major"
        rem = f"TTR {ttr:.2f} - very low lexical diversity (possible keyword stuffing). Rewrite to use natural variation."
    return Verdict(status, score, sev, 0.85,
                   {"type_token_ratio": round(ttr, 3), "tokens": len(tokens), "unique_tokens": len(set(tokens))},
                   rem)


def check_synonym_variation_density(p: ParsedHTML) -> Verdict:
    """ON-133 - Detect over-repeated key terms. Any single non-stopword
    token at > 4% of body text is a keyword-stuffing red flag.
    """
    tokens = _tokens(p.body_text or "")
    if len(tokens) < 150:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too thin"})
    counts = Counter(tokens)
    top = counts.most_common(5)
    n = len(tokens)
    flagged = [{"token": t, "count": c, "share": round(c / n, 3)} for t, c in top if c / n > 0.04]
    if not flagged:
        top_token, top_count = top[0]
        return Verdict(
            "pass", 10.0, "info", 0.8,
            {"top_token": top_token, "top_share": round(top_count / n, 3), "samples": [
                {"token": t, "share": round(c / n, 3)} for t, c in top
            ]},
        )
    return Verdict(
        "warn", 4.0, "major", 0.85,
        {"flagged": flagged, "total_tokens": n},
        f"{len(flagged)} token(s) repeated above 4% of body content. Replace with synonyms, "
        "pronouns, and varied phrasing. This pattern is a classic keyword-stuffing footprint.",
    )


# ============================================================================
# 3.7 N-Gram Audit
# ============================================================================

def _ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    if len(tokens) < n:
        return []
    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def check_ngram_distribution(p: ParsedHTML) -> Verdict:
    """ON-134 - Top 1/2/3-grams + per-bigram stuffing check (any bigram
    > 2% of bigrams = potential stuffing).
    """
    tokens = _tokens(p.body_text or "")
    if len(tokens) < 150:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too thin"})
    bigrams = _ngrams(tokens, 2)
    trigrams = _ngrams(tokens, 3)
    bg_counts = Counter(bigrams)
    tg_counts = Counter(trigrams)
    n_bigrams = max(len(bigrams), 1)
    flagged_bg = [
        {"ngram": " ".join(ng), "count": c, "share": round(c / n_bigrams, 3)}
        for ng, c in bg_counts.most_common(5)
        if c / n_bigrams > 0.02
    ]
    ev = {
        "top_bigrams": [{"ngram": " ".join(ng), "count": c} for ng, c in bg_counts.most_common(5)],
        "top_trigrams": [{"ngram": " ".join(ng), "count": c} for ng, c in tg_counts.most_common(5)],
        "stuffing_flagged": flagged_bg,
    }
    if not flagged_bg:
        return Verdict("pass", 10.0, "info", 0.85, ev)
    return Verdict(
        "warn", 4.0, "major", 0.85, ev,
        f"{len(flagged_bg)} bigram(s) above 2% of all bigrams. Rewrite to introduce "
        "natural variation - swap the noun, vary the modifier, restructure the sentence.",
    )


def check_cross_page_ngram_overlap(pages: list[ParsedHTML]) -> Verdict:
    """ON-135 (site-wide) - Find page pairs whose top 5 bigrams overlap by
    >= 4 items. These are likely cannibalizing each other.
    """
    candidates = []
    for p in pages:
        toks = _tokens(p.body_text or "")
        if len(toks) < 150:
            continue
        bg = Counter(_ngrams(toks, 2)).most_common(5)
        candidates.append((p.url, {ng for ng, _ in bg}))
    if len(candidates) < 2:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "not enough content pages"})
    pairs = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            u1, s1 = candidates[i]
            u2, s2 = candidates[j]
            overlap = len(s1 & s2)
            if overlap >= 4:
                pairs.append({
                    "a": u1, "b": u2, "shared_top_bigrams": overlap,
                    "examples": [" ".join(ng) for ng in list(s1 & s2)[:3]],
                })
    if not pairs:
        return Verdict(
            "pass", 10.0, "info", 0.8,
            {"pages_checked": len(candidates), "overlap_pairs": 0},
        )
    score = max(0.0, 10.0 - len(pairs) * 1.5)
    return Verdict(
        status_from_score(score), round(score, 1),
        "major" if len(pairs) >= 3 else "minor", 0.8,
        {"pages_checked": len(candidates), "overlap_pairs": len(pairs), "examples": pairs[:5]},
        f"{len(pairs)} page pair(s) share 4+ top bigrams - likely cannibalization. "
        "Differentiate their primary keywords or consolidate with a 301.",
    )


# ============================================================================
# 3.8 Koray Framework - Semantic Content Writing Rules
# ============================================================================

def check_macro_context_connection(p: ParsedHTML) -> Verdict:
    """ON-136 - Koray's 'Macro Context Connection': the first paragraph
    must explicitly link to the parent domain topic. Detected by overlap
    between the first paragraph's tokens and the title's tokens.
    """
    if not p.paragraphs or not p.title:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "missing title or first paragraph"})
    first = p.paragraphs[0]
    overlap_set = set(_tokens(first)) & set(_tokens(p.title))
    overlap_count = len(overlap_set)
    if overlap_count >= 2:
        return Verdict(
            "pass", 10.0, "info", 0.8,
            {"overlap_count": overlap_count, "overlap_tokens": sorted(overlap_set)[:5]},
        )
    if overlap_count == 1:
        return Verdict(
            "warn", 6.0, "minor", 0.8,
            {"overlap_count": 1, "overlap_tokens": sorted(overlap_set)},
            "Opening paragraph mentions only one title token. Open with a sentence that explicitly states the topic + domain entity (Koray macro-context rule).",
        )
    return Verdict(
        "fail", 3.0, "major", 0.85,
        {"overlap_count": 0, "first_paragraph_excerpt": first[:160], "title": p.title[:120]},
        "Opening paragraph shares no tokens with the title - macro-context connection broken. "
        "Rewrite the first sentence to lead with the page's primary entity and category.",
    )


def check_definitional_content(p: ParsedHTML) -> Verdict:
    """ON-137 - Koray's definitional-content rule: at least one passage
    of the form '<X> is ...' or 'A <X> means ...' or 'Definition:'
    """
    text = (p.body_text or "")[:8000]
    if len(text) < 200:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too thin"})
    patterns = (
        r"\bis\s+(?:an?\s+|the\s+)?[a-z][a-z\s\-]{8,80}",
        r"\bmeans\s+[a-z][a-z\s\-]{5,80}",
        r"\bdefinition\s*[:\-]\s*[A-Za-z]",
        r"\brefers\s+to\s+[a-z][a-z\s\-]{5,80}",
        r"\b(?:also\s+)?known\s+as\s+[A-Za-z]",
    )
    hits = sum(1 for pat in patterns if re.search(pat, text))
    if hits >= 2:
        return Verdict("pass", 10.0, "info", 0.75, {"definitional_pattern_hits": hits})
    if hits == 1:
        return Verdict(
            "warn", 7.0, "minor", 0.75,
            {"definitional_pattern_hits": 1},
            "Only one definitional pattern detected. Add a clear definition of the central entity ('X is a...') in the first 200 words.",
        )
    return Verdict(
        "warn", 4.0, "minor", 0.75,
        {"definitional_pattern_hits": 0},
        "No definitional content detected. Open or include a passage that defines the central entity in plain language - this is the Koray definitional-content rule and a strong AI Overview signal.",
    )


def check_authoritative_citations(p: ParsedHTML) -> Verdict:
    """ON-138 - external links to authoritative sources (.gov, .edu,
    wikipedia, schema.org, etc) are a Koray information-quality signal.
    """
    ext = [l for l in (p.links or []) if not l.is_internal and l.href]
    auth_links: list[str] = []
    for link in ext:
        try:
            host = urlparse(link.href).netloc.lower()
        except ValueError:
            continue
        if any(host.endswith(t) for t in _AUTH_TLDS) or any(d in host for d in _AUTH_DOMAINS):
            auth_links.append(link.href)
    if (p.word_count or 0) < 300:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too thin to require citations"})
    n = len(set(auth_links))
    if n >= 2:
        return Verdict("pass", 10.0, "info", 0.8, {"authoritative_links": n, "examples": auth_links[:5]})
    if n == 1:
        return Verdict(
            "warn", 6.0, "minor", 0.8,
            {"authoritative_links": 1, "examples": auth_links},
            "Only 1 authoritative outbound citation. Aim for 2+ links to .gov / .edu / Wikipedia / official standards bodies to lift information quality and E-E-A-T.",
        )
    return Verdict(
        "warn", 3.0, "minor", 0.8,
        {"authoritative_links": 0, "external_links_total": len(ext)},
        "No authoritative outbound citations. Cite at least 2 high-trust sources (gov, edu, Wikipedia, schema.org) where the content makes factual claims.",
    )


def check_qa_pair_coverage(p: ParsedHTML) -> Verdict:
    """ON-139 - Koray Q&A rule: each section should answer an implicit
    question. Proxy: count question H2s + presence of FAQ schema.
    """
    h2 = [h.text for h in p.headings if h.level == 2]
    question_h2 = sum(
        1 for h in h2 if h.endswith("?") or _QUESTION_LEADERS.match(h)
    )
    has_faq = False
    for block in (p.schema_blocks or []):
        if isinstance(block, dict):
            t = block.get("@type")
            if isinstance(t, str) and t.lower() == "faqpage":
                has_faq = True
            elif isinstance(t, list) and any("faqpage" == str(x).lower() for x in t):
                has_faq = True
    if not h2:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "no H2 sections"})
    ratio = question_h2 / len(h2)
    score = round(min(10.0, ratio * 8.0 + (2.5 if has_faq else 0.0)), 1)
    ev = {
        "h2_count": len(h2),
        "question_h2": question_h2,
        "ratio": round(ratio, 2),
        "faq_schema": has_faq,
    }
    if score >= 7:
        return Verdict("pass", score, "info", 0.75, ev)
    rem = (
        f"{question_h2}/{len(h2)} H2 sections are framed as questions. "
        "Convert at least 30% of H2s to questions and add FAQ schema with 4-6 Q&A pairs to satisfy "
        "Koray's question-and-answer pair rule."
    )
    return Verdict(
        status_from_score(score), score,
        "minor" if score >= 4 else "major", 0.75,
        ev, rem,
    )


# ============================================================================
# 3.9 Information Quality
# ============================================================================

_FACT_RE = re.compile(
    r"(\b\d{1,4}\s*(?:%|percent|years|year|hours|hour|days|day|km|miles|million|billion|thousand)\b|"
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b|"
    r"\b\d{4}\b|"
    r"\b(?:ISO|EN|BS|DIN|RFC|ANSI|ASTM|HIPAA|GDPR|CCPA|OSHA)\s*\d+\b)",
    re.IGNORECASE,
)


def check_information_density(p: ParsedHTML) -> Verdict:
    """ON-140 - count fact tokens (numbers, dates, standards) per 100
    words. Pages with high density are more citable.
    """
    text = (p.body_text or "")[:30000]
    word_count = max(p.word_count or 0, 1)
    if word_count < 150:
        return Verdict("n_a", 0.0, "info", 0.7, {"reason": "too thin"})
    facts = _FACT_RE.findall(text)
    density = len(facts) / (word_count / 100.0)
    score = round(min(10.0, density * 2.5), 1)
    ev = {
        "fact_count": len(facts),
        "facts_per_100_words": round(density, 2),
        "samples": list({(f if isinstance(f, str) else f[0]) for f in facts})[:8],
    }
    if score >= 7:
        return Verdict("pass", score, "info", 0.75, ev)
    rem = (
        f"Information density is {density:.2f} facts per 100 words. "
        "Add concrete numbers, dates, certifications, and named standards. "
        "Pages dense with verifiable facts are far more likely to be cited by AI search."
    )
    return Verdict(
        status_from_score(score), score,
        "minor" if score >= 4 else "major", 0.75,
        ev, rem,
    )


_DATE_PATTERN = re.compile(
    r"\b(20\d{2}|19\d{2})\b|"
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}",
    re.IGNORECASE,
)


def check_date_freshness(p: ParsedHTML) -> Verdict:
    """ON-141 - look for datePublished / dateModified in schema OR a
    visible date in the first 1000 chars of body text. Pages without any
    date signal feel stale to both users and AI tools.
    """
    schema_date = None
    for block in (p.schema_blocks or []):
        if isinstance(block, dict):
            for k in ("dateModified", "datePublished", "uploadDate", "dateCreated"):
                if block.get(k):
                    schema_date = (k, str(block.get(k)))
                    break
        if schema_date:
            break
    body_dates = _DATE_PATTERN.findall((p.body_text or "")[:1500])
    if schema_date:
        return Verdict(
            "pass", 10.0, "info", 0.85,
            {"schema_date": {"key": schema_date[0], "value": schema_date[1]}, "body_date_hits": len(body_dates)},
        )
    if body_dates:
        return Verdict(
            "warn", 7.0, "minor", 0.7,
            {"body_date_hits": len(body_dates), "samples": [str(d)[:30] for d in body_dates[:3]]},
            "Page has visible dates but no `datePublished` / `dateModified` in schema. Add Article schema with both fields so AI tools can verify freshness.",
        )
    return Verdict(
        "warn", 4.0, "minor", 0.7,
        {"body_date_hits": 0},
        "No publication or modification date detected on this page. Add a visible 'Updated: <date>' line + Article schema datePublished/dateModified.",
    )


def check_author_expertise_signals(p: ParsedHTML) -> Verdict:
    """ON-142 (rollup) - byline + Person schema + credentials/sameAs.
    Higher signal = stronger E-E-A-T, which is also a Koray quality lever.
    """
    has_byline = bool(p.bylines)
    person = _schema_block_of_type(p, "Person")
    credentials = isinstance(person, dict) and bool(
        person.get("jobTitle") or person.get("description") or person.get("hasCredential")
    )
    same_as = isinstance(person, dict) and bool(person.get("sameAs"))
    score = (3.0 if has_byline else 0.0) + (3.5 if person else 0.0) + (1.5 if credentials else 0.0) + (2.0 if same_as else 0.0)
    score = round(min(10.0, score), 1)
    ev = {
        "byline_present": has_byline,
        "person_schema_present": person is not None,
        "credentials_in_schema": credentials,
        "person_sameAs_present": same_as,
    }
    # Only flag for content-heavy pages (where authorship matters)
    if (p.word_count or 0) < 500:
        return Verdict("n_a", 0.0, "info", 0.6, {**ev, "reason": "not a content page"})
    if score >= 8:
        return Verdict("pass", score, "info", 0.85, ev)
    rem = (
        "Strengthen author signals: add a visible byline, Person JSON-LD with jobTitle + sameAs "
        "(LinkedIn / professional profile), and a brief credentials line on the author page."
    )
    return Verdict(
        status_from_score(score), score,
        "major" if score < 4 else "minor", 0.85,
        ev, rem,
    )


# ============================================================================
# Aggregators
# ============================================================================

def iter_per_page_semantic_seo(p: ParsedHTML) -> Iterable[tuple[str, str, Verdict]]:
    """Yield (check_id, owner, verdict) for every per-page Module 3 check."""
    yield ("ON-119", "A2", check_central_entity_coherence(p))
    yield ("ON-121", "A2", check_entity_coverage(p))
    yield ("ON-122", "A2", check_sameas_presence(p))
    yield ("ON-123", "B4", check_organization_schema_completeness(p))
    yield ("ON-128", "A2", check_heading_paragraph_proximity(p))
    yield ("ON-129", "A2", check_section_coherence(p))
    yield ("ON-130", "A2", check_intent_classification(p))
    yield ("ON-131", "A2", check_intent_alignment(p))
    yield ("ON-132", "A2", check_lexical_diversity(p))
    yield ("ON-133", "A2", check_synonym_variation_density(p))
    yield ("ON-134", "A2", check_ngram_distribution(p))
    yield ("ON-136", "A1", check_macro_context_connection(p))
    yield ("ON-137", "A1", check_definitional_content(p))
    yield ("ON-138", "A1", check_authoritative_citations(p))
    yield ("ON-139", "A5", check_qa_pair_coverage(p))
    yield ("ON-140", "A1", check_information_density(p))
    yield ("ON-141", "A1", check_date_freshness(p))
    yield ("ON-142", "A1", check_author_expertise_signals(p))


def iter_site_wide_semantic_seo(
    pages: list[ParsedHTML],
) -> Iterable[tuple[str, str, Verdict]]:
    """Yield (check_id, owner, verdict) for every site-wide Module 3 check."""
    yield ("ON-120", "A2", check_knowledge_domain_consistency(pages))
    yield ("ON-124", "A2", check_topical_clusters(pages))
    yield ("ON-125", "A2", check_cluster_depth(pages))
    yield ("ON-126", "A4", check_hub_spoke_links({"pages": pages}))
    yield ("ON-127", "A2", check_topical_breadth(pages))
    yield ("ON-135", "A2", check_cross_page_ngram_overlap(pages))
