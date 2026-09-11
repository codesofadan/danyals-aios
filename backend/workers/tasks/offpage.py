"""Off-page workers (7B-3): the Web 2.0 publish pipeline drivers + the backlink /
citation MONITORING sweep.

Three Celery tasks, all built on the never-stuck / never-re-raise / idempotent worker
template (``workers.tasks.audit``) - with ``task_acks_late`` a raised exception would
redeliver the job and re-run a PAID stage (double spend), so every task acks and
returns a small result dict:

* ``web2_write_job``   - drive one planned property plan -> write -> ``needs_review``
  (the human quality gate). Never publishes.
* ``web2_publish_job`` - after a lead APPROVES, drive publish -> verify -> track.
* ``monitor_offpage_job`` - pull a client's live backlink profile + citation listings,
  DIFF new/lost vs the stored ledger, apply the changes, and call the ``notify_new_lost``
  alert SEAM for new/lost links.

The pipeline stages themselves live in ``app.services.web2_pipeline`` (pure of Celery +
network); this module WIRES the concrete privileged store, the cost gate, and the
key/OAuth-gated providers, then runs the pure orchestration. The monitoring DIFF is
also a pure function (``diff_backlinks`` / ``diff_citations``) so it is unit-tested
directly with the deterministic provider fakes - no DB, no network.

7F-1 DECOUPLING: the alert delivery (the notifications service) is built in a PARALLEL
chunk. ``notify_new_lost`` imports it LAZILY + GUARDED, so this worker has NO hard
dependency on 7F-1: if the notifications service is not importable yet it logs a no-op
and returns. When 7F-1 lands, the same seam starts delivering with no change here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings, get_settings
from app.core.security import is_public_url
from app.db.database import privileged_connection
from app.db.offpage_repo import ServiceOffpageStore, service_offpage_store
from app.logging_setup import get_logger
from app.schemas.offpage import action_for
from app.services import pricing, web2_gate
from app.services.content_generator import SourcePack
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from app.services.deliverables import emit_deliverable
from app.services.directory_names import canonical_norm
from app.services.vault import find_secret
from app.services.web2_linkcheck import check_link
from app.services.web2_pacing import PacingCaps, Placement
from app.services.web2_pipeline import (
    SimilarityOutcome,
    Web2Client,
    Web2Outcome,
    run_publish,
    run_write,
)
from app.services.web2_release import plan_release
from integrations.backlinks import BacklinkProvider, BacklinkRecord, backlink_provider_from_settings
from integrations.citations import CitationProvider, CitationRecord, citation_provider_from_settings
from integrations.content_providers import content_providers_from_settings
from integrations.web2_credentials import build_publisher
from integrations.web2_publishers import Web2Publisher

logger = get_logger("workers.offpage")

# Off-page monitoring pulls ride the 'backlinks' (off-page) money-dial; the provider
# labels are for the cost log only (not the frontend dial's Provider union).
_MONITOR_FEATURE = "backlinks"
# Citation discovery rides its OWN dial (2026-09-02). It used to share
# _MONITOR_FEATURE, so the byhand backlinks default silently blocked every citation
# audit — zero rows written behind a 202 (measured, 2026-09-01 23:30).
_CITATION_DISCOVERY_FEATURE = "citation_discovery"
_MONITOR_JOB_TYPE = "backlinks"

# The notify callback shape: (client_id, client_name, new_links, lost_rows).
NotifyFn = Callable[[str | None, str, list[BacklinkRecord], list[dict[str, Any]]], None]


class _NullCostCache:
    """A no-op ``CostCache`` for the worker's gate (these off-page pulls/publishes are
    not cache-keyed - a live monitoring pull must always hit the provider; the dial +
    budgets still gate it)."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


# --------------------------------------------------------------------------- #
# The notify / alert SEAM (7F-1 is parallel - lazy + guarded, never a hard dep).
# --------------------------------------------------------------------------- #
def notify_new_lost(
    client_id: str | None,
    client_name: str,
    new_links: list[BacklinkRecord],
    lost_links: list[dict[str, Any]],
) -> None:
    """Alert on new/lost backlinks. Best-effort: delivers via the notifications service
    when it is importable (7F-1), else logs a no-op. NEVER raises - a monitoring sweep
    must not fail because the alert channel is missing or hiccups."""
    if not new_links and not lost_links:
        return
    try:
        # 7F-1 (parallel): the concrete alert delivery. Import lazily + guarded so this
        # worker builds + runs with NO hard dependency on that chunk.
        from app.services.notifications import notify_offpage_changes
    except Exception:
        logger.info(
            "offpage_notify_noop", client=client_name,
            new=len(new_links), lost=len(lost_links),
        )
        return
    try:
        notify_offpage_changes(
            client_id=client_id, client_name=client_name,
            new_links=new_links, lost_links=lost_links,
        )
    except Exception:
        logger.warning("offpage_notify_failed", client=client_name)


# --------------------------------------------------------------------------- #
# Pure monitoring DIFFs (unit-tested directly with the provider fakes).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BacklinkDiff:
    """The monitoring delta: ``new`` records to insert + stored ``lost`` rows to mark."""

    new: list[BacklinkRecord] = field(default_factory=list)
    lost: list[dict[str, Any]] = field(default_factory=list)


def diff_backlinks(
    fetched: list[BacklinkRecord], stored: list[dict[str, Any]]
) -> BacklinkDiff:
    """Diff a freshly-pulled profile against the stored ledger, keyed by referring
    domain. NEW = a live (non-lost) domain not yet stored. LOST = a stored, not-already-
    lost domain that is gone from the pull OR the provider now reports it dropped. Pure
    + deterministic; a domain seen twice keeps its first occurrence."""
    stored_by_domain: dict[str, dict[str, Any]] = {}
    for row in stored:
        dom = str(row.get("ref_domain") or "").lower()
        if dom:
            stored_by_domain.setdefault(dom, row)
    fetched_by_domain: dict[str, BacklinkRecord] = {}
    for rec in fetched:
        dom = rec.ref_domain.lower()
        if dom:
            fetched_by_domain.setdefault(dom, rec)

    new = [
        rec for dom, rec in fetched_by_domain.items()
        if dom not in stored_by_domain and not rec.lost
    ]
    lost: list[dict[str, Any]] = []
    for dom, row in stored_by_domain.items():
        if str(row.get("status") or "") == "lost":
            continue  # already recorded lost
        hit = fetched_by_domain.get(dom)
        if hit is None or hit.lost:
            lost.append(row)
    return BacklinkDiff(new=new, lost=lost)


@dataclass(frozen=True)
class CitationDiff:
    """The citation delta: ``new`` directories to insert + stored rows whose NAP state
    ``changed`` (paired with the fresh record)."""

    new: list[CitationRecord] = field(default_factory=list)
    changed: list[tuple[dict[str, Any], CitationRecord]] = field(default_factory=list)


