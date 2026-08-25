"""The canonical check registry - all 363 checks, loaded from ``checklists/*.yaml``.

WHY THIS EXISTS. Until now the checklists were documentation: nothing in the
engine read them at runtime. The consequence was measured on a real 197-page run
(``docs/audit/fixtures/README.md``): ``subcategory`` was populated on only **38%**
of emitted findings, because each analyzer set it by hand or not at all, and two
values were emitted that are not in the vocabulary at all (``site-structure``,
``geo-ai``). The pillar x subpoint axis the report is organised around therefore
could not be trusted.

This module makes the YAML the single source of truth for what a check IS:
its pillar, its subpoint, its owning agent, its default severity, what data it
needs, and whether a machine or a model decides it.

Three things fall out of having it, none of which were previously possible:

1. **Enrichment** - a finding's ``subcategory``/``owner_agent``/``automation``
   are joined from the registry by ``check_id``, so they are 100% populated and
   always in-vocabulary.
2. **Coverage** - "160 of 363 checks fired" becomes answerable, and so does
   "which ones did not, and why", which is what stops a skipped check reading
   like a passing one.
3. **Cost class** - every data source is classified once, so the set of checks a
   spend tier may run is DERIVED by set-containment rather than hand-curated.

Pure and dependency-light on purpose: yaml + stdlib, no network, no clock, no
database. It is imported by both the engine and (after vendoring) the platform.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

# --------------------------------------------------------------------------- #
# Cost classes
# --------------------------------------------------------------------------- #
# A data source's cost class is a property of the SOURCE, not of the check, so it
# is declared once here for all 53 sources that appear across the checklists.
#
#   zero        - derivable from the target site itself, or computed from other
#                 checks. No third party is paid and no quota is consumed.
#   free_quota  - a third-party API that is offered without charge but is
#                 rate-limited. Permitted on a zero-spend run, still budgeted.
#   connection  - free, but requires the client to have granted us access
#                 (Search Console, server logs). Absent grant => the check cannot run.
#   billable    - money leaves the account, per call.
CostClass = Literal["zero", "free_quota", "connection", "billable"]

_ZERO: frozenset[str] = frozenset({
    "axe_results", "competitor_crawl", "computed", "crawl_graph", "crawl_log",
    "crawled_html", "crawled_html_desktop", "crawled_html_googlebot_ua",
    "crawled_html_mobile", "crawled_html_raw", "crawled_html_user_ua", "dns",
    "http_headers", "http_resp", "http_status", "http_timing", "internal_links",
    "llms_txt", "robots", "schema_blocks", "site_pages", "sitemap",
    "tls_handshake", "w3c_validator", "web_fetch", "whois", "wikidata",
})
_FREE_QUOTA: frozenset[str] = frozenset({
    "psi", "psi_mobile", "crux",
    # Rendering was classed `zero` on the assumption of a local Playwright,
    # which consumes no quota. It is implemented against Firecrawl, whose free
    # tier is a metered monthly allowance, so `zero` would have let a free
    # lead-magnet audit burn the rendering budget. That is the google_nl defect
    # exactly: a cost the tier model could not see.
    "rendered_html", "rendered_html_mobile", "screenshot", "screenshot_breakpoints",
})
_CONNECTION: frozenset[str] = frozenset({
    "gsc_query", "gsc_ctr", "gsc_coverage", "server_logs",
})
_BILLABLE: frozenset[str] = frozenset({
    "competitor_moz_da", "competitor_moz_links", "embeddings", "google_nl",
    "google_places", "moz_da", "moz_keyword", "moz_links", "moz_links_historical",
    "moz_spam_score", "otterly", "serper", "serper_geo", "serper_top10", "web_search",
})


def cost_class(data_source: str) -> CostClass:
    """Classify one data source.

    An UNKNOWN source is classified ``billable`` deliberately. A source added to
    a checklist without being classified here must not be able to sneak into a
    zero-spend tier by defaulting to free - the whole point of the class system
    is that spend cannot happen by omission. See the google_nl defect recorded in
    ``docs/audit/fixtures/README.md``, which was exactly this failure with the
    flag list instead of the source list.
    """
    if data_source in _ZERO:
        return "zero"
    if data_source in _FREE_QUOTA:
        return "free_quota"
    if data_source in _CONNECTION:
        return "connection"
    return "billable"


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #

#: The four checklist files, and therefore the four PILLARS a check can live in.
#: NOTE the local file declares ``category: local-seo``, not ``local`` - and that
#: is also the string every emitted finding carries, so it is the correct join key.
PILLARS: tuple[str, ...] = ("on-page", "technical", "off-page", "local-seo")

#: The six DIMENSIONS the operator picks from. A dimension is not the same thing
#: as a pillar: GEO and Strategy are carved out of their home files by owning
#: agent, because that is how the work is actually divided.
DIMENSIONS: tuple[str, ...] = (
    "onpage", "technical", "offpage", "local", "geo", "strategy",
)

_PILLAR_TO_DIMENSION = {
    "on-page": "onpage",
    "technical": "technical",
    "off-page": "offpage",
    "local-seo": "local",
}


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """One row of a checklist file. Immutable; the YAML is the source of truth."""

    id: str
    name: str
    pillar: str            # on-page | technical | off-page | local  (the FILE)
    subcategory: str       # the SUBPOINT, e.g. "crawlability", "gbp", "eeat"
    owner_agent: str       # A1-A5 | B1-B5 | C1-C4 | D1-D4 | M2
    severity_default: str  # critical | major | minor | info
    data_sources: tuple[str, ...]
    analyzer: str
    automation: str        # full | ai-assisted

    @property
    def dimension(self) -> str:
        """The operator-facing dimension (R4-14's rule).

        GEO is owner-agent A5 and Strategy is owner-agent M2, wherever their
        checks physically live; everything else takes its file's pillar. The M2
        scoring checks are distributed across all four files, which is why
        dimension cannot simply be read off the filename.
        """
        if self.owner_agent == "A5":
            return "geo"
        if self.owner_agent == "M2":
            return "strategy"
        return _PILLAR_TO_DIMENSION[self.pillar]

    @property
    def cost_classes(self) -> frozenset[str]:
        return frozenset(cost_class(s) for s in self.data_sources)

    @property
    def is_deterministic(self) -> bool:
        """True when a machine decides it. ``ai-assisted`` means a model call,
        which is itself billable regardless of what data the check reads."""
        return self.automation == "full"

    def runs_under(self, permitted: frozenset[str]) -> bool:
        """Set-containment: every source this check needs is permitted.

        NOTE this is NECESSARY BUT NOT SUFFICIENT. A ``computed`` rollup passes
        containment even when every check it aggregates was skipped, which would
        publish a score over no data. Upstream-input gating is applied separately
        by the coverage pass; see ``inputs_ran`` there.
        """
        if not self.is_deterministic and "billable" not in permitted:
            return False
        return self.cost_classes <= permitted


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def checklist_dir() -> Path:
    """Locate ``checklists/``.

    Resolution order matters because this module has to work in three places: a
    developer checkout, an installed wheel, and (after the engine is vendored)
    inside the platform backend. An explicit env var wins so a deployment can
    always state the answer rather than rely on a relative path surviving a move.
    """
    override = os.getenv("AUDIT_CHECKLIST_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "checklists"
        if candidate.is_dir():
            return candidate
    return here.parents[1] / "checklists"


@lru_cache(maxsize=1)
def load_registry() -> dict[str, CheckSpec]:
    """All checks, keyed by check id. Cached - the YAML does not change at runtime."""
    registry: dict[str, CheckSpec] = {}
    directory = checklist_dir()
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pillar = raw.get("category")
        if pillar not in PILLARS:
            # Not a checklist file (tiers.yaml, data_sources.yaml, ...).
            continue
        for entry in raw.get("checks", []) or []:
            spec = CheckSpec(
                id=str(entry["id"]).strip(),
                name=str(entry.get("name", "")).strip(),
                pillar=pillar,
                subcategory=str(entry.get("subcategory", "") or "").strip(),
                owner_agent=str(entry.get("owner_agent", "") or "").strip(),
                severity_default=str(entry.get("severity_default", "") or "").strip(),
                data_sources=tuple(entry.get("data_sources", []) or []),
                analyzer=str(entry.get("analyzer", "") or "").strip(),
                automation=str(entry.get("automation", "") or "").strip(),
            )
            if spec.id in registry:
                raise ValueError(
                    f"duplicate check id {spec.id!r} in {path.name} - check ids are "
                    "the join key for enrichment, coverage and delta, so a duplicate "
                    "silently merges two different checks"
                )
            registry[spec.id] = spec
    return registry


def get(check_id: str) -> CheckSpec | None:
    return load_registry().get((check_id or "").strip())


def subpoints() -> dict[str, list[str]]:
    """The pillar -> subpoint vocabulary, sorted. This is the report's spine."""
    out: dict[str, set[str]] = {}
    for spec in load_registry().values():
        out.setdefault(spec.pillar, set()).add(spec.subcategory)
    return {k: sorted(v) for k, v in sorted(out.items())}



# --------------------------------------------------------------------------- #
# Subpoint display names
# --------------------------------------------------------------------------- #
# The checklist's subcategory keys are INTERNAL. Several are research shorthand
# that means nothing outside this repo - `semantic-3.8-koray` is a person's name,
# `semantic-3.9-info-quality` is a section number - and they were being printed
# straight onto a client-facing scorecard.
#
# Keyed by PILLAR then subcategory, because the same key means different things
# in different files: on-page `crawlability` is about one page's own directives,
# technical `crawl` is about site-wide crawl access.
#
# The KEY is never renamed. It is the join between the YAML, the emitted finding
# and the stored rollup; only the presentation changes.
SUBPOINT_LABEL: dict[str, dict[str, str]] = {
    "on-page": {
        "ai-search": "AI search readiness",
        "canonical": "Canonical tags",
        "content-quality": "Content quality",
        "conversion": "Conversion elements",
        "crawlability": "Crawlability",
        "cwv": "Core Web Vitals",
        "duplication": "Duplicate content",
        "eeat": "Experience & trust (E-E-A-T)",
        "engagement": "Engagement signals",
        "entities": "Entity coverage",
        "external-links": "Outbound links",
        "headings": "Heading structure",
        "images": "Images & alt text",
        "indexability": "Indexability",
        "internal-links": "Internal linking",
        "keywords": "Keyword targeting",
        "meta-description": "Meta descriptions",
        "mobile": "Mobile experience",
        "penalties": "Penalty risk",
        "readability": "Readability",
        "schema": "Structured data",
        "scoring": "On-page rollups",
        "search-intent": "Search intent match",
        "security": "Page security",
        "semantic-3.1-central-entity": "Central entity clarity",
        "semantic-3.2-entity": "Entity completeness",
        "semantic-3.3-topical-map": "Topical map coverage",
        "semantic-3.4-contextual": "Contextual connection",
        "semantic-3.5-query-intent": "Query intent alignment",
        "semantic-3.6-lexical": "Vocabulary range",
        "semantic-3.7-ngram": "Phrase cannibalisation",
        "semantic-3.8-koray": "Contextual hierarchy",
        "semantic-3.9-info-quality": "Information density",
        "snippets": "Featured snippet fitness",
        "structured-content": "Content structure",
        "titles": "Title tags",
        "topics": "Topic coverage",
        "url": "URL structure",
        "ux": "Page experience",
    },
    "technical": {
        "accessibility": "Accessibility",
        "amp": "AMP",
        "caching": "Caching",
        "canonical": "Canonicalisation",
        "compression": "Compression",
        "crawl": "Crawl access",
        "crawl-logs": "Crawl logs",
        "cwv": "Core Web Vitals",
        "domain": "Domain & DNS",
        "duplication": "Duplicate URLs",
        "errors": "HTTP errors",
        "html": "HTML validity",
        "indexability": "Indexation",
        "internal-links": "Link architecture",
        "international": "International targeting",
        "low-quality": "Thin & low-value pages",
        "media": "Media delivery",
        "mobile": "Mobile rendering",
        "pagination": "Pagination",
        "performance": "Page speed",
        "redirects": "Redirects",
        "rendering": "JavaScript rendering",
        "robots-sitemap": "Robots & sitemaps",
        "schema": "Structured data",
        "scoring": "Technical rollups",
        "security": "Security & HTTPS",
        "server": "Server & hosting",
        "social": "Social markup",
        "spam": "Spam signals",
        "url-parameters": "URL parameters",
    },
    "off-page": {
        "ai-search": "AI search authority",
        "anchors": "Anchor text profile",
        "authority": "Domain authority",
        "backlinks": "Backlink profile",
        "brand-signals": "Brand signals",
        "competitor": "Competitor gap",
        "diversity": "Link diversity",
        "historical": "Link history",
        "link-attributes": "Link attributes",
        "link-placement": "Link placement",
        "link-quality": "Link quality",
        "link-types": "Link types",
        "outreach": "Outreach opportunities",
        "pbn": "Private network risk",
        "scoring": "Off-page rollups",
        "topical-authority": "Topical authority",
        "toxicity": "Toxic links",
    },
    "local-seo": {
        "citations": "Citations & directories",
        "gbp": "Google Business Profile",
        "local-keywords": "Local keywords",
        "local-pack": "Local pack presence",
        "nap": "NAP consistency",
        "reviews": "Reviews & ratings",
        "schema": "Local schema",
        "scoring": "Local rollups",
    },
}


def subpoint_label(pillar: str, subcategory: str) -> str:
    """The operator/client-facing name for a subpoint.

    Falls back to a title-cased key rather than an empty string: an unmapped
    subpoint should read awkwardly, not disappear from a scorecard.
    """
    mapped = SUBPOINT_LABEL.get(pillar, {}).get(subcategory)
    if mapped:
        return mapped
    return (subcategory or "").replace("-", " ").replace("_", " ").strip().capitalize()


def checks_for_dimensions(dimensions: frozenset[str] | None) -> frozenset[str]:
    """Check ids belonging to the selected dimensions. Empty/None selects ALL,
    which is the documented meaning of an empty type picker (ADM-012 / AUD-005)."""
    reg = load_registry()
    if not dimensions:
        return frozenset(reg)
    return frozenset(cid for cid, s in reg.items() if s.dimension in dimensions)
