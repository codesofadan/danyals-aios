"""Citation-submission worker (7B-4): the never-stuck / never-re-raise / idempotent
driver that claims a QUEUED citation row, dispatches it to the right engine (a
legitimate direct API - the Playwright form bot is RETIRED, Phase 3/C1) or routes
it to the operator queue, and tracks the outcome. Mirrors
``workers/tasks/offpage.py``'s Web 2.0 tasks exactly - with
``task_acks_late`` a raised exception would redeliver the job and re-run a PAID
stage (double spend), so this always acks and returns a small result dict.

``_FEATURE`` is the money-dial this module's only paid stage gates through -
``tests/test_dial_registration.py`` auto-discovers this constant and fails the
build if it is not registered in ``app/schemas/cost.py`` (the exact defect that bit
four Part-8 modules before that guard existed).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Json

from app.config import Settings, get_settings
from app.core.security import is_public_url
from app.logging_setup import get_logger
from app.modules.citations.repo import ServiceCitationsStore, service_citations_store
from app.modules.citations.service import (
    disposition_for_block,
    is_human_queue_method,
    is_prohibited,
    job_from_row,
    submitter_for,
)
from app.services.citation_liveness import (
    DRIFTED,
    LIVE,
    LivenessProbe,
    http_liveness_probe,
    judge_liveness,
    next_recheck_days,
)
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.citation_aggregators import AppleBusinessSubmitter, DataAxleSubmitter
from integrations.citation_submitters import CitationSubmitter
from integrations.errors import ProviderNotConfiguredError

logger = get_logger("app.modules.citations.tasks")

_FEATURE = "citations"
_JOB_TYPE = "citations"
_ERROR_MAX = 500
_TERMINAL = frozenset({"submitted", "verified", "failed"})
# How soon to retry a citation whose directory we could not reach. Short, because
# nothing was learned - and deliberately NOT a rung of the settling ladder, so a
# network blip cannot push the next real check three months out.
_UNREACHABLE_RETRY_DAYS = 1


class _NullCostCache:
    """A no-op ``CostCache`` - a citation submit is never cache-keyed (a live
    submission must always run; the dial + budgets still gate it)."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


def _api_submitters(settings: Settings) -> dict[str, CitationSubmitter]:
    """The direct-API engines, keyed to match a directory's ``submit_method`` suffix
    (``api:data_axle`` -> key ``data_axle``).

    EMPTY TODAY, ON PURPOSE. This held ``BingPlacesSubmitter`` and
    ``FoursquareSubmitter``; both were deleted because their coded write endpoints do
    not exist. Probed unauthenticated 2026-08-23:

        POST https://api.foursquare.com/v3/places                     -> 404
        POST https://places-api.foursquare.com/places                 -> 404
        POST https://ssl.bing.com/webmaster/places/api/v1/locations   -> 301 -> 404

    with a Foursquare READ endpoint returning 401 as the control, so these are missing
    routes and not auth failures. Foursquare routes place additions to a
    community-moderated Placemaker queue - there is no endpoint to repair - and Bing
    Places API access is a partner programme, not a public write path.

    TWO ARE WIRED BELOW, NOT THREE. R1 verified three live write APIs - Data Axle, Apple
    Business Connect and Google Business Profile - but only the first two have an engine
    in this file. `api:gbp` has none, so a GBP row blocks with "no API submitter
    configured for 'gbp'", which is honest but means GBP credentials alone do NOT open
    that route: the engine has to be written first. Said here explicitly because the
    catalogue row, the `api` tier and the config key all exist and make it look wired.

    Each is built ONLY when its key is present, so the dict never holds a client that
    cannot actually call anything - and ``submitter_for`` reports the honest "not
    configured" reason for whatever is absent rather than a caller having to None-check
    twice.

    DATA AXLE IS ALSO PRICE-GATED, which is the unusual part and the important one. Its
    per-Add price is published nowhere reachable, and at the modelled $5/$10/$30 the
    per-unit cost is 17x-100x the 10c commitment. So the key alone is not enough: until
    ``data_axle_add_cost_estimate`` is a real number the submitter is not built at all,
    and the row blocks rather than spending against a figure nobody has confirmed.
    A key without a price is a way to spend money by accident."""
    out: dict[str, CitationSubmitter] = {}
    if settings.data_axle_api_key and settings.data_axle_submits_enabled:
        with contextlib.suppress(ProviderNotConfiguredError):
            out["data_axle"] = DataAxleSubmitter(
                api_key=settings.data_axle_api_key.get_secret_value()
            )
    if settings.apple_business_api_key and settings.apple_business_org_id:
        with contextlib.suppress(ProviderNotConfiguredError):
            out["apple_business"] = AppleBusinessSubmitter(
                api_key=settings.apple_business_api_key.get_secret_value(),
                org_id=settings.apple_business_org_id,
            )
    return out


