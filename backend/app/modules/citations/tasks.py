"""Citation-submission worker (7B-4): the never-stuck / never-re-raise / idempotent
driver that claims a QUEUED citation row, dispatches it to the right engine (a
direct API or the self-hosted Playwright bot), and tracks the
outcome. Mirrors ``workers/tasks/offpage.py``'s Web 2.0 tasks exactly - with
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
    is_prohibited,
    job_from_row,
    submitter_for,
)
from app.services.citation_liveness import (
    LivenessProbe,
    http_liveness_probe,
    judge_liveness,
    next_recheck_days,
)
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.captcha_solver import captcha_solver_from_settings
from integrations.citation_aggregators import AppleBusinessSubmitter, DataAxleSubmitter
from integrations.citation_bot import citation_bot_from_settings, db_spec_loader
from integrations.citation_signup import citation_signup_bot_from_settings
from integrations.citation_submitters import CitationSubmitter
from integrations.errors import ProviderNotConfiguredError
from integrations.imap_mailbox import imap_mailbox_from_settings

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
    if tier in ("api", "aggregator"):
        # Apple and GBP: a real API call, no per-submission charge. Priced at zero because
        # it IS zero, not because the price is unknown.
        return 0.0
    if tier == "bot_fillable":
        return settings.citation_bot_cost_estimate
    if tier == "captcha_assisted":
        return settings.citation_captcha_cost_estimate
    # Any other/unknown tier falls to the self-hosted Playwright bot's estimate -
    # the default engine for a directory not on the api/aggregator/captcha tiers.
    return settings.citation_bot_cost_estimate


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
        # submission that could not physically happen. That was survivable while the bot
        # fell back to a 50-entry in-code catalogue and almost always had *something* to
        # run. It stops being survivable now that the bot only drives EARNED specs
        # (0108): the whitelist starts empty, so "no engine" is the common case, and
        # charging for it would turn an honest coverage number into a bill.
        #
        # Nothing above this line spends. `submitter_for` is pure dispatch, and building
        # the bot only imports Playwright and reads the active-spec whitelist.
        job = job_from_row(row)
        solver = captcha_solver_from_settings(settings)
        # The EARNED whitelist is the bot's ONLY source of a runnable spec (0108).
        # `route` suppresses the residential proxy on Route B: a Route B directory is by
        # definition undefended, so one that starts answering 403 has BECOME Route C -
        # a route change to record, not proxy bandwidth to buy.
        bot = citation_bot_from_settings(
            settings,
            captcha_solver=solver,
            spec_loader=db_spec_loader,
            route=str(row.get("directory_route") or ""),
        )
        # Account-creation engine: only wired when a catch-all IMAP mailbox + mail
        # domain are configured (else None -> a bot:signup directory HOLDS as blocked).
        # IMAP polling is free; the paid submit is still gated by the `citations` dial.
        mailbox = imap_mailbox_from_settings(settings)
        signup_bot = citation_signup_bot_from_settings(settings, captcha_solver=solver, mailbox=mailbox)
        submitter, reason = submitter_for(
            submit_method,
            api_submitters=_api_submitters(settings),
            bot=bot,
            signup_bot=signup_bot,
        )
        if submitter is None:
            # A missing engine is HUMAN WORK, not a dead end - `disposition_for_block`
            # sends it to the operator queue rather than parking it. The one exception the
            # classifier makes is `aggregator:fed_by_*`, whose "no action needed" reason
            # means the listing arrives through the core feed and there is nothing for
            # anyone to submit; that stays `blocked` so it is not offered as work.
            fed_by_aggregator = submit_method.startswith("aggregator:fed_by_")
            code = "fed_by_aggregator" if fed_by_aggregator else "no_engine"
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
                "citation_submit_no_engine",
                citation_id=citation_id, reason=reason, disposition=state,
            )
            return {"state": state, "reason": reason}

        # A bot with no EARNED spec for this directory cannot submit. Asking before the
        # gate is what keeps an empty whitelist free rather than expensive.
        can_submit = getattr(submitter, "can_submit", None)
        if callable(can_submit) and not can_submit(job):
            # The most common row in the catalogue today: 176 bot-tier directories with
            # zero earned specs. A person does not need a spec - they have eyes - so this
            # is the single biggest source of legitimate queue work.
            state = disposition_for_block("no_verified_spec")
            store.update_citation(
                citation_id,
                {
                    "submit_status": state,
                    "blocked_reason": "no_verified_spec",
                    "error": (
                        "no verified form spec for this directory - a spec is activated "
                        "only after a dated human DOM check and one submission that "
                        "produced a public listing URL (nothing was sent, nothing charged)"
                    ),
                },
            )
            logger.info("citation_submit_no_spec", citation_id=citation_id, disposition=state)
            return {"state": state, "reason": "no_verified_spec"}

        decision = _gate().evaluate(ctx)
        if not decision.allowed:
            store.update_citation(
                citation_id, {"submit_status": "blocked", "error": f"spend_blocked:{decision.outcome}"}
            )
            logger.info("citation_submit_blocked", citation_id=citation_id, outcome=decision.outcome)
            return {"state": "blocked", "reason": decision.outcome}

        store.update_citation(citation_id, {"submit_status": "submitting"})

        try:
            result = submitter.submit(job)
        except Exception as exc:  # a provider crash still marks failed - never stuck, never re-raised
            _gate().commit(ctx, ctx.estimated_cost)  # the attempt still incurred the metered cost
            logger.exception("citation_submit_provider_error", citation_id=citation_id)
            store.update_citation(citation_id, {"submit_status": "failed", "error": f"{exc!r}"[:_ERROR_MAX]})
            return {"state": "failed", "reason": f"{exc!r}"[:_ERROR_MAX]}

        # The self-hosted bot only drives directories it has a FormSpec for, and a
        # native API can turn out not to expose the write endpoint at all (e.g.
        # Foursquare's public API has no anonymous place-create - POST /v3/places
        # 404s). With no fallback engine, that engine's own honest failed/blocked
        # result stands as-is - a queued directory it cannot reach is reported
        # truthfully rather than silently re-routed.
        _gate().commit(ctx, ctx.estimated_cost)
        fields: dict[str, Any] = {
            "submit_status": result.status,
            "proof_url": result.proof_url,
            "error": result.error[:_ERROR_MAX],
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
        try:
            # SSRF guard: `live_url` is operator/provider-supplied and this runs
            # server-side, so a private/loopback host must never be fetched.
            if not is_public_url(live_url):
                probe = LivenessProbe(status_code=None, checked_from="refused:non-public-url")
            else:
                probe = fetch(live_url)
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
        # three months.
        could_not_look = probe.status_code is None
        if could_not_look:
            fields: dict[str, Any] = {
                "verification_evidence": Json(verdict.evidence),
                "next_recheck_at": datetime.now(UTC) + timedelta(days=_UNREACHABLE_RETRY_DAYS),
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
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="citation_submit")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def citation_submit_job(citation_id: str) -> dict[str, Any]:
    """Entry point: submit one queued citation row."""
    settings = get_settings()
    return execute_citation_submit(service_citations_store(), settings, citation_id)


@celery_app.task(name="citation_liveness_recheck")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def citation_liveness_recheck_job(limit: int = 200) -> dict[str, Any]:
    """Entry point: re-confirm every citation whose re-check has come due.

    Cost: this makes plain HTTP GETs and no provider call, so it does NOT go through the
    money dial - there is nothing metered to gate. (~$41/yr for 100 clients even at the
    Serper-assisted cadence, which is why the cadence is a quality decision.)"""
    return execute_liveness_recheck(service_citations_store(), fetch=http_liveness_probe)
