"""Baseline Policy-Radar recommendations - the evergreen, always-true SEO
best-practices distilled from the Content Doctrine / general 2026 SEO.

These exist so the Command Center is POPULATED PRE-LIVE, before the change-detection
watcher (a later chunk) starts producing KB-derived recommendations. They are a
CONSTANT set (no watcher, no live source), surfaced by the repo alongside the
DB-backed recommendations.

Each entry is a ROW-SHAPED dict (``recommendations`` column names) so it flows
through ``RecommendationResponse.from_row`` exactly like a DB row. Its ``id`` is a
stable synthetic ``rec-base-*`` string and ``kb_ref`` a synthetic ``kb-base-*``
(there is no live KB entry, so ``kb_entry_id`` is ``None``). ``merge_baseline``
dedupes by ``kb_ref``: once a baseline rec is MATERIALIZED into the DB (the first
time a lead acknowledges/applies/dismisses it), the DB row wins and the constant is
no longer surfaced - so a rec appears exactly once whatever its state.
"""

from __future__ import annotations

from typing import Any

# Row-shaped constants (recommendations column names). status starts 'new' (open) so
# every baseline rec shows in the Command Center's open queue pre-live.
BASELINE_RECOMMENDATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "rec-base-eeat",
        "kb_entry_id": None,
        "kb_ref": "kb-base-eeat",
        "title": "Lead with first-hand experience & demonstrable expertise (E-E-A-T)",
        "why": (
            "Helpful-content and core systems reward pages that show real experience, "
            "expertise, authority and trust; thin, templated or scaled AI content is the "
            "single biggest sitewide ranking risk."
        ),
        "action": (
            "Keep the audit check 'E-E-A-T & helpful-content depth scan' on every crawl - "
            "flag author bylines, credentials, original media and first-hand detail on "
            "money pages."
        ),
        "scope": "global",
        "target_module": "audit",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-cwv",
        "kb_entry_id": None,
        "kb_ref": "kb-base-cwv",
        "title": "Pass Core Web Vitals - INP is the page-experience gate",
        "why": (
            "Interaction to Next Paint (INP) replaced FID as a Core Web Vital; poor INP/LCP/"
            "CLS suppress rankings and conversions, especially on mobile."
        ),
        "action": (
            "Keep the audit check 'Core Web Vitals (INP/LCP/CLS)' green - budget INP < 200ms, "
            "LCP < 2.5s, CLS < 0.1, and defer non-critical JS."
        ),
        "scope": "global",
        "target_module": "audit",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-geo",
        "kb_entry_id": None,
        "kb_ref": "kb-base-geo",
        "title": "Write answer-first, entity-rich passages for AI Overviews (GEO)",
        "why": (
            "Generative answers surface on more queries; pages that open with a concise, "
            "citable summary and a clear entity list win the AI Overview reference and its "
            "referral traffic."
        ),
        "action": (
            "Require a 40-60 word answer summary + a primary-entity list at the top of every "
            "content brief in the Content Studio."
        ),
        "scope": "global",
        "target_module": "content",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-schema",
        "kb_entry_id": None,
        "kb_ref": "kb-base-schema",
        "title": "Ship valid, complete structured data on every template",
        "why": (
            "Valid JSON-LD (Article, Product, LocalBusiness, FAQ, Breadcrumb) unlocks rich "
            "results and reinforces entity understanding; missing or invalid required fields "
            "silently drop the rich snippet."
        ),
        "action": (
            "Keep the audit check 'Structured-data coverage & validity' validating the "
            "@type-appropriate required fields on each page template."
        ),
        "scope": "global",
        "target_module": "audit",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-topical",
        "kb_entry_id": None,
        "kb_ref": "kb-base-topical",
        "title": "Build topical authority with internal linking & content clusters",
        "why": (
            "Depth of coverage across a topic cluster plus descriptive internal links "
            "distributes authority and signals expertise better than isolated one-off pages."
        ),
        "action": (
            "In content guidance, plan pillar + supporting-cluster briefs and require "
            "descriptive internal links between related pages on every new draft."
        ),
        "scope": "global",
        "target_module": "content",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-local-nap",
        "kb_entry_id": None,
        "kb_ref": "kb-base-local-nap",
        "title": "Keep Google Business Profile complete & NAP consistent",
        "why": (
            "For local and service-area businesses, a complete GBP plus consistent Name / "
            "Address / Phone across citations is decisive for map-pack visibility and "
            "proximity ranking."
        ),
        "action": (
            "Raise a standing client advisory for local clients to verify GBP categories, "
            "hours and NAP consistency across top citations each quarter."
        ),
        "scope": "client",
        "target_module": "portal",
        "region": "national",
        "region_label": "US · National",
        "status": "new",
        "affected_clients": "",
    },
)


def baseline_recommendation_rows() -> list[dict[str, Any]]:
    """A fresh list of shallow copies of the baseline recommendation rows.

    Copies so a caller (or ``from_row``) can never mutate the module constant."""
    return [dict(row) for row in BASELINE_RECOMMENDATIONS]


def merge_baseline(
    db_rows: list[dict[str, Any]], *, include_baseline: bool = True
) -> list[dict[str, Any]]:
    """DB recommendations first, then the baseline recs not yet materialized.

    Dedup is by ``kb_ref``: a baseline rec whose ``kb_ref`` already exists among the
    DB rows has been materialized (a lead acted on it), so the DB row wins and the
    constant is dropped. The DB rows keep their own ordering (the repo sorts them);
    baseline recs append in their declared order. ``include_baseline=False`` returns
    the DB rows untouched (e.g. an internal count)."""
    if not include_baseline:
        return db_rows
    seen = {str(r.get("kb_ref", "")) for r in db_rows}
    extra = [r for r in baseline_recommendation_rows() if r["kb_ref"] not in seen]
    return [*db_rows, *extra]


def baseline_by_id(rec_id: str) -> dict[str, Any] | None:
    """The baseline recommendation row with this synthetic ``rec-base-*`` id, or
    ``None``. Used to MATERIALIZE a baseline rec into the DB on first transition."""
    for row in BASELINE_RECOMMENDATIONS:
        if row["id"] == rec_id:
            return dict(row)
    return None
