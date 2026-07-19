"""Citation-builder orchestration (7B-4): PURE reasoning over catalog rows + a
business profile - no DB, no network (mirrors ``local_seo.service`` /
``web2_pipeline``'s plan stage). The privileged reads/writes live in ``repo.py``;
the actual submit calls live in ``integrations.citation_*``; this layer only
decides WHICH directories a campaign queues, WHAT it will cost, and WHICH engine a
queued row's ``submit_method`` routes to.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.modules.citations.schemas import AUTOMATABLE_TIERS
from integrations.citation_submitters import CitationJob, CitationSubmitter


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
        return sub, ("" if sub is not None else f"no API submitter configured for {key!r}")
    if submit_method.startswith("aggregator:") or submit_method.startswith("bot:"):
        return bot, ("" if bot is not None else "Playwright bot not installed/configured")
    if submit_method == "apify":
        return apify, ("" if apify is not None else "Apify fallback not configured")
    return None, f"no automatable engine for submit_method={submit_method!r}"


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