# The submit methods a Data Axle Add is billed for. Apple Business Connect and Google
# Business Profile share the `api` tier and cost NOTHING per submission - they are gated by
# credentials, not by a rate card - so neither belongs here.
_DATA_AXLE_METHODS: frozenset[str] = frozenset({"api:data_axle"})


def _is_priced_by_data_axle(submit_method: str) -> bool:
    """Whether this row's submission is billed at the (unknown) Data Axle Add rate.

    `aggregator:fed_by_*` rows never reach the submitter at all - `submitter_for` returns
    "no action needed - covered by seeding the core aggregator(s)" - so they are not
    listed: they cost nothing because nothing is sent."""
    return submit_method in _DATA_AXLE_METHODS


def _cost_estimate_for(tier: str, settings: Settings, submit_method: str = "") -> float:
    if _is_priced_by_data_axle(submit_method):
        # 0.0 until a real rate card is on file. The guard in `execute_citation_submit`
        # refuses these rows while `data_axle_submits_enabled` is False, so the 0.0 is
        # never actually spent - it is a blocked route, not a free one.
        return settings.data_axle_add_cost_estimate
    # Everything else is zero because it IS zero: Apple/GBP are real API calls with no
    # per-submission charge, and every form tier (bot_fillable / captcha_assisted) is
    # operator-queue work since the Playwright bot's retirement - a person's minutes,
    # never metered provider spend. The old per-submit bot/solve estimates were deleted
    # with the bot (Phase 3, plan C1).
    return 0.0


