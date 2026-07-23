"""Citation-builder orchestration (7B-4): PURE reasoning over catalog rows + a
business profile - no DB, no network (mirrors ``local_seo.service`` /
``web2_pipeline``'s plan stage). The privileged reads/writes live in ``repo.py``;
the actual submit calls live in ``integrations.citation_*``; this layer only
decides WHICH directories a campaign queues, WHAT it will cost, and WHICH engine a
queued row's ``submit_method`` routes to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.modules.citations.schemas import (
    AUTOMATABLE_TIERS,
    DEFAULT_CAMPAIGN_CAP,
    DEFAULT_MIN_AUTHORITY,
)
from integrations.citation_submitters import CitationJob, CitationSubmitter

# core builds first everywhere, then tier1, then tier2 (the reference plan's build
# order); an unknown authority_tier sorts last with tier2.
_TIER_RANK: dict[str, int] = {"core": 0, "tier1": 1, "tier2": 2}


def automatable_directories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every catalog row a campaign COULD queue - ``manual_only`` is filtered out
    here, once, so no caller has to remember the exclusion. A row fed by another
    aggregator (``submit_method`` starting ``aggregator:fed_by_``) is ALSO excluded:
    there is nothing to submit, it is already covered by seeding the core
    aggregator(s) it is fed from."""
    return [
        r
        for r in rows
        if r.get("tier") in AUTOMATABLE_TIERS
        and not str(r.get("submit_method") or "").startswith("aggregator:fed_by_")
    ]


@dataclass
class DirectorySelection:
    """The outcome of applying the reference-plan strategy to a catalog: the ORDERED
    rows to queue, plus a transparent count of what each rule excluded (so a capped or
    filtered batch is never a silent truncation - the counts surface to the operator)."""

    selected: list[dict[str, Any]] = field(default_factory=list)
    excluded_off_vertical: int = 0
    excluded_low_authority: int = 0
    excluded_marketplace: int = 0
    capped: int = 0


def _serves_vertical(row: dict[str, Any], vertical: str | None) -> bool:
    """A directory serves a client when it is GENERAL (no verticals = applies to all)
    or explicitly names the client's vertical. With no resolved vertical we keep only
    general rows - never blast a niche directory at an unknown industry."""
    verticals = row.get("verticals") or []
    if not verticals:
        return True
    return vertical is not None and vertical in verticals


def select_campaign_directories(
    rows: list[dict[str, Any]],
    *,
    vertical: str | None = None,
    cap: int | None = DEFAULT_CAMPAIGN_CAP,
    min_authority: int | None = DEFAULT_MIN_AUTHORITY,
    include_marketplaces: bool = False,
) -> DirectorySelection:
    """Apply the reference-plan selection to already-automatable rows: match the
    client's vertical, drop the sub-DA spam tail, optionally exclude lead-gen
    marketplaces, order by build-tier then authority, and cap the batch.

    Ordering: authority_tier (core -> tier1 -> tier2) then authority DESC (a scored
    row outranks a lower-scored one; an UNSCORED row - authority NULL - sorts after
    scored rows within its tier rather than being dropped) then name for stability.
    Every exclusion is counted, so ``cap`` and the filters are transparent, not silent.
    """
    result = DirectorySelection()
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not _serves_vertical(row, vertical):
            result.excluded_off_vertical += 1
            continue
        if not include_marketplaces and bool(row.get("is_marketplace")):
            result.excluded_marketplace += 1
            continue
        da = row.get("authority")
        if min_authority is not None and da is not None and int(da) < min_authority:
            result.excluded_low_authority += 1
            continue
        kept.append(row)

    def _sort_key(r: dict[str, Any]) -> tuple[int, int, str]:
        rank = _TIER_RANK.get(str(r.get("authority_tier") or "tier2"), 2)
        da = r.get("authority")
        # higher DA first -> negate; unscored (None) -> 0 so it sits just below any
        # positive-DA row in the same tier but above genuinely low-DA ones.
        da_key = -int(da) if da is not None else 0
        return (rank, da_key, str(r.get("name") or ""))

    kept.sort(key=_sort_key)

    if cap and cap > 0 and len(kept) > cap:
        result.capped = len(kept) - cap
        kept = kept[:cap]

    result.selected = kept
    return result


def is_live_directory_response(status_code: int | None) -> bool:
    """Whether an HTTP status from a catalog URL health-check means the directory is
    still LIVE (reference plan step 7: "verify live at submission - directory churn is
    high, many 2019-era entries are parked or dead"). A 2xx/3xx (redirects to a live
    page) is live; a 4xx/5xx or an unreachable host (None) is treated as dead so the
    row can be deactivated rather than wasting a submission attempt on a parked domain.
    A 403/429 (bot-blocked but alive) is the one grey area - treated as LIVE, since the
    domain answered, to avoid deactivating a real directory that merely refused a HEAD.
    """
    if status_code is None:
        return False
    if status_code in (403, 429):
        return True
    return 200 <= status_code < 400


