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
from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
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
    differs. Pure + deterministic."""
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
        elif str(existing.get("nap_status") or "") != rec.nap_status:
            changed.append((existing, rec))
    return CitationDiff(new=new, changed=changed)


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
    for rec in diff.new:
        store.insert_citation(
            client_id=client_id, client_name=client_name, directory=rec.directory,
            nap_status=rec.nap_status, action=action_for(rec.nap_status), note=rec.note,
            directory_id=catalog.get(canonical_norm(rec.directory)),
        )
    for existing, rec in diff.changed:
        store.update_citation_status(
            str(existing["id"]), nap_status=rec.nap_status,
            action=action_for(rec.nap_status), note=rec.note,
        )
    logger.info(
        "citation_monitor_done", business=business,
        new=len(diff.new), changed=len(diff.changed),
    )
    return {"state": "ok", "new": len(diff.new), "changed": len(diff.changed)}


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
        return build_publisher(vault_label=vault_label, platform=platform, lookup=find_secret)
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