def execute_citation_submit(
    store: ServiceCitationsStore, settings: Settings, citation_id: str
) -> dict[str, Any]:
    """Submit ONE queued citation. Never raises - a redelivered/already-terminal row
    is a clean no-op; any failure marks the row ``failed`` with a capped error,
    never leaves it stuck at ``submitting``."""
    try:
        row = store.load_citation_with_directory(citation_id)
        if row is None:
            logger.warning("citation_submit_missing", citation_id=citation_id)
            return {"state": "error", "reason": "not found"}
        status = str(row.get("submit_status") or "not_started")
        if status in _TERMINAL:
            return {"state": "unchanged", "reason": f"submit_status={status}"}
        if status != "queued":
            return {"state": "skipped", "reason": f"submit_status={status}"}

        # HONEST-STATE GUARD: a citation with no business name has no NAP to submit -
        # the joined business_profile is empty (the client never had one). Dispatching
        # it anyway sends an empty listing that the directory rejects, and the row comes
        # back 'failed' as if the ENGINE broke, when in truth we simply had no data. Mark
        # it 'blocked' with the real reason instead, and never spend the gate on it. This
        # is the root of "citation submit shows failed" for a client whose NAP was never
        # captured; the fix upstream (0051 + derive-on-campaign) means this should be rare.
        if not str(row.get("bp_business_name") or "").strip():
            store.update_citation(
                citation_id,
                {
                    "submit_status": "blocked",
                    # This site used to write NO reason code at all, so the row rendered
                    # in the client report with an empty `skip_reason` - the one state
                    # 0106 §0.5 exists to prevent. `no_nap` also routes correctly through
                    # `disposition_for_block`: it is a data problem for a lead to fix, not
                    # work an operator can complete in a browser.
                    "blocked_reason": "no_nap",
                    "error": "no business profile / NAP for this client - capture its "
                    "name and address before submitting (nothing was sent)",
                },
            )
            logger.info("citation_submit_no_nap", citation_id=citation_id)
            return {"state": "blocked", "reason": "no business profile / NAP"}

        # TERMS GUARD, and it runs BEFORE the cost gate because a prohibited submission
        # must not even be priced. Yelp, Trustpilot and Houzz publish clauses banning
        # automated ACCESS and RETRIEVAL, and a form bot must GET the form before it can
        # fill it - so the clause binds us, and "we only submitted, we didn't scrape" is
        # not a reading that survives. `route='F'` is the derived decision (0106);
        # `tos_position` is the evidence behind it. Blocking on route and not on
        # tos_position is what keeps GBP and Apple - prohibited as BOT targets, legitimate
        # over their own APIs - reachable on route 'A'.
        #
        # This is a hard block in the worker, never a warning in the UI. A submission made
        # under a client's identity against a platform's terms is the CLIENT's exposure.
        if is_prohibited(row):
            store.update_citation(
                citation_id,
                {
                    "submit_status": "blocked",
                    "blocked_reason": "tos_prohibits",
                    "error": (
                        "this directory's terms forbid automated submission - nothing was "
                        f"sent. Clause: {row.get('directory_tos_source_url') or 'on file'!s}"
                    ),
                },
            )
            logger.info("citation_submit_prohibited", citation_id=citation_id)
            return {"state": "blocked", "reason": "tos_prohibits"}

        tier = str(row.get("directory_tier") or "")
        # The CITATION's own snapshot, copied verbatim from the catalogue at queue time
        # (`submit_method_label`), not the directory's current value - so a catalogue edit
        # after a lead approved a batch cannot silently re-route or re-price it. The same
        # string the dispatch below reads.
        submit_method = str(row.get("submit_method") or "")

        # PRICE GUARD: a Data Axle Add costs an unknown amount, and an unpriced Add would
        # pass the cost gate as free. Blocking is the only honest option - a run that
        # spends against an invented number cannot be un-spent.
        #
        # KEYED ON THE METHOD, NOT THE TIER. It used to fire for the whole `api`/
        # `aggregator` bucket, which also holds Apple Business Connect and Google Business
        # Profile - both FREE per submission, neither billed by Data Axle. So the moment
        # the owner obtained Apple or GBP credentials (the one thing that unblocks route A
        # without a rate card), their submissions would still have blocked, quoting
        # DATA_AXLE_ADD_COST_ESTIMATE - a rate card for a different vendor that has nothing
        # to do with either. The guard now names exactly the submitter whose price is
        # unknown.
        if _is_priced_by_data_axle(submit_method) and not settings.data_axle_submits_enabled:
            store.update_citation(
                citation_id,
                {
                    "submit_status": "blocked",
                    "blocked_reason": "price_unknown",
                    "error": (
                        "aggregator submissions are blocked until a real per-Add rate is "
                        "configured (DATA_AXLE_ADD_COST_ESTIMATE) - nothing was sent and "
                        "nothing was charged"
                    ),
                },
            )
            logger.info("citation_submit_unpriced", citation_id=citation_id, tier=tier)
            return {"state": "blocked", "reason": "price_unknown"}

        client_id = row.get("client_id")
        ctx = GateContext(
            feature_key=_FEATURE,
            client_id=str(client_id) if client_id else None,
            provider=f"citations:{tier or 'unknown'}",
            estimated_cost=_cost_estimate_for(tier, settings, submit_method),
            job_id=citation_id,
            job_type=_JOB_TYPE,
            client_name=str(row.get("client_name") or ""),
        )
        # ENGINE RESOLUTION HAPPENS BEFORE THE COST GATE, and the order is the point.
        #
        # It used to run after: the gate charged, the row went to `submitting`, and only
        # then did the worker discover there was no engine - so a client was billed for a
        # submission that could not physically happen. Since the Playwright bot's
        # retirement (Phase 3, plan C1) the machine-dispatchable set is SMALL - the two
        # legitimate API submitters - so "route to a person" is the common case, and
        # charging for it would turn an honest coverage number into a bill.
        #
        # Nothing above this line spends. `submitter_for` is pure dispatch.
        submitter, reason = submitter_for(
            submit_method,
            api_submitters=_api_submitters(settings),
        )
        if submitter is None:
            # `disposition_for_block` decides where an undispatched row goes:
            #
            #  * fed_by_aggregator -> `blocked` (nothing to submit; the listing arrives
            #    through the core feed and offering it as work would be an invented task).
            #  * every retired bot route (`bot:*`, non-fed `aggregator:*`, `manual`) ->
            #    `ready_for_human` with the honest code `human_queue`: form work is a
            #    PERSON's by design, not an engine gap. This is the campaign skip
            #    ledger's truth - "43 waiting on human_queue" means 43 items of real
            #    queue work, not 43 misconfigurations.
            #  * anything else (an unconfigured API engine, `closed`, an unknown
            #    method) -> `no_engine`, which still routes to the queue where a person
            #    can act and stays honest where they cannot.
            if submit_method.startswith("aggregator:fed_by_"):
                code = "fed_by_aggregator"
            elif is_human_queue_method(submit_method):
                code = "human_queue"
            else:
                code = "no_engine"
            state = disposition_for_block(code)
            store.update_citation(
                citation_id,
                {
                    "submit_status": state,
                    "blocked_reason": code,
                    "error": reason[:_ERROR_MAX],
                },
            )
            logger.info(
                "citation_submit_not_dispatched",
                citation_id=citation_id, reason=reason, code=code, disposition=state,
            )
            return {"state": state, "reason": reason}

        decision = _gate().evaluate(ctx)
        if not decision.allowed:
            store.update_citation(
                citation_id,
                {
                    "submit_status": "blocked",
                    # The stable machine code lives in blocked_reason (the rollups and
                    # the UI's sentence map group on it); the gate's specific outcome
                    # stays in error. This used to write NO reason at all — the one
                    # blocked state 0106 §0.5 says must not exist.
                    "blocked_reason": "spend_blocked",
                    "error": (
                        f"spend_blocked:{decision.outcome} - nothing was sent and "
                        "nothing was charged"
                    ),
                },
            )
            logger.info("citation_submit_blocked", citation_id=citation_id, outcome=decision.outcome)
            return {"state": "blocked", "reason": decision.outcome}

        store.update_citation(citation_id, {"submit_status": "submitting"})

        try:
            result = submitter.submit(job_from_row(row))
        except Exception as exc:  # a provider crash still marks failed - never stuck, never re-raised
            _gate().commit(ctx, ctx.estimated_cost)  # the attempt still incurred the metered cost
            logger.exception("citation_submit_provider_error", citation_id=citation_id)
            store.update_citation(
                citation_id,
                {
                    "submit_status": "failed",
                    "error": f"{exc!r}"[:_ERROR_MAX],
                    # The per-row answer to "what did this listing cost" (0121): the
                    # committed estimate, mirroring what cost_log just recorded.
                    "cost": ctx.estimated_cost,
                },
            )
            return {"state": "failed", "reason": f"{exc!r}"[:_ERROR_MAX]}

        # A native API can turn out not to expose the write endpoint at all (e.g.
        # Foursquare's public API has no anonymous place-create - POST /v3/places
        # 404s). With no fallback engine, that engine's own honest failed/blocked
        # result stands as-is - a queued directory it cannot reach is reported
        # truthfully rather than silently re-routed.
        _gate().commit(ctx, ctx.estimated_cost)
        fields: dict[str, Any] = {
            "submit_status": result.status,
            "proof_url": result.proof_url,
            "error": result.error[:_ERROR_MAX],
            # Per-row cost (0121): what this attempt committed, mirroring cost_log.
            "cost": ctx.estimated_cost,
        }
        if result.external_ref:
            fields["external_ref"] = result.external_ref
        if result.status in ("submitted", "verified"):
            fields["action"] = "Update"
            fields["submitted_at"] = datetime.now(UTC)
            # HONEST NAP: nothing here claims nap_status='consistent'.
            #
            # A submission that was SENT is not a listing that EXISTS, and this function
            # never reads one back - so it has no evidence to assert consistency with. It
            # used to make that claim on `result.status == "verified"`, which no submitter
            # can return: Data Axle runs teleresearch over up to three business days,
            # Apple returns SUBMITTED, and the bot only ever sees its own success
            # indicator on its own page. So the branch was unreachable, and had anything
            # ever reached it, it would have re-asserted precisely the unbacked claim this
            # module was rebuilt to remove. Only the liveness verifier - which fetches the
            # live URL and matches the name against the phone or address - promotes a row.
        store.update_citation(citation_id, fields)
        logger.info("citation_submit_done", citation_id=citation_id, status=result.status)
        return {"state": result.status, "reason": result.error}
    except Exception as exc:  # never re-raise (acks_late would redeliver = double spend)
        logger.exception("citation_submit_error", citation_id=citation_id)
        try:
            store.update_citation(citation_id, {"submit_status": "failed", "error": f"{exc!r}"[:_ERROR_MAX]})
        except Exception:
            logger.warning("citation_submit_mark_failed_failed", citation_id=citation_id)
        return {"state": "error", "reason": f"{exc!r}"[:_ERROR_MAX]}