def diff_citations(
    fetched: list[CitationRecord], stored: list[dict[str, Any]]
) -> CitationDiff:
    """Diff pulled directory listings against the stored ledger, keyed by directory.
    NEW = a directory not yet stored. CHANGED = a stored directory whose NAP state now
    differs - OR whose EVIDENCE moved (0129: a fresh pull that found the URL or a
    stronger/weaker tier must update the row even when the NAP verdict is unchanged,
    or the evidence columns would freeze at their first write). Pure + deterministic."""
    stored_by_dir: dict[str, dict[str, Any]] = {}
    for row in stored:
        key = str(row.get("directory") or "").lower()
        if key:
            stored_by_dir.setdefault(key, row)
    new: list[CitationRecord] = []
    changed: list[tuple[dict[str, Any], CitationRecord]] = []
    for rec in fetched:
        existing = stored_by_dir.get(rec.directory.lower())
        if existing is None:
            new.append(rec)
            continue
        nap_moved = str(existing.get("nap_status") or "") != rec.nap_status
        evidence_moved = bool(rec.evidence_level) and (
            str(existing.get("evidence_level") or "") != rec.evidence_level
        )
        url_moved = bool(rec.url) and str(existing.get("discovered_url") or "") != rec.url
        if nap_moved or evidence_moved or url_moved:
            changed.append((existing, rec))
    return CitationDiff(new=new, changed=changed)


def _discovery_evidence(rec: CitationRecord, checked_at: datetime) -> dict[str, Any]:
    """The persisted ``discovery_evidence`` jsonb (0129): the record's own receipt
    ({sources, queries, snippet, nap, classifier}) plus a SERVER-SIDE ``checked_at``
    stamped at write time. A record with no evidence at all yields ``{}`` (the column
    default) rather than a lone timestamp claiming evidence that does not exist."""
    if not rec.evidence and not rec.evidence_level:
        return {}
    evidence: dict[str, Any] = dict(rec.evidence)
    evidence["checked_at"] = checked_at.isoformat()
    return evidence


