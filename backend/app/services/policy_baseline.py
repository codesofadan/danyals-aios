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
    {
        "id": "rec-base-cwv-regression",
        "kb_entry_id": None,
        "kb_ref": "kb-base-cwv-regression",
        "title": "Escalate a Core Web Vitals regression within 24 hours of detection",
        "why": (
            "A re-run audit that shows INP, LCP or CLS crossing from green/amber into red "
            "versus the client's last passing crawl is a ranking- and revenue-risk event, not "
            "routine noise - it needs a human owner and a client-visible timeline immediately, "
            "not at the next scheduled review."
        ),
        "action": (
            "When the audit engine flags a Core Web Vitals metric regressing into 'red' "
            "versus the prior crawl, open a P1 ticket, notify the assigned account lead within "
            "24 hours, and post a remediation ETA to the client portal before the next crawl."
        ),
        "scope": "global",
        "target_module": "audit",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-spam-violation",
        "kb_entry_id": None,
        "kb_ref": "kb-base-spam-violation",
        "title": "Escalation protocol for a Google spam-policy violation found in audit",
        "why": (
            "A technical/on-page audit that surfaces signals of a spam-policy violation "
            "(cloaking, scaled thin content, doorway pages, link-scheme footprints) exposes "
            "the client to a manual action or ranking demotion; treating it as a routine audit "
            "finding instead of a compliance incident risks the client's entire domain."
        ),
        "action": (
            "Any audit finding tagged as a spam-policy risk is escalated same-day to the "
            "account lead and the client, with the offending pages/links listed and a "
            "remediation-or-disavow plan proposed before any further off-page work resumes on "
            "that domain."
        ),
        "scope": "global",
        "target_module": "audit",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-link-velocity",
        "kb_entry_id": None,
        "kb_ref": "kb-base-link-velocity",
        "title": "Cap off-page link-velocity to a safe, ramping threshold per client",
        "why": (
            "Publishing Web 2.0 properties and citations faster than a domain's existing "
            "authority and age can support creates an unnatural backlink-velocity footprint "
            "that risks a manual or algorithmic devaluation instead of the intended authority "
            "gain."
        ),
        "action": (
            "Cap new referring-domain creation from the Web 2.0 publisher network to a "
            "ramping per-client monthly threshold (new/low-authority sites start lower), "
            "reviewed against the off-page board's new-domain rate before each publishing "
            "batch is queued."
        ),
        "scope": "global",
        "target_module": "portal",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-content-eeat-bar",
        "kb_entry_id": None,
        "kb_ref": "kb-base-content-eeat-bar",
        "title": "Minimum E-E-A-T bar every AI-assisted draft must clear before publish",
        "why": (
            "AI-assisted drafting speeds up production, but a draft that ships without "
            "first-hand detail, a credentialed byline or fact-checked claims is exactly the "
            "'thin, templated, scaled' content pattern helpful-content systems are built to "
            "demote - the speed gain is worthless if the page can't rank."
        ),
        "action": (
            "Require every AI-assisted draft in the Content Studio to carry a named author "
            "byline, at least one first-hand or client-sourced detail, and a human fact-check "
            "pass before it is queued for WordPress publish."
        ),
        "scope": "global",
        "target_module": "content",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-local-nap-sla",
        "kb_entry_id": None,
        "kb_ref": "kb-base-local-nap-sla",
        "title": "NAP-consistency SLA across all submitted citations",
        "why": (
            "Local-pack ranking is sensitive to Name/Address/Phone mismatches across "
            "citations; a citation submitted with stale or inconsistent NAP data actively "
            "hurts the client instead of helping, and mismatches compound the longer they sit "
            "unresolved across the citation network."
        ),
        "action": (
            "Every citation submission is reconciled against the client's canonical NAP record "
            "before submission, and any live mismatch found on the citation board is corrected "
            "within 5 business days of detection."
        ),
        "scope": "client",
        "target_module": "portal",
        "region": "national",
        "region_label": "US · National",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-geo-citability",
        "kb_entry_id": None,
        "kb_ref": "kb-base-geo-citability",
        "title": "GEO / AI-Overview citability standard for every published page",
        "why": (
            "AI Overviews and other generative answers only cite passages that are extractable "
            "on their own - a page that reads well to a human but buries its answer inside long "
            "unstructured prose will lose the AI-search reference to a competitor's page that "
            "answers first."
        ),
        "action": (
            "Every content brief and every GEO audit re-check requires a standalone, "
            "citable answer passage (40-60 words) plus semantic heading structure the AI-search "
            "extractor can parse without additional context."
        ),
        "scope": "global",
        "target_module": "content",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-budget-cap-breach",
        "kb_entry_id": None,
        "kb_ref": "kb-base-budget-cap-breach",
        "title": "Client budget-cap breach protocol",
        "why": (
            "Audit, content generation and off-page publishing all draw on metered API/provider "
            "spend against a client's budget; letting a job continue past the client's approved "
            "cap without a pause and a conversation risks billing disputes and an eroded client "
            "relationship."
        ),
        "action": (
            "When a client's tracked spend crosses 90% of its budget cap, pause further "
            "paid jobs for that client automatically and notify the account lead; do not resume "
            "spend until the lead or client confirms a new cap."
        ),
        "scope": "client",
        "target_module": "portal",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-citation-quality-bar",
        "kb_entry_id": None,
        "kb_ref": "kb-base-citation-quality-bar",
        "title": "Citation and Web 2.0 submission compliance/quality bar",
        "why": (
            "Not every directory or Web 2.0 platform is worth a submission - low-quality, "
            "deindexed or spam-flagged listing sites add zero authority and can flag the whole "
            "citation profile as low-effort; only platforms that meet a minimum trust bar should "
            "receive client NAP data or published property content."
        ),
        "action": (
            "Before a platform is added to (or kept on) the citation/Web 2.0 publisher roster, "
            "verify it is indexed, has real domain authority and an acceptable spam score; drop "
            "any platform that fails a quarterly re-check from future submission batches."
        ),
        "scope": "global",
        "target_module": "portal",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-audit-cadence",
        "kb_entry_id": None,
        "kb_ref": "kb-base-audit-cadence",
        "title": "Audit re-run cadence policy per client tier",
        "why": (
            "Findings go stale - a technical/on-page/off-page/local/GEO audit that's months old "
            "can miss a regression, a new spam-policy exposure or a competitor's move; without a "
            "minimum re-run cadence, clients are advised on data that no longer reflects their "
            "site."
        ),
        "action": (
            "Re-run the full audit suite at least every 30 days for active paid clients "
            "(every 90 days for lighter tiers), and trigger an out-of-cycle re-run immediately "
            "after any major client site change or Google core update."
        ),
        "scope": "global",
        "target_module": "audit",
        "region": "global",
        "region_label": "Global",
        "status": "new",
        "affected_clients": "",
    },
    {
        "id": "rec-base-wp-publish-rollback",
        "kb_entry_id": None,
        "kb_ref": "kb-base-wp-publish-rollback",
        "title": "WordPress publish rollback policy",
        "why": (
            "An automated publish to a client's live WordPress site (via the AIOS publisher "
            "plugin) can break a template, a plugin dependency or SEO metadata on push; without "
            "a fast rollback path a single bad publish becomes site-down or de-indexing risk "
            "for the client."
        ),
        "action": (
            "Every scheduled or on-demand WordPress publish snapshots the prior revision "
            "before it goes live, and any publish that trips a post-publish health check "
            "(broken render, 5xx, missing metadata) auto-rolls back to that snapshot and alerts "
            "the account lead."
        ),
        "scope": "global",
        "target_module": "content",
        "region": "global",
        "region_label": "Global",
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