# --------------------------------------------------------------------------- #
# Liveness re-check: the job that makes `live` mean something a week later.
# --------------------------------------------------------------------------- #
def execute_liveness_recheck(
    store: ServiceCitationsStore,
    *,
    fetch: Callable[[str], LivenessProbe],
    limit: int = 200,
) -> dict[str, Any]:
    """Re-confirm every citation whose re-check has come due.

    WHY THIS EXISTS. `live` is not a fact you establish once. Directories delete
    listings, merge duplicates, expire unclaimed entries and quietly change a phone
    number, and none of that notifies us. Without this sweep, `live` decays from an
    observation into a claim - and a stale claim on a client report is the same class of
    defect as the screenshot-as-live-URL it replaced.

    `fetch` is INJECTED so the whole decision path unit-tests with zero network. It
    returns a `LivenessProbe`; a fetch that raises is caught here and treated as "we
    could not look", which holds the row rather than delisting it.

    Never raises: with `task_acks_late` a redelivery would re-run the whole sweep, and
    one unreachable directory must not cost the other 199 their re-check."""
    checked = 0
    changed = 0
    outcomes: dict[str, int] = {}
    try:
        rows = store.due_for_recheck(limit=limit)
    except Exception:
        logger.exception("citation_recheck_load_failed")
        return {"state": "error", "checked": 0, "changed": 0}

    for row in rows:
        citation_id = str(row.get("id"))
        live_url = str(row.get("live_url") or "")
        discovered_url = str(row.get("discovered_url") or "")
        # PROMOTION CANDIDATE (0129): discovery found a URL and nothing has verified it
        # yet. The probe below is the ONLY thing that can grant `live` - discovery
        # never does; it merely nominates the URL the probe now fetches.
        promoting = not live_url and bool(discovered_url)
        target_url = live_url or discovered_url
        try:
            # SSRF guard: the target URL is operator/provider-supplied and this runs
            # server-side, so a private/loopback host must never be fetched.
            if not is_public_url(target_url):
                probe = LivenessProbe(status_code=None, checked_from="refused:non-public-url")
            else:
                probe = fetch(target_url)
        except Exception:
            # A failure to LOOK is not evidence the listing is gone. Hold the row.
            logger.warning("citation_recheck_fetch_failed", citation_id=citation_id)
            probe = LivenessProbe(status_code=None, checked_from="fetch-error")

        verdict = judge_liveness(
            probe,
            business_name=str(row.get("bp_business_name") or ""),
            phone=str(row.get("bp_phone") or ""),
            address_line1=str(row.get("bp_address_line1") or ""),
        )
        checked += 1
        outcomes[verdict.status] = outcomes.get(verdict.status, 0) + 1

        count = int(row.get("recheck_count") or 0)
        current = str(row.get("submit_status") or "")

        # COULD NOT LOOK is not a verdict about the listing.
        #
        # `judge_liveness` returns `submitted` for an unreachable host, meaning "ask
        # again" - but WRITING that would downgrade a confirmed `live` row to `submitted`
        # because our own DNS blipped, silently dropping a real citation out of the
        # client's live count. That is the same harm as delisting it: it invents work to
        # redo. So the row's status is left exactly as it was, the failed attempt is
        # recorded in the evidence, and it is retried SOON rather than consuming a rung of
        # the settling ladder - a network failure must not push the next real check out by
        # three months. (This holds for a PROMOTION candidate too: an unreachable host
        # neither promotes nor demotes it.)
        could_not_look = probe.status_code is None
        if could_not_look:
            fields: dict[str, Any] = {
                "verification_evidence": Json(verdict.evidence),
                "next_recheck_at": datetime.now(UTC) + timedelta(days=_UNREACHABLE_RETRY_DAYS),
            }
        elif promoting:
            days = next_recheck_days(
                recheck_count=count,
                authority_tier=str(row.get("directory_authority_tier") or ""),
                route=str(row.get("directory_route") or ""),
            )
            if verdict.status in (LIVE, DRIFTED):
                # THE PROBE GRANTS LIVE - discovery never does. The page answered and
                # the business is really on it, so the discovered URL is promoted:
                # live_url is earned, the method is 'discovery' (the value 0106
                # reserved for exactly this path), and the status is whatever the
                # existing judge decided (live, or drifted when the NAP no longer
                # matches - the listing exists either way).
                fields = {
                    "live_url": discovered_url,
                    "submit_status": verdict.status,
                    "verification_method": "discovery",
                    "verification_evidence": Json(verdict.evidence),
                    "recheck_count": count + 1,
                    "next_recheck_at": datetime.now(UTC) + timedelta(days=days),
                    "evidence_checked_at": datetime.now(UTC),
                }
                if verdict.is_live:
                    fields["live_url_verified_at"] = datetime.now(UTC)
                if current != verdict.status:
                    changed += 1
            else:
                # The probe LOOKED and the business was not there. That is NOT a
                # delisting - nothing was ever live at this URL - it is the discovery
                # claim failing verification, so the `confirmed` tier no longer
                # stands: demote to `uncertain` (the verify-first bucket owns it now)
                # and leave live_url/submit_status untouched.
                fields = {
                    "evidence_level": "uncertain",
                    "verification_evidence": Json(verdict.evidence),
                    "next_recheck_at": datetime.now(UTC) + timedelta(days=days),
                    "evidence_checked_at": datetime.now(UTC),
                }
        else:
            days = next_recheck_days(
                recheck_count=count,
                authority_tier=str(row.get("directory_authority_tier") or ""),
                route=str(row.get("directory_route") or ""),
            )
            fields = {
                "submit_status": verdict.status,
                "verification_method": verdict.method,
                "verification_evidence": Json(verdict.evidence),
                "recheck_count": count + 1,
                "next_recheck_at": datetime.now(UTC) + timedelta(days=days),
            }
            # Only a CONFIRMED live listing stamps the verified-at timestamp. A drifted
            # or delisted row keeps whatever the last real confirmation was, so "when did
            # we last actually see this?" stays answerable.
            if verdict.is_live:
                fields["live_url_verified_at"] = datetime.now(UTC)
            if current != verdict.status:
                changed += 1
        try:
            store.update_citation(citation_id, fields)
        except Exception:
            logger.exception("citation_recheck_update_failed", citation_id=citation_id)

    logger.info("citation_recheck_done", checked=checked, changed=changed, **outcomes)
    return {"state": "ok", "checked": checked, "changed": changed, "outcomes": outcomes}


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app lazily-free at module load, per the
# worker template).
# --------------------------------------------------------------------------- #
from app.jobs import JobOutcome, JobQueue, JobTarget  # noqa: E402 - after the pure core
from app.jobs.celery_task import aios_job  # noqa: E402 - after the pure core
from app.jobs.contract import JobContext  # noqa: E402 - after the pure core