# --------------------------------------------------------------------------- #
# Monitoring orchestration (cost-gated; never raises).
# --------------------------------------------------------------------------- #
def run_backlink_monitor(
    store: ServiceOffpageStore,
    provider: BacklinkProvider,
    gate: CostGate,
    settings: Settings,
    *,
    client_id: str,
    client_name: str,
    domain: str,
    notify: NotifyFn = notify_new_lost,
    limit: int = 100,
) -> dict[str, Any]:
    """Pull ``domain``'s live profile, diff vs the ledger, apply new/lost, and alert.

    R5: cost pre-check on the 'backlinks' dial BEFORE the paid pull - a block skips the
    pull (no spend). Never raises: a provider failure returns an ``error`` result."""
    ctx = GateContext(
        feature_key=_MONITOR_FEATURE, client_id=client_id, provider="DataForSEO",
        estimated_cost=float(settings.offpage_monitor_cost_estimate), job_id=domain,
        job_type=_MONITOR_JOB_TYPE, client_name=client_name,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("backlink_monitor_blocked", domain=domain, outcome=decision.outcome)
        return {"state": "blocked", "reason": decision.outcome, "new": 0, "lost": 0}
    try:
        fetched = provider.fetch_backlinks(domain, limit=limit)
    except Exception:
        logger.exception("backlink_monitor_pull_failed", domain=domain)
        return {"state": "error", "reason": "provider pull failed", "new": 0, "lost": 0}
    # ACTUAL cost = one DataForSEO backlink pull x the per-call unit price (pricing.py).
    gate.commit(ctx, pricing.dataforseo_cost(settings, calls=1))

    stored = store.list_backlinks_for_client(client_id)
    diff = diff_backlinks(fetched, stored)
    for rec in diff.new:
        store.insert_backlink(
            client_id=client_id, client_name=client_name, ref_domain=rec.ref_domain,
            anchor=rec.anchor, authority=rec.authority, spam=rec.spam,
            first_seen=rec.first_seen, status=rec.status,
            # 0133: the verification coordinates. Persisted at ingest so the verify
            # sweep can fetch the referring page itself; discovery never sets liveness.
            source_url=rec.source_url, target_url=rec.target_url,
        )
    for row in diff.lost:
        store.set_backlink_status(str(row["id"]), "lost")
    if diff.new or diff.lost:
        notify(client_id, client_name, diff.new, diff.lost)
        # Publish a refreshed Backlink-Profile deliverable when the profile actually
        # changed (best-effort; the emit never raises).
        emit_deliverable(
            client_id=client_id,
            client_name=client_name,
            title="Backlink Profile",
            kind="Backlinks",
            requires="backlinks",
            source_kind="offpage",
            source_id=None,
            icon="hub",
        )
    logger.info(
        "backlink_monitor_done", domain=domain, new=len(diff.new), lost=len(diff.lost)
    )
    return {
        "state": "ok", "new": len(diff.new), "lost": len(diff.lost),
        "notified": bool(diff.new or diff.lost),
    }


def run_citation_monitor(
    store: ServiceOffpageStore,
    provider: CitationProvider,
    gate: CostGate,
    settings: Settings,
    *,
    client_id: str,
    client_name: str,
    business: str,
    limit: int = 50,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Pull ``business``'s directory listings, diff vs the ledger, and apply new/changed
    rows (NAP state drives the Submit/Update action). Cost-gated + never-raises like the
    backlink monitor."""
    ctx = GateContext(
        feature_key=_CITATION_DISCOVERY_FEATURE, client_id=client_id, provider="BrightLocal",
        estimated_cost=float(settings.offpage_monitor_cost_estimate), job_id=business,
        job_type=_MONITOR_JOB_TYPE, client_name=client_name,
    )
    say = progress or (lambda _msg: None)
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("citation_monitor_blocked", business=business, outcome=decision.outcome)
        return {"state": "blocked", "reason": decision.outcome, "new": 0, "changed": 0}
    try:
        say(f"searching for listings of {business}")
        fetched = provider.fetch_citations(business, limit=limit)
    except Exception:
        logger.exception("citation_monitor_pull_failed", business=business)
        return {"state": "error", "reason": "provider pull failed", "new": 0, "changed": 0}
    # One BrightLocal monitoring pull. BrightLocal is a subscription with no per-call
    # meter, so the committed cost is the per-pull unit price itself (1 pull performed)
    # -- a real unit of work, not a flat per-call guess of a token/query count.
    # The search-discovery provider's whole bundle (Serper + Places + Foursquare +
    # optional Firecrawl + the optional DataForSEO Business Listings corroboration
    # call, 0129) rides this SAME single per-pull estimate on the citation_discovery
    # dial: there is no per-source metering inside the provider, so one more gated
    # call inside the already-gated pull folds into the one commit rather than
    # inventing a second meter.
    gate.commit(ctx, float(settings.offpage_monitor_cost_estimate))

    stored = store.list_citations_for_client(client_id)
    diff = diff_citations(fetched, stored)
    say(f"found {len(fetched)} listings; recording {len(diff.new)} new, {len(diff.changed)} changed")
    # Resolve each discovered listing to its CATALOG ROW before writing it. Discovery
    # names a listing from its domain and the catalog names it as a product, so a row
    # written with a name alone matched nothing later and the client was told to build
    # a listing they already had. Looked up once for the whole batch; a name with no
    # unambiguous catalog row is written with a NULL id and still matches by name.
    try:
        catalog = store.directory_ids_by_name()
    except Exception:
        logger.warning("citation_directory_lookup_failed", business=business)
        catalog = {}
    # ONE server-side timestamp for the whole batch (0129): `checked_at` inside the
    # evidence receipt and the `evidence_checked_at` column are stamped HERE at write
    # time, never trusted from a provider record.
    checked_at = datetime.now(UTC)
    for rec in diff.new:
        store.insert_citation(
            client_id=client_id, client_name=client_name, directory=rec.directory,
            nap_status=rec.nap_status, action=action_for(rec.nap_status), note=rec.note,
            directory_id=catalog.get(canonical_norm(rec.directory)),
            discovered_url=rec.url,
            discovery_evidence=_discovery_evidence(rec, checked_at),
            evidence_level=rec.evidence_level,
            evidence_checked_at=checked_at if rec.evidence_level else None,
        )
    for existing, rec in diff.changed:
        store.update_citation_status(
            str(existing["id"]), nap_status=rec.nap_status,
            action=action_for(rec.nap_status), note=rec.note,
            # Evidence fields ride the same update (0129) - but ONLY when this pull
            # actually produced them, so a tier-less provider record can never blank
            # what an earlier discovery recorded.
            discovered_url=rec.url or None,
            discovery_evidence=(
                _discovery_evidence(rec, checked_at) if rec.evidence_level else None
            ),
            evidence_level=rec.evidence_level or None,
            evidence_checked_at=checked_at if rec.evidence_level else None,
        )
    logger.info(
        "citation_monitor_done", business=business,
        new=len(diff.new), changed=len(diff.changed),
    )
    return {"state": "ok", "new": len(diff.new), "changed": len(diff.changed)}


# --------------------------------------------------------------------------- #
# Verification sweeps (0133): backlink liveness + Web 2.0 link recheck.
# Free by construction - plain HTTP GETs against pages we already know about, no
# provider call - so neither goes through the money dial. Both reuse
# `web2_linkcheck.check_link` verbatim: one definition of "our link is on that
# page" for publish-time verification, backlinks and the recheck alike.
# --------------------------------------------------------------------------- #

#: A verified-live link is re-confirmed monthly; a missing one is looked at again in
#: a week so the LOSS is confirmed by a second, separated observation before the
#: monitoring status may flip to `lost`. `unknown` retries soon - nothing was
#: learned, so it must not consume a month of not-looking.
_LIVE_RECHECK_DAYS = 30
_MISSING_CONFIRM_DAYS = 7
_UNKNOWN_RETRY_DAYS = 1

#: HTTP answers that are evidence the PAGE ITSELF is gone (vs "we could not look").
_GONE_STATUSES = frozenset({404, 410})


class EvidenceFetcher:
    """SSRF-guarded page fetcher for the verification sweeps. Never raises.

    Mirrors ``_fetch_page``'s honest User-Agent (no browser impersonation beyond the
    compat prefix, and the AIOS name is right there), but hardens the redirect path
    per ``app/core/security.py``'s caller contract: redirects are followed MANUALLY
    with every hop re-validated through ``is_public_url``, so a public page cannot
    30x this worker into the metadata service. The terminal HTTP status is kept on
    ``self.status`` so the verdict's evidence can say what the server answered -
    ``check_link``'s fetcher seam only carries HTML, and an evidence receipt that
    cannot name the status would make 404 and timeout indistinguishable.
    """

    user_agent = "Mozilla/5.0 (compatible; AIOS-linkcheck/1.0)"

    def __init__(self, *, timeout: float = 15.0, max_redirects: int = 5) -> None:
        self._timeout = timeout
        self._max_redirects = max_redirects
        self.status: int | None = None
        self.detail: str = ""

    def __call__(self, url: str) -> str | None:
        import httpx

        current = url
        for _hop in range(self._max_redirects + 1):
            # Re-validated EVERY hop, not just once: the redirect target is as
            # attacker-controllable as the first URL (TOCTOU / rebinding contract).
            if not is_public_url(current):
                self.detail = "refused: non-public URL"
                return None
            try:
                with httpx.Client(
                    timeout=self._timeout,
                    follow_redirects=False,
                    headers={"User-Agent": self.user_agent},
                ) as client:
                    resp = client.get(current)
            except Exception as exc:
                self.detail = f"fetch failed: {type(exc).__name__}"
                return None
            self.status = resp.status_code
            location = resp.headers.get("location", "")
            if resp.status_code in (301, 302, 303, 307, 308) and location:
                current = str(httpx.URL(current).join(location))
                continue
            if resp.status_code >= 400:
                self.detail = f"http {resp.status_code}"
                return None
            return resp.text
        self.detail = "too many redirects"
        return None


def _check_evidence(check: Any, fetcher: EvidenceFetcher, checked_at: datetime) -> dict[str, Any]:
    """The persisted receipt for one verification look: what the server answered,
    what the checker concluded, and when - stamped server-side, like 0129's."""
    detail = str(check.detail or "")
    if fetcher.detail and fetcher.detail not in detail:
        detail = f"{detail} ({fetcher.detail})" if detail else fetcher.detail
    return {"http_status": fetcher.status, "detail": detail, "checked_at": checked_at.isoformat()}


def execute_verify_backlinks(
    store: ServiceOffpageStore,
    *,
    limit: int = 25,
    fetcher_factory: Callable[[], EvidenceFetcher] | None = None,
    notify: NotifyFn = notify_new_lost,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify the due backlinks by fetching each referring page ourselves.

    WHY. `backlinks.status` is a PROVIDER's claim from the last paid pull; nothing
    ever looked at the page. This sweep is the platform's own observation: fetch
    `source_url`, look for `target_url` with the same `check_link` the Web 2.0
    pipeline trusts, and record what was actually seen. Three verdicts on purpose -
    `live` / `missing` / `unknown` - because "could not check" shown as either of the
    others silently converts an outage into a false accusation or a false pass.

    LOSS IS CONFIRMED, NEVER INFERRED FROM ONE LOOK: the first `missing` only
    schedules a +7d re-look; a row missing TWICE flips its monitoring status to
    `lost` (only from `new` - a `toxic` link stays in the disavow queue whether or
    not it is still up) and fires the same `notify_new_lost` seam the monitor uses.

    Never raises: one unreachable page must not cost the other rows their check, and
    a redelivered job would just re-claim whatever is still due (the claim's lease +
    idempotent verdict writes make that harmless).
    """
    moment = now or datetime.now(UTC)
    try:
        rows = store.claim_due_backlink_checks(limit=limit)
    except Exception:
        logger.exception("backlink_verify_load_failed")
        return {"state": "error", "checked": 0, "outcomes": {}, "lost_confirmed": 0}

    make_fetcher = fetcher_factory or EvidenceFetcher
    checked = 0
    lost_confirmed = 0
    outcomes: dict[str, int] = {}
    for row in rows:
        backlink_id = str(row.get("id"))
        try:
            fetcher = make_fetcher()
            check = check_link(
                str(row.get("source_url") or ""), str(row.get("target_url") or ""), fetcher
            )
            liveness = {"found": "live", "missing": "missing"}.get(check.state, "unknown")
            if liveness == "unknown" and fetcher.status in _GONE_STATUSES:
                # The referring page itself answered 404/410. That IS an observation
                # about the backlink - the page (and the link on it) is gone - not a
                # failed look, and it is the COMMONEST loss mode: without this the
                # two-observation `lost` ladder could never start for a deleted page
                # (the web2 recheck below makes the same upgrade).
                liveness = "missing"
            checked += 1
            outcomes[liveness] = outcomes.get(liveness, 0) + 1

            confirm_lost = liveness == "missing" and str(row.get("liveness") or "") == "missing"
            # Only a `new` link demotes to `lost`; `toxic` outranks lost (the disavow
            # queue must keep it) and an already-`lost` row has nothing to flip.
            mark_lost = confirm_lost and str(row.get("status") or "") == "new"
            days = (
                _LIVE_RECHECK_DAYS if liveness == "live"
                else _MISSING_CONFIRM_DAYS if liveness == "missing"
                else _UNKNOWN_RETRY_DAYS
            )
            store.record_backlink_check(
                backlink_id,
                liveness=liveness,
                link_rel=check.rel,
                check_evidence=_check_evidence(check, fetcher, moment),
                checked_at=moment,
                next_check_at=moment + timedelta(days=days),
                mark_lost=mark_lost,
            )
            if mark_lost:
                lost_confirmed += 1
                client_id = str(row["client_id"]) if row.get("client_id") else None
                notify(client_id, str(row.get("client_name") or ""), [], [dict(row)])
        except Exception:
            logger.exception("backlink_verify_row_failed", backlink_id=backlink_id)

    logger.info(
        "backlink_verify_done", checked=checked, lost_confirmed=lost_confirmed, **outcomes
    )
    return {
        "state": "ok", "checked": checked, "outcomes": outcomes,
        "lost_confirmed": lost_confirmed,
    }


def _notify_web2_link_lost(
    client_id: str | None, client_name: str, platform: str, post_url: str
) -> None:
    """Alert that a published Web 2.0 property no longer carries its link.

    The same seam shape as ``notify_new_lost``: a LOST placed link is the actionable
    negative signal, so it rides the existing ``lost_link`` alert taxonomy - lazily +
    guarded, best-effort, never raises. The log line fires regardless, so even with
    no client id (a legacy row) the demotion is never silent."""
    logger.warning(
        "web2_link_lost", client=client_name, platform=platform, post_url=post_url
    )
    if not client_id:
        return
    try:
        import asyncio

        from app.services.notifications import raise_alert
    except Exception:
        return
    detail = (
        f"the {platform} placement for {client_name} no longer carries its link "
        f"({post_url})"
    ).strip()
    try:
        asyncio.run(raise_alert(client_id, "lost_link", "warning", detail))
    except Exception:
        logger.warning("web2_link_lost_alert_failed", client=client_name)


def execute_web2_link_recheck(
    store: ServiceOffpageStore,
    *,
    limit: int = 50,
    fetcher_factory: Callable[[], EvidenceFetcher] | None = None,
    now: datetime | None = None,
    alert: Callable[[str | None, str, str, str], None] = _notify_web2_link_lost,
) -> dict[str, Any]:
    """Re-measure the placed link on published Web 2.0 properties.

    `published` was checked ONCE, at publish time; platforms delete posts, strip
    links and add rel=nofollow afterwards, and none of that notifies us. Sweeping
    least-recently-checked-first keeps every property inside a bounded staleness
    window without a per-row schedule.

    HONESTY RULES. A page that answers 404/410 is EVIDENCE (the post is gone), so it
    demotes like a stripped link; any other failed look stays `unknown` and touches
    only `link_checked_at` - `link_found` keeps its last real observation, because
    downgrading it on our own network blip would invent a client-facing defect. A
    demotion (link_found -> false) always emits the alert seam ON THE TRANSITION, so
    a lost link is reported once rather than re-alarmed every day it stays lost -
    and never silently shown green. Never raises."""
    moment = now or datetime.now(UTC)
    try:
        rows = store.list_published_web2_for_recheck(limit=limit)
    except Exception:
        logger.exception("web2_link_recheck_load_failed")
        return {"state": "error", "checked": 0, "outcomes": {}, "demoted": 0}

    make_fetcher = fetcher_factory or EvidenceFetcher
    checked = 0
    demoted = 0
    outcomes: dict[str, int] = {}
    for row in rows:
        web2_id = str(row.get("id"))
        try:
            fetcher = make_fetcher()
            check = check_link(
                str(row.get("post_url") or ""), str(row.get("target_url") or ""), fetcher
            )
            state = check.state
            if state == "unknown" and fetcher.status in _GONE_STATUSES:
                # The page itself is gone. That IS an observation about the placement
                # - the post was deleted - not a failed look.
                state = "missing"
            checked += 1
            outcomes[state] = outcomes.get(state, 0) + 1

            if state == "found":
                store.update_web2(
                    web2_id,
                    {"link_found": True, "link_rel": check.rel, "link_checked_at": moment},
                )
            elif state == "missing":
                previously_found = row.get("link_found")
                store.update_web2(
                    web2_id,
                    {"link_found": False, "link_rel": check.rel, "link_checked_at": moment},
                )
                if previously_found is not False:
                    demoted += 1
                    client_id = str(row["client_id"]) if row.get("client_id") else None
                    alert(
                        client_id, str(row.get("client_name") or ""),
                        str(row.get("platform") or ""), str(row.get("post_url") or ""),
                    )
            else:
                # Could not look: record THAT we tried, change no verdict column.
                store.update_web2(web2_id, {"link_checked_at": moment})
        except Exception:
            logger.exception("web2_link_recheck_row_failed", web2_id=web2_id)

    logger.info("web2_link_recheck_done", checked=checked, demoted=demoted, **outcomes)
    return {"state": "ok", "checked": checked, "outcomes": outcomes, "demoted": demoted}


# --------------------------------------------------------------------------- #
# Provider + client wiring (key/OAuth-gated; degraded -> None).
# --------------------------------------------------------------------------- #
def _writer_for(settings: Settings) -> tuple[Any | None, str]:
    """The content writer + its model tier, or ``(None, ...)`` degraded (no key)."""
    providers = content_providers_from_settings(settings)
    if providers is None:
        return None, "content-writer"
    return providers.writer, providers.model_writer


def _wr_str_list(value: Any) -> list[str]:
    """Trimmed, blank-dropped string list from a jsonb value (else empty)."""
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _source_pack_from_web2_row(row: dict[str, Any]) -> SourcePack:
    """Build the writer's grounding pack from the placement's ``source_pack`` jsonb
    (seeded at plan time with the operator's first-hand proof). Empty -> just the
    client name, so the generator emits ``[NEEDS:]`` gaps (never a hallucination)
    that HOLD at review - exactly the pre-grounding behaviour."""
    raw = row.get("source_pack")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    facts_raw = raw.get("facts")
    facts = (
        {str(k): str(v) for k, v in facts_raw.items()} if isinstance(facts_raw, dict) else {}
    )
    return SourcePack(
        client_name=str(raw.get("client_name") or row.get("client_name") or "our team"),
        facts=facts,
        services=_wr_str_list(raw.get("services")),
        proof_points=_wr_str_list(raw.get("proof_points")),
        unique_data=_wr_str_list(raw.get("unique_data")),
        testimonials=_wr_str_list(raw.get("testimonials")),
    )


def _client_from_row(row: dict[str, Any]) -> Web2Client:
    """The grounding client for a placement: display name + tenant id + the first-hand
    ``source_pack`` seeded at plan time. With an empty pack the generator degrades
    ungrounded facts to ``[NEEDS:]`` gaps that HOLD at review."""
    client_id = row.get("client_id")
    # `client_geo` is joined in by ServiceOffpageStore.load_web2 from the client's
    # business profile. It is load-bearing twice over: the writer uses it to ground a
    # local article, and the similarity gate masks it before shingling (an unmasked city
    # token is what lets two templated articles score as distinct). Absent profile -> ''.
    geo = str(row.get("client_geo") or "").strip()
    return Web2Client(
        client_id=str(client_id) if client_id else None,
        name=str(row.get("client_name") or ""),
        source_pack=_source_pack_from_web2_row(row),
        geo=geo or None,
    )


# --------------------------------------------------------------------------- #
# Pure entry points (wire concrete deps + run the never-raising orchestration).
# --------------------------------------------------------------------------- #
def execute_web2_write(store: ServiceOffpageStore, settings: Settings, web2_id: str) -> Web2Outcome:
    """Draft one planned property to the review gate (wires the writer + gate)."""
    row = store.load_web2(web2_id)
    client = _client_from_row(row) if row else Web2Client(client_id=None, name="")
    writer, model = _writer_for(settings)
    # THE OPERATOR'S IMAGE KILL-SWITCH REACHES THIS PATH TOO. web2 used the generator's
    # DEFAULT_TUNING, whose max_images is 5, so every article paid for a photo-brief
    # writer call - and the result was then discarded: `builder.images` never enters
    # `builder.parts`, is absent from `Web2Article`, and no web2 publisher renders an
    # image. So it was spend with no output, on a setting the operator believed was off.
    # Imported from the content worker rather than re-derived, so the two cannot disagree
    # about what `content_images_enabled` means.
    from workers.tasks.content import _tuning as _image_tuning

    return run_write(
        store, web2_id, client=client, writer=writer, gate=_gate(), settings=settings,
        model=model, tuning=_image_tuning(settings),
        similarity=_similarity_checker(store, settings),
    )


def _similarity_checker(
    store: ServiceOffpageStore, settings: Settings
) -> Callable[..., SimilarityOutcome]:
    """The DB-backed similarity gate the pure pipeline calls at draft time.

    A thin adapter over :mod:`app.services.web2_gate`, which the approval endpoint also
    uses - the two callers MUST score identically, so the logic lives in one place.
    """

    def check(
        *, web2_id: str, row: dict[str, Any], body_md: str, client: Web2Client
    ) -> SimilarityOutcome:
        return web2_gate.evaluate_draft(
            store, settings, web2_id=web2_id, row=row, body_md=body_md,
            client_name=client.name, geo=client.geo or "",
        )

    return check


def execute_web2_publish(store: ServiceOffpageStore, settings: Settings, web2_id: str) -> Web2Outcome:
    """Publish an APPROVED property (wires the vault-backed, per-client publisher +
    gate). ``_publisher_for`` degrades to ``None`` on ANY failure (missing row,
    store error, missing/malformed vault credential) - never raises, so it can never
    bypass ``run_publish``'s own never-raise guarantee below."""
    publisher = _publisher_for(store, web2_id)
    outcome = run_publish(
        store, web2_id, publisher=publisher, gate=_gate(), settings=settings,
        fetch_page=_fetch_page,
    )
    if outcome.state == "published":
        _record_fingerprint(store, web2_id)
    return outcome


def _fetch_page(url: str) -> str | None:
    """Fetch a published page so the pipeline can confirm our link is really on it.

    Deliberately tolerant and non-raising: a verification failure must never fail the
    publish it is verifying, and "could not read the page" has to stay distinguishable
    from "the link was not there" - so every failure returns None, which the checker
    records as `unknown` rather than `missing`.

    A browser-ish User-Agent because several of these platforms serve a bot-blocking
    interstitial to a bare client, which would otherwise read as a stripped link.
    """
    import httpx

    try:
        with httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIOS-linkcheck/1.0)"},
        ) as client:
            resp = client.get(url)
        if resp.status_code >= 400:
            logger.info("web2_linkcheck_http_error", url=url, status=resp.status_code)
            return None
        return resp.text
    except Exception:
        logger.info("web2_linkcheck_unreachable", url=url)
        return None


def _record_fingerprint(store: ServiceOffpageStore, web2_id: str) -> None:
    """Enter a LIVE property into the similarity corpus. Best-effort by design.

    Recorded here rather than at approval because this is the first moment the article
    is actually public - a property that was approved but whose publish then failed is
    not out there, and seeding the corpus with it would block a later, better draft of
    the same placement for no reason.

    NEVER raises: the article is already live, so failing the job now would redeliver it
    (``acks_late``) and attempt a SECOND publish of the same post. A missing fingerprint
    degrades the gate's recall by exactly one document and is logged; a double publish is
    a real duplicate on a client's property.
    """
    try:
        row = store.load_web2(web2_id)
        if row is None:
            return
        body_md = str(row.get("body_md") or "")
        if not body_md.strip():
            return
        web2_gate.record_fingerprint(
            store, web2_id=web2_id, row=row, body_md=body_md,
            client_name=str(row.get("client_name") or ""),
            geo=str(row.get("client_geo") or ""),
            status_at_capture="published",
        )
    except Exception:
        logger.warning("web2_fingerprint_not_recorded", web2_id=web2_id)


def _publisher_for(store: ServiceOffpageStore, web2_id: str) -> Web2Publisher | None:
    """Best-effort vault lookup for the row's publishing account. Any failure here (a
    store error, a missing row, no vault credential yet, Medium/an unrecognised
    platform) degrades to ``None`` - ``run_publish`` then HOLDS the placement at
    ``needs_review`` exactly as if the platform were unconfigured.

    The vault label is the property's ``account_id`` where it has one. A property
    created before ``web2_accounts`` (0100/0101) has none until the reconciliation
    (``app/cli/web2_migrate_house.py``) attributes it, so it falls back to the legacy
    client-id label - otherwise every pre-existing placement would lose its credential
    the moment accounts shipped. The fallback is logged so the remaining un-migrated
    rows are visible rather than silently permanent."""
    try:
        row = store.load_web2(web2_id)
        if row is None:
            return None
        platform = str(row.get("platform") or "")
        if not platform:
            return None
        account_id = str(row.get("account_id") or "")
        vault_label = ""
        if account_id:
            # Read the label OFF THE ACCOUNT, never infer it from the id: a migrated house
            # account keeps its legacy client-id label on purpose, so assuming
            # label == account_id misses a credential that is really there.
            account = store.web2_account_vault(account_id)
            if account is None:
                logger.warning(
                    "web2_publisher_account_missing", web2_id=web2_id, account_id=account_id
                )
                return None
            if str(account.get("health") or "") in {"suspended", "deleted"}:
                logger.warning(
                    "web2_publisher_account_unusable", web2_id=web2_id,
                    account_id=account_id, health=str(account.get("health") or ""),
                )
                return None
            vault_label = str(account.get("vault_label") or "") or account_id
        if not vault_label:
            vault_label = str(row.get("client_id") or "")
            if not vault_label:
                return None
            logger.info("web2_publisher_legacy_client_label", web2_id=web2_id, platform=platform)
        # OAuth platforms route through the refresh service (Phase 5): the vault holds
        # a {access_token, refresh_token, expires_at} BUNDLE (or a legacy single
        # string), and the publisher needs a CURRENT access token - sealing-time
        # tokens expire within the hour, which is exactly the live Blogger 401. A
        # failed refresh returns None here, so the publish HOLDS at needs_review
        # (honest degradation) while the refresh service degrades the account's
        # health and alerts. Lazy import per the worker template.
        from app.services.web2_token_refresh import OAUTH_BUNDLE_PLATFORMS, refreshing_lookup

        lookup = find_secret
        if platform in OAUTH_BUNDLE_PLATFORMS:
            lookup = refreshing_lookup(platform=platform, account_id=account_id)
        return build_publisher(vault_label=vault_label, platform=platform, lookup=lookup)
    except Exception:
        logger.warning("web2_publisher_lookup_failed", web2_id=web2_id)
        return None


def execute_monitor(
    store: ServiceOffpageStore,
    settings: Settings,
    *,
    client_id: str,
    domain: str,
    business: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the backlink + citation monitoring sweep for one client (wires the key-gated
    providers). A degraded (keyless) provider is SKIPPED, never a crash.

    ``progress`` reports the current stage in one human line. Optional so the pure core
    stays callable without a job context (and Celery-free)."""
    say = progress or (lambda _msg: None)
    gate = _gate()
    stored_name = ""
    row_source = store.list_backlinks_for_client(client_id)
    if row_source:
        stored_name = str(row_source[0].get("client_name") or "")

    result: dict[str, Any] = {"client_id": client_id}
    say("checking the backlink profile")
    backlinks = backlink_provider_from_settings(settings)
    if backlinks is None:
        logger.info("backlink_monitor_degraded", client_id=client_id, reason="no_provider")
        result["backlinks"] = {"state": "degraded", "reason": "provider unconfigured"}
    else:
        result["backlinks"] = run_backlink_monitor(
            store, backlinks, gate, settings,
            client_id=client_id, client_name=stored_name, domain=domain,
        )

    say("checking directory listings")
    citations = citation_provider_from_settings(settings)
    if citations is None or not business:
        logger.info("citation_monitor_degraded", client_id=client_id)
        result["citations"] = {"state": "degraded", "reason": "provider unconfigured or no business"}
    else:
        result["citations"] = run_citation_monitor(
            store, citations, gate, settings,
            client_id=client_id, client_name=stored_name, business=business,
            progress=say,
        )
    return result


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app lazily-free at module load).
# --------------------------------------------------------------------------- #
from app.jobs import JobOutcome, JobQueue, JobTarget  # noqa: E402
from app.jobs.celery_task import aios_job  # noqa: E402
from app.jobs.contract import JobContext  # noqa: E402
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


def _mailbox_for_client(row: dict[str, Any]) -> Any:
    """The CLIENT's own mailbox, built from their stored identity (0122).

    Never the agency catch-all: reading a client's confirmation mail out of a shared
    inbox is the same shared-registrant-domain footprint the per-client identity exists
    to remove. No stored mailbox simply means no automatic verification - the operator
    clicks the link themselves and nothing breaks.
    """
    host = str(row.get("web2_imap_host") or "")
    user = str(row.get("web2_imap_user") or "")
    label = str(row.get("web2_imap_vault_label") or "")
    provider = str(row.get("web2_imap_vault_provider") or "")
    if not (host and user and label and provider):
        return None
    from app.services.vault import find_secret
    from integrations.imap_mailbox import ImapMailbox

    password = find_secret(provider=provider, label=label)
    if not password:
        return None
    return ImapMailbox(
        host=host, port=int(row.get("web2_imap_port") or 993), user=user, password=password
    )


def execute_web2_provision_tick(limit: int = 25) -> dict[str, Any]:
    """Advance every provisioning item that can move without a human.

    Reads and writes on the privileged pool: this sweeps ACROSS clients, which no
    tenant-scoped connection may do, and it writes only the queue's own columns.
    """
    from datetime import UTC, datetime, timedelta

    from app.services.web2_account_registration import (
        AccountRegistrationError,
        register_account,
    )
    from app.services.web2_provision_tick import TickReport, decide_auto_signup, decide_verification

    checked = advanced = failed = 0
    with privileged_connection() as cur:
        cur.execute(
            "select i.id, i.client_id, i.platform, i.status, i.lane, i.handle, "
            "       i.registration_email, i.created_at, "
            "       c.web2_imap_host, c.web2_imap_port, c.web2_imap_user, "
            "       c.web2_imap_vault_provider, c.web2_imap_vault_label "
            "from public.web2_provision_items i "
            "join public.clients c on c.id = i.client_id "
            "where i.status in ('identity_ready', 'awaiting_verification') "
            "order by i.created_at limit %s",
            (limit,),
        )
        items = list(cur.fetchall())

    for item in items:
        checked += 1
        status_now = str(item.get("status") or "")
        action = None
        try:
            if status_now == "identity_ready":
                action = decide_auto_signup(item, signup=_run_api_signup)
            elif status_now == "awaiting_verification":
                mailbox = _mailbox_for_client(item)
                if mailbox is None:
                    continue  # no mailbox: the operator confirms by hand, which is fine
                created = item.get("created_at")
                since = created if isinstance(created, datetime) else datetime.now(UTC)
                def _check(alias: str, when: datetime, _mb: Any = mailbox) -> tuple[bool, str]:
                    return _check_mail(_mb, alias, when)

                action = decide_verification(
                    item, since=since - timedelta(hours=1), check=_check
                )
        except Exception as exc:  # a bad item must never stop the sweep
            failed += 1
            logger.warning(
                "web2_provision_tick_item_failed",
                platform=str(item.get("platform") or ""), error=type(exc).__name__,
            )
            continue
        if action is None:
            continue

        note = action.note
        account_id: str | None = None
        if action.to_status == "live":
            try:
                account_id = register_account(
                    platform=action.platform,
                    client_id=str(item.get("client_id") or ""),
                    handle=action.handle or str(item.get("handle") or ""),
                    registration_email=str(item.get("registration_email") or ""),
                    credential=action.credential,
                )
            except AccountRegistrationError as refused:
                failed += 1
                _write_tick_result(
                    action.item_id, status="blocked", note=str(refused)[:400],
                    verify_link="", account_id=None,
                )
                continue
        _write_tick_result(
            action.item_id, status=action.to_status, note=note[:400],
            verify_link=action.verify_link, account_id=account_id,
        )
        advanced += 1

    return TickReport(checked=checked, advanced=advanced, failed=failed).as_dict()


def _run_api_signup(platform: str, handle: str) -> tuple[str, dict[str, str], str]:
    """Drive the platform's own signup API. Returns (status, credentials, error).

    The HTTP seam is ``httpx_json`` - the REAL ``HttpJson`` the signup module ships.
    A local wrapper used to stand here with the wrong signature (``data=`` sent as a
    JSON body, no ``json_body``/``headers`` kwargs at all), so any provider calling
    the protocol as documented raised ``TypeError`` and the auto lane never actually
    ran. There is exactly one correct implementation of that protocol; use it."""
    from integrations.web2_signup import SignupContext, api_signup_provider_for, httpx_json

    provider = api_signup_provider_for(platform)
    if provider is None:
        return ("blocked", {}, f"{platform} has no automatic signup.")
    ctx = SignupContext(
        platform=platform, alias_email="", username=handle or "aios", password="",
        http=httpx_json,
    )
    result = provider.signup(ctx)
    return (result.status, dict(result.credentials), result.error or "")


def _check_mail(mailbox: Any, alias: str, since: datetime) -> tuple[bool, str]:
    """One non-blocking look for a confirmation mail. Never sleeps, never raises."""
    from integrations.imap_mailbox import extract_verification

    msg = mailbox.check_once(
        to_alias=alias, since=since, subject_contains=("confirm", "verify", "activate")
    )
    if msg is None:
        return (False, "")
    return (True, extract_verification(msg).link or "")


def _write_tick_result(
    item_id: str, *, status: str, note: str, verify_link: str, account_id: str | None
) -> None:
    """Persist one decided move. Only the columns this tick owns are written."""
    sets = ["status = %s", "note = %s"]
    params: list[Any] = [status, note]
    if verify_link:
        sets.append("verify_link = %s")
        sets.append("verify_found_at = now()")
        params.append(verify_link)
    if account_id:
        sets.append("account_id = %s")
        params.append(account_id)
    params.append(item_id)
    with privileged_connection() as cur:
        cur.execute(
            "update public.web2_provision_items set "
            + ", ".join(sets)
            + " where id = %s",
            params,
        )


@celery_app.task(name="web2_provision_tick")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def web2_provision_tick_job(limit: int = 25) -> dict[str, Any]:
    """Entry point: advance the provisioning queue's automatic steps.

    Deliberately NOT on a beat schedule - beat is parked by standing owner instruction,
    and turning it on is an owner decision, not a side effect of adding a feature. The
    operator runs this from the account builder, and a future beat entry would change
    only WHO calls it.
    """
    return execute_web2_provision_tick(limit)


@celery_app.task(name="web2_write")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def web2_write_job(web2_id: str) -> dict[str, Any]:
    """Entry point: draft one planned Web 2.0 property and PARK it at ``needs_review``.

    The draft is NEVER auto-published. The ONLY path from ``needs_review`` to
    ``publishing`` is a lead's explicit approval (``POST /offpage/web2/{id}/approve``,
    or the campaign approve service, which calls that same per-property primitive once
    per ``web2_id``).

    That gate is load-bearing, not ceremonial. It is where the anchor, the footprint
    and the article body are judged before anything is posted under a client's name -
    and Tumblr's API License requires a per-post human action before an application
    posts on an account holder's behalf, so a batch/auto path would breach it.
    """
    settings = get_settings()
    outcome = execute_web2_write(service_offpage_store(), settings, web2_id)
    return outcome.as_dict()


@celery_app.task(name="web2_publish")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def web2_publish_job(web2_id: str) -> dict[str, Any]:
    """Entry point: publish + verify + track an APPROVED Web 2.0 property."""
    settings = get_settings()
    outcome = execute_web2_publish(service_offpage_store(), settings, web2_id)
    return outcome.as_dict()


def claim_due_web2_releases() -> list[dict[str, Any]]:
    """Claim every APPROVED property whose pacing slot has arrived.

    ``for update ... skip locked`` so two concurrent ticks never claim the same row - the
    claim is the mutex, and it lives at the database, which is the right place for it.
    Mirrors ``_claim_due_scheduled_codes`` in the content worker.

    ``of p`` is required, not stylistic: Postgres refuses ``FOR UPDATE`` over the nullable
    side of an outer join ("FeatureNotSupported"), and the account join is a LEFT JOIN
    because a property need not have an attributed account yet. Naming the properties
    table locks the rows we actually claim and leaves the account rows unlocked, which is
    also what we want - the tick reads an account's ownership, it does not modify it.
    """
    with privileged_connection() as cur:
        cur.execute(
            "select p.id, p.client_id, p.platform, p.status, p.account_id, "
            "       coalesce(a.ownership::text, 'per_client') as ownership "
            "from public.web2_properties p "
            "left join public.web2_accounts a on a.id = p.account_id "
            "where p.status = 'publishing' "
            "  and p.scheduled_for is not null and p.scheduled_for <= now() "
            "for update of p skip locked"
        )
        return [dict(row) for row in cur.fetchall()]


def execute_web2_release(
    store: ServiceOffpageStore, settings: Settings, *, now: datetime | None = None
) -> dict[str, Any]:
    """Release the due properties whose pacing caps still allow it.

    A PARTIAL RELEASE IS NOT A FAILURE HERE - deferring is a normal, expected outcome
    (the caps are re-checked at release because a schedule laid weeks ago cannot know
    what has happened since). What would be dishonest is reporting a deferral as a
    publish, so the two are counted separately and both are returned.
    """
    moment = now or datetime.now(UTC)
    due = claim_due_web2_releases()
    if not due:
        return {"claimed": 0, "released": [], "deferred": []}

    caps = PacingCaps.from_row(store.pacing_caps_row())
    history = [
        Placement(
            published_at=r["published_at"],
            web2_id=str(r["web2_id"]),
            client_id=str(r["client_id"]),
            platform=str(r["platform"]),
            account_id=str(r["account_id"]) if r.get("account_id") else None,
            ownership=str(r.get("ownership") or "per_client"),
        )
        for r in store.recent_web2_publishes()
    ]
    plan = plan_release(now=moment, caps=caps, due_rows=due, history=history)

    for decision in plan.decisions:
        if decision.action == "release":
            # Clearing the slot BEFORE enqueueing means a redelivered tick cannot claim
            # the same row again: the claim query requires a non-null scheduled_for.
            store.update_web2(decision.web2_id, {"scheduled_for": None})
            web2_publish_job.delay(decision.web2_id)
        elif decision.action == "defer" and decision.defer_until is not None:
            store.update_web2(decision.web2_id, {"scheduled_for": decision.defer_until})
    return {
        "claimed": len(due),
        "released": plan.released,
        "deferred": plan.deferred,
        "next_tick_at": plan.next_tick_at.isoformat() if plan.next_tick_at else "",
    }


@celery_app.task(name="web2_release_due")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def web2_release_due_job() -> dict[str, Any]:
    """Entry point: publish the approved properties whose drip slots have arrived.

    Un-keyed and idempotent by construction: the claim requires a non-null
    ``scheduled_for`` and the release clears it, so a redelivery finds nothing to redo.

    HOW IT IS DRIVEN. Celery beat is intentionally empty in this deployment, so this task
    is not scheduled by default - it is safe to call on demand and is designed to be
    driven either by a re-enabled beat entry or by a self-rescheduling chain. Until one
    of those is switched on, an IMMEDIATE campaign publishes normally (approval enqueues
    directly) and a DRIP campaign queues correctly but waits. That is a deliberate,
    visible state rather than a silent failure, and it is called out in the plan.
    """
    settings = get_settings()
    return execute_web2_release(service_offpage_store(), settings)


def _monitor_target(client_id: str, domain: str = "", business: str = "") -> JobTarget:
    # No idempotency key of its own: the caller supplies one (the router buckets by
    # minute so a double-click collapses, the weekly sweep derives one per client), and
    # a key baked in here would make a deliberate re-run a no-op.
    return JobTarget(client_id=client_id, scope_id=client_id)


@aios_job(
    # The pinned name is UNCHANGED, so every existing caller and any message already
    # in flight keeps working across this migration.
    name="monitor_offpage",
    job_name="offpage.monitor",
    # LONG, not STANDARD. This ran under Celery's default 1800s limit; LONG's limit is
    # exactly that, so nothing that was legal yesterday is newly killed today.
    queue=JobQueue.LONG,
    max_attempts=1,
    client_concurrency=1,
    scope_type="client",
    target=_monitor_target,
)
def monitor_offpage_job(
    ctx: JobContext, client_id: str, domain: str = "", business: str = ""
) -> JobOutcome:
    """Run the backlink + citation monitoring sweep for one client.

    UNDER THE JOB CONTRACT SINCE THE CITATION AUDIT NEEDED TO BE VISIBLE. As a plain
    Celery task this produced no job_runs row at all, so "run citation audit" returned
    a bare {"status": "queued"} with no id, nothing could be polled, and an operator
    had no way to tell a running sweep from a dead one. Now it has a run id, a live
    stage line, and an honest terminal state.

    A keyless provider DEGRADES rather than passing silently. That was the worst of
    the old behaviour: with no BrightLocal or Serper key the sweep returned
    {"state": "degraded"} to a caller that discarded it, wrote zero rows, and the
    board simply showed no citations - indistinguishable from a business that has
    none. The contract requires a reason for `degraded`, so it cannot be recorded
    without saying which half did not run.
    """
    settings = get_settings()
    ctx.checkpoint()
    result = execute_monitor(
        service_offpage_store(), settings,
        client_id=client_id, domain=domain, business=business,
        progress=ctx.progress,
    )

    backlinks = dict(result.get("backlinks") or {})
    citations = dict(result.get("citations") or {})
    counts = {
        "backlinks_new": int(backlinks.get("new") or 0),
        "backlinks_changed": int(backlinks.get("changed") or 0),
        "citations_new": int(citations.get("new") or 0),
        "citations_changed": int(citations.get("changed") or 0),
        "backlinks_state": str(backlinks.get("state") or ""),
        "citations_state": str(citations.get("state") or ""),
    }

    states = {counts["backlinks_state"], counts["citations_state"]}
    if states & {"blocked"}:
        return JobOutcome.blocked(
            "offpage_monitor_blocked",
            "the cost gate refused this sweep: "
            + ", ".join(
                f"{half} ({d.get('reason')})"
                for half, d in (("backlinks", backlinks), ("citations", citations))
                if d.get("state") == "blocked"
            ),
            result=counts,
        )
    unavailable = [
        half
        for half, d in (("backlinks", backlinks), ("citations", citations))
        if d.get("state") in {"degraded", "error"}
    ]
    if unavailable:
        return JobOutcome.degraded(
            "offpage_provider_unavailable",
            f"{' and '.join(unavailable)} could not be checked: "
            + "; ".join(
                str(d.get("reason") or "unavailable")
                for d in (backlinks, citations)
                if d.get("state") in {"degraded", "error"}
            )
            + ". The counts below cover only what did run.",
            result=counts,
        )
    return JobOutcome.completed(
        f"{counts['citations_new']} new and {counts['citations_changed']} changed listings",
        result=counts,
    )


def _verify_backlinks_target(limit: int = 25) -> JobTarget:
    """Idempotency = the DAY. A hand-fired second run on the same day collapses onto
    the first (nothing new would be due minutes later anyway); the automations
    dispatcher overrides with its own per-occurrence key, so a scheduled cadence is
    never blocked by a manual run. No client_id: the sweep is platform-wide."""
    return JobTarget(idempotency_key=f"backlinks:verify:{datetime.now(UTC):%Y-%m-%d}")


@aios_job(
    name="verify_backlinks",
    job_name="offpage.verify_backlinks",
    queue=JobQueue.STANDARD,
    max_attempts=1,
    target=_verify_backlinks_target,
)
def verify_backlinks_job(ctx: JobContext, limit: int = 25) -> JobOutcome:
    """Entry point: fetch each due referring page and confirm the client's link.

    Cost: plain HTTP GETs against already-known pages - no provider call, so it does
    NOT go through the money dial (mirrors citation_liveness_recheck). Driven by the
    paused `offpage.verify_backlinks` automation row (0134) or on demand; beat stays
    off either way.
    """
    ctx.checkpoint()
    result = execute_verify_backlinks(service_offpage_store(), limit=limit)
    counts = {
        "checked": int(result.get("checked") or 0),
        "lost_confirmed": int(result.get("lost_confirmed") or 0),
        "outcomes": result.get("outcomes") or {},
    }
    if result.get("state") == "error":
        # The due list itself could not be read. `completed, 0 checked` would claim
        # "nothing was due", which is a different fact entirely.
        return JobOutcome.degraded(
            "backlink_verify_unavailable",
            "the backlinks due a check could not be claimed, so none were verified",
            result=counts,
        )
    return JobOutcome.completed(
        f"verified {counts['checked']} backlinks, {counts['lost_confirmed']} confirmed lost",
        result=counts,
    )


def _recheck_web2_target(limit: int = 50) -> JobTarget:
    """Same day-bucket rule as the backlink sweep, same dispatcher-override escape."""
    return JobTarget(idempotency_key=f"web2:linkcheck:{datetime.now(UTC):%Y-%m-%d}")


@aios_job(
    name="recheck_web2_links",
    job_name="web2.link_recheck",
    queue=JobQueue.STANDARD,
    max_attempts=1,
    target=_recheck_web2_target,
)
def recheck_web2_links_job(ctx: JobContext, limit: int = 50) -> JobOutcome:
    """Entry point: re-measure the placed link on published Web 2.0 properties.

    `published != still-linked`: this is what keeps `link_found` an observation
    rather than a publish-day claim. Free (plain GETs), so no money dial; driven by
    the paused `web2.link_recheck` automation row (0134) or on demand.
    """
    ctx.checkpoint()
    result = execute_web2_link_recheck(service_offpage_store(), limit=limit)
    counts = {
        "checked": int(result.get("checked") or 0),
        "demoted": int(result.get("demoted") or 0),
        "outcomes": result.get("outcomes") or {},
    }
    if result.get("state") == "error":
        return JobOutcome.degraded(
            "web2_link_recheck_unavailable",
            "the published properties could not be listed, so no links were re-checked",
            result=counts,
        )
    return JobOutcome.completed(
        f"re-checked {counts['checked']} placements, {counts['demoted']} demoted",
        result=counts,
    )