def estimate_campaign_cost(rows: list[dict[str, Any]], settings: Settings) -> float:
    """The R5 pre-check total for a batch of directory rows, BEFORE any submit runs -
    a lead reviews this (the ``citations`` dial defaults to ``byhand``) rather than
    discovering the spend after the fact. Sums each row's own tier estimate; an
    ``api``/``aggregator`` row is a plain call, a ``bot_fillable`` row is Playwright
    compute only, a ``captcha_assisted`` row additionally carries one CAPTCHA solve."""
    total = 0.0
    for row in rows:
        tier = row.get("tier")
        if tier in ("api", "aggregator"):
            total += settings.citation_api_cost_estimate
        elif tier == "bot_fillable":
            total += settings.citation_bot_cost_estimate
        elif tier == "captcha_assisted":
            total += settings.citation_captcha_cost_estimate
    return round(total, 4)


def submit_method_label(directory: dict[str, Any]) -> str:
    """The ``submit_method`` string stored on a queued citation row - copied
    verbatim from the catalog so the worker's dispatch (``submitter_for`` below)
    only ever has to read the citation row, never re-join the catalog to redecide."""
    return str(directory.get("submit_method") or "")


def submitter_for(
    submit_method: str,
    *,
    api_submitters: dict[str, CitationSubmitter],
    bot: CitationSubmitter | None,
    apify: CitationSubmitter | None,
) -> tuple[CitationSubmitter | None, str]:
    """Pick the engine one queued row's ``submit_method`` routes to.

    Returns ``(submitter, reason)`` - ``reason`` is only meaningful when
    ``submitter`` is ``None`` (why nothing could be dispatched: an unconfigured
    engine, or a directory that needs no separate action at all). Never raises -
    an unrecognised ``submit_method`` is a clean "no engine", not a crash.
    """
    if submit_method.startswith("aggregator:fed_by_"):
        return None, "no action needed - covered by seeding the core aggregator(s)"
    if submit_method.startswith("api:"):
        key = submit_method.split(":", 1)[1]
        sub = api_submitters.get(key)
        if sub is not None:
            return sub, ""
        # FALL BACK to Apify rather than blocking - the client's explicit call
        # (2026-07-23): a queued directory must be BUILT by whatever engine can
        # reach it, not parked behind an unconfigured native integration.
        if apify is not None:
            return apify, ""
        return None, f"no API submitter configured for {key!r}"
    if submit_method.startswith("aggregator:") or submit_method.startswith("bot:"):
        if bot is not None:
            return bot, ""
        if apify is not None:
            return apify, ""
        return None, "Playwright bot not installed/configured"
    if submit_method == "apify":
        return apify, ("" if apify is not None else "Apify fallback not configured")
    return None, f"no automatable engine for submit_method={submit_method!r}"


# --------------------------------------------------------------------------- #
# NAP bridge: derive a submission business_profile from the client's own NAP
# (client_business_profiles, 0051). PURE - the repo does the actual insert.
# --------------------------------------------------------------------------- #
def derive_business_profile_fields(client_nap: dict[str, Any]) -> dict[str, Any]:
    """Map a ``client_business_profiles`` row (the client's identity captured at
    creation) onto the column dict for a ``business_profiles`` SUBMISSION row.

    The primary category leads the ordered ``categories`` list (a listing form fills
    the primary first), then the extras. ``label``/``is_primary`` mark it the client's
    canonical location. This is why "No business profile yet for this client" no longer
    dead-ends: the citation-builder derives its first submission profile from the NAP the
    wizard already collected, instead of demanding the operator re-enter it."""
    primary = str(client_nap.get("primary_category") or "").strip()
    extras = [str(c).strip() for c in (client_nap.get("extra_categories") or []) if str(c).strip()]
    categories = ([primary] if primary else []) + [c for c in extras if c != primary]
    hours = client_nap.get("hours")
    return {
        "label": "Primary",
        "business_name": str(client_nap.get("business_name") or ""),
        "address_line1": str(client_nap.get("address_line1") or ""),
        "address_line2": str(client_nap.get("address_line2") or ""),
        "city": str(client_nap.get("city") or ""),
        "region": str(client_nap.get("region") or ""),
        "postal_code": str(client_nap.get("postal_code") or ""),
        "market": str(client_nap.get("market") or "US"),
        "phone": str(client_nap.get("phone") or ""),
        "website_url": str(client_nap.get("website_url") or ""),
        "categories": categories,
        "hours": dict(hours) if isinstance(hours, dict) else {},
        "is_primary": True,
    }