def _submit_target(citation_id: str, client_id: str = "", campaign_id: str = "") -> JobTarget:
    """Idempotency = the row x the campaign that queued it. A double-POSTed campaign
    cannot run a row twice; a LATER campaign that legitimately requeues the same
    citation gets a fresh key."""
    return JobTarget(
        idempotency_key=f"citations.submit:{citation_id}:{campaign_id or 'manual'}",
        client_id=client_id or None,
        scope_id=citation_id,
    )


def _submit_outcome(result: dict[str, Any]) -> JobOutcome:
    """Map the pure core's state vocabulary onto the contract's five outcomes.

    Doctrine: ``is_success()`` may be true only when a submission actually went out.
    ``ready_for_human`` is a routing verdict, not a delivery — it renders as blocked
    with its reason so Operations can aggregate "43 waiting on human_queue"."""
    state = str(result.get("state") or "error")
    reason = str(result.get("reason") or "")
    if state in ("submitted", "verified"):
        return JobOutcome.completed(detail=f"submitted ({reason or 'engine ok'})", result=result)
    if state in ("unchanged", "skipped"):
        # An idempotent no-op on a row already terminal / already moving.
        return JobOutcome.completed(detail=f"no-op: {reason}", result=result)
    if state == "ready_for_human":
        return JobOutcome.blocked(
            reason_code=reason or "ready_for_human",
            reason=f"routed to the operator queue: {reason or 'a person finishes this one'}",
            result=result,
        )
    if state == "blocked":
        return JobOutcome.blocked(
            reason_code=reason or "blocked", reason=reason or "refused by policy", result=result
        )
    return JobOutcome.failed(
        error_type=state if state in ("failed", "error") else "unexpected_state",
        error_message=reason,
        result=result,
    )


@aios_job(
    # The pinned task name is unchanged, so in-flight messages survive the migration
    # (the same move citation_liveness_recheck made below).
    name="citation_submit",
    job_name="citations.submit",
    # BROWSER: kept for message-compatibility (in-flight jobs and worker -Q lists name
    # it). The Playwright bot is retired, so nothing here launches a browser any more -
    # dispatch/classification runs are milliseconds and an API submit is one HTTP call,
    # both of which this queue serves fine.
    queue=JobQueue.BROWSER,
    # ONE attempt: execute_citation_submit already owns never-re-raise / never-
    # double-spend. The contract adds the ledger row, dead-letter and reaper coverage
    # this task ran without — a bare @celery_app.task wrote NO job_runs row, so a
    # 45-row campaign was invisible in Operations and, with no worker consuming the
    # queue, indistinguishable from a platform that was merely idle (2026-09-01).
    max_attempts=1,
    client_concurrency=2,
    scope_type="citation",
    target=_submit_target,
)
def citation_submit_job(
    ctx: JobContext, citation_id: str, client_id: str = "", campaign_id: str = ""
) -> JobOutcome:
    """Entry point: submit one queued citation row, under the job contract."""
    ctx.checkpoint()
    result = execute_citation_submit(service_citations_store(), get_settings(), citation_id)
    return _submit_outcome(result)