# --------------------------------------------------------------------------- #
# Gap analysis: what is already cited vs what the catalog says is still missing.
# PURE (no DB, no network) so the whole decision is unit-testable.
# --------------------------------------------------------------------------- #
# A citation row COVERS its directory when it is in-flight or live; a blocked/failed/
# never-started+missing row does NOT (it is retryable - still a gap to close).
_COVERING_SUBMIT: frozenset[str] = frozenset({"queued", "submitting", "submitted", "verified"})
_LIVE_SUBMIT: frozenset[str] = frozenset({"submitted", "verified"})
_COVERING_NAP: frozenset[str] = frozenset({"consistent", "inconsistent"})


def _norm_directory(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _row_covers(row: dict[str, Any]) -> bool:
    """Whether an existing citation counts as coverage of its directory. A monitoring
    row that FOUND a listing (nap consistent/inconsistent) covers it; a submission row
    that is queued/live covers it; a blocked/failed row is an open gap, not coverage."""
    submit = str(row.get("submit_status") or "not_started")
    nap = str(row.get("nap_status") or "")
    if submit in _COVERING_SUBMIT:
        return True
    return submit not in ("failed", "blocked") and nap in _COVERING_NAP


@dataclass
class CitationGap:
    """The reconciliation of a client's existing citations against the automatable
    catalog: what is covered, what is still MISSING (the build target), the live listing
    URLs already earned, and an honest per-status tally."""

    existing_count: int = 0
    covered_count: int = 0
    missing: list[dict[str, Any]] = field(default_factory=list)
    live_urls: list[dict[str, str]] = field(default_factory=list)
    by_submit_status: dict[str, int] = field(default_factory=dict)
    by_nap_status: dict[str, int] = field(default_factory=dict)


def compute_citation_gap(
    *,
    directories: list[dict[str, Any]],
    existing_citations: list[dict[str, Any]],
    vertical: str | None = None,
    cap: int | None = DEFAULT_CAMPAIGN_CAP,
    min_authority: int | None = DEFAULT_MIN_AUTHORITY,
    include_marketplaces: bool = False,
) -> CitationGap:
    """Reconcile existing citations against the catalog and report the gap.

    (a) analyse existing citations - count them + tally where they stand (per submit and
        per NAP status), and collect the live listing URLs already earned;
    (b) compute MISSING directories - apply the SAME reference-plan selection a campaign
        uses (vertical match, spam-tail floor, marketplace gate, build-order sort, cap),
        then subtract every directory already COVERED (matched by directory_id, else by
        normalized name so a legacy monitoring row with no directory_id still counts).

    The result's ``missing`` is exactly what "build only the missing ones" should queue,
    in build order (core -> tier1 -> tier2)."""
    gap = CitationGap(existing_count=len(existing_citations))

    covered_ids: set[str] = set()
    covered_names: set[str] = set()
    for row in existing_citations:
        submit = str(row.get("submit_status") or "not_started")
        nap = str(row.get("nap_status") or "unknown")
        gap.by_submit_status[submit] = gap.by_submit_status.get(submit, 0) + 1
        gap.by_nap_status[nap] = gap.by_nap_status.get(nap, 0) + 1
        proof = str(row.get("proof_url") or "")
        if submit in _LIVE_SUBMIT and proof:
            gap.live_urls.append(
                {"directory": str(row.get("directory") or ""), "url": proof, "status": submit}
            )
        if _row_covers(row):
            gap.covered_count += 1
            did = row.get("directory_id")
            if did:
                covered_ids.add(str(did))
            name = str(row.get("directory") or "")
            if name:
                covered_names.add(_norm_directory(name))

    candidates = automatable_directories(directories)
    selection = select_campaign_directories(
        candidates,
        vertical=vertical,
        cap=cap,
        min_authority=min_authority,
        include_marketplaces=include_marketplaces,
    )
    gap.missing = [
        d
        for d in selection.selected
        if str(d.get("id")) not in covered_ids
        and _norm_directory(str(d.get("name") or "")) not in covered_names
    ]
    return gap


def job_from_row(row: dict[str, Any]) -> CitationJob:
    """Build the engine-facing ``CitationJob`` from a joined citation+directory+
    business_profile row (see ``repo.load_citation_with_directory``)."""
    categories = row.get("bp_categories")
    return CitationJob(
        directory_name=str(row.get("directory_name") or row.get("directory") or ""),
        directory_url=str(row.get("directory_url") or ""),
        market=str(row.get("directory_market") or "US"),
        submit_method=str(row.get("submit_method") or ""),
        business_name=str(row.get("bp_business_name") or ""),
        address_line1=str(row.get("bp_address_line1") or ""),
        address_line2=str(row.get("bp_address_line2") or ""),
        city=str(row.get("bp_city") or ""),
        region=str(row.get("bp_region") or ""),
        postal_code=str(row.get("bp_postal_code") or ""),
        phone=str(row.get("bp_phone") or ""),
        website_url=str(row.get("bp_website_url") or ""),
        categories=tuple(categories) if isinstance(categories, list) else (),
        external_ref=str(row["external_ref"]) if row.get("external_ref") else None,
    )