@aios_job(
    # The pinned name is unchanged, so existing callers and any in-flight message
    # keep working across this migration.
    name="citation_liveness_recheck",
    job_name="citations.liveness",
    queue=JobQueue.LONG,
    max_attempts=1,
)
def citation_liveness_recheck_job(ctx: JobContext, limit: int = 200) -> JobOutcome:
    """Entry point: re-confirm every citation whose re-check has come due.

    Cost: this makes plain HTTP GETs and no provider call, so it does NOT go through the
    money dial - there is nothing metered to gate. (~$41/yr for 100 clients even at the
    Serper-assisted cadence, which is why the cadence is a quality decision.)

    UNDER THE JOB CONTRACT because it is an automation now, and an automation whose
    runs leave no trace is the defect this platform is being repaired of: it would
    fire on schedule, report nothing, and be indistinguishable from one that never
    ran. It was the last capability in the registry still doing that - the other
    thirteen already write a run row.
    """
    ctx.checkpoint()
    result = execute_liveness_recheck(service_citations_store(), fetch=http_liveness_probe)
    counts = {
        "checked": int(result.get("checked") or 0),
        "changed": int(result.get("changed") or 0),
        "outcomes": result.get("outcomes") or {},
    }
    if result.get("state") == "error":
        # The sweep could not read its own work list. Reporting `completed` with zero
        # checked would say "nothing was due", which is a different fact entirely.
        return JobOutcome.degraded(
            "citation_liveness_unavailable",
            "the listings due a re-check could not be read, so none were confirmed",
            result=counts,
        )
    return JobOutcome.completed(
        f"re-checked {counts['checked']} listings, {counts['changed']} changed",
        result=counts,
    )
