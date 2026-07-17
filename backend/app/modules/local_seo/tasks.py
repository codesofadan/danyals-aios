"""Local-SEO workers: the cost-gated map-pack refresh BEAT + the read-only GBP sync.

Both tasks ride the never-stuck / never-re-raise / idempotent worker template
(``workers.tasks.context`` / ``app.modules.keyword_research.tasks``): with
``task_acks_late`` a raised exception would redeliver the job and re-run a PAID
provider pull (double spend), so a task ACKs and returns a small result dict.

``refresh_local_ranks`` (BEAT) per due row:

  R6 beat-overlap lock -> claim active rows FOR UPDATE SKIP LOCKED -> R5 cost
  pre-check (dial ``local_rank``, billed to the ROW'S CLIENT) -> provider check ->
  commit cost -> update the current row AND append history.

**THE CRITICAL INVARIANT** (pinned by ``tests/modules/local_seo/test_tasks.py``): a
provider ERROR writes NO row and must NOT set ``rank=NULL``. In this schema NULL
means "checked successfully, not in the local pack" - a real, chartable observation.
Writing a FAILED check as NULL would fabricate a ranking loss the business never
suffered: the client's report would show them dropping out of the map pack because
an API timed out. A failure is therefore counted and logged, and nothing is persisted.

A gate block DEGRADES (no provider call, honest $0, nothing written). The keyless
path degrades to the deterministic fake provider, never to a crash.

``sync_gbp_profile`` is READ-ONLY enrichment and APPROVAL-AWARE: the Google Business
Profile API is approval-gated (a new project starts at 0 QPM and approval takes days
to weeks), so with no key / no sealed OAuth token this task HOLDS cleanly rather than
failing - and the module stays fully usable on map-pack rank + citations alone. It
never posts and never replies to reviews (out of contract scope): there is no write
path here to misuse.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.local_seo.provider import LocalPackProvider, local_pack_provider_from_settings
from app.modules.local_seo.repo import ServiceLocalStore, service_local_store
from app.modules.local_seo.service import rank_delta
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore

logger = get_logger("workers.local_seo")

# The map-pack spend rides its OWN money-dial feature, so ops can throttle local rank
# off/byhand/api independently of keyword/content/audit spend. job_type is the
# free-text cost-log label.
_FEATURE = "local_rank"
_JOB_TYPE = "local_rank"

# R6: the beat-overlap lock. A Postgres ADVISORY lock (session-scoped, auto-released
# when the connection closes) keyed by a constant unique to this beat: if a previous
# tick is still draining its batch, the next tick takes no lock and returns instead of
# piling a second batch of PAID checks on top. The per-row `FOR UPDATE SKIP LOCKED`
# claim below already prevents double-CHECKING one row; this lock additionally keeps
# the beat from fanning out unboundedly under a slow provider.
_BEAT_LOCK_KEY = 803_901  # arbitrary but STABLE - a change would defeat the lock


class _NullCostCache:
    """A no-op ``CostCache``: a live rank check is not cache-keyed (it must hit the
    provider - a cached rank is a stale rank); the dial + budgets still gate it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


def check_one_ranking(
    store: ServiceLocalStore,
    provider: LocalPackProvider,
    gate: CostGate,
    settings: Settings,
    row: dict[str, Any],
) -> str:
    """Refresh ONE claimed ranking row. Returns its outcome label. Never raises.

    Outcomes: ``ranked`` (found in the pack), ``unranked`` (checked, NOT in the pack -
    persisted as an honest ``rank=NULL``), ``blocked`` (the gate said no - $0, nothing
    written), ``error`` (the check FAILED - **nothing written**), ``skipped`` (the row
    lost its profile mid-flight).
    """
    ranking_id = str(row["id"])
    client_id = str(row["client_id"])
    profile = store.profile_for_ranking(str(row["profile_id"]))
    if profile is None:
        # The profile was deleted between the claim and here; the cascade will take
        # this row too. Nothing to check against - never guess a business identity.
        logger.info("local_rank_skipped", ranking_id=ranking_id, reason="profile_gone")
        return "skipped"

    # R5: the cost pre-check BEFORE the paid call. The GateContext's client_id is the
    # ROW's client, so the check is billed to the CLIENT whose ranking it is (their
    # monthly cap governs their own tracking spend), not to a house account.
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=client_id,
        provider=provider.provider,
        estimated_cost=provider.estimated_cost(),
        job_id=ranking_id,
        job_type=_JOB_TYPE,
        client_name=str(row.get("client_name", "") or ""),
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("local_rank_blocked", ranking_id=ranking_id, outcome=decision.outcome)
        return "blocked"

    try:
        result = provider.rank(
            keyword=str(row["keyword"]),
            geo=row.get("geo"),
            place_id=(str(profile["place_id"]) if profile.get("place_id") else None),
            # The profile's own NAP name is the business identity to match in the pack;
            # the client's account name is a billing label and may differ.
            business_name=str(profile.get("nap_name") or profile.get("client_name") or ""),
        )
    except Exception:
        # A provider that raises instead of returning an error result is still a
        # FAILED check - same contract: persist nothing.
        logger.exception("local_rank_check_failed", ranking_id=ranking_id)
        return "error"

    if not result.ok:
        # THE CRITICAL BRANCH. The check failed, so we do not know this business's
        # rank - we must not say "not in the pack" (rank=NULL) on its behalf. Write
        # NOTHING: the row keeps its last known good rank and its history stays
        # truthful. The claim already stamped last_checked_at, so the queue rotates
        # and a persistently failing row cannot starve the others.
        logger.warning(
            "local_rank_provider_error", ranking_id=ranking_id, reason=result.error
        )
        return "error"

    # The call happened -> commit the spend (a failed fetch above is never charged).
    gate.commit(ctx, ctx.estimated_cost)

    previous = row.get("rank")
    previous_rank = int(previous) if previous is not None else None
    store.record_check(
        ranking_id,
        client_id=client_id,
        rank=result.rank,
        previous_rank=previous_rank,
        rank_change=rank_delta(previous_rank, result.rank),
        in_map_pack=result.in_map_pack,
        found_url=result.found_url,
        top_competitors=list(result.top_competitors),
        provider=result.provider,
    )
    return "ranked" if result.rank is not None else "unranked"


def execute_refresh(
    store: ServiceLocalStore,
    provider: LocalPackProvider,
    gate: CostGate,
    settings: Settings,
    *,
    batch: int,
) -> dict[str, Any]:
    """Claim and refresh up to ``batch`` due rankings. Never raises.

    One row's failure never stops the sweep: each row is independent, so a bad keyword
    or a mid-batch provider blip cannot wedge the beat or lose the rows behind it.
    """
    counts = {"ranked": 0, "unranked": 0, "blocked": 0, "error": 0, "skipped": 0}
    claimed = store.claim_due_rankings(batch)
    for row in claimed:
        try:
            outcome = check_one_ranking(store, provider, gate, settings, row)
        except Exception:
            # A store failure on ONE row (the only thing check_one_ranking lets
            # through) must not abandon the rest of the batch.
            logger.exception("local_rank_row_failed", ranking_id=str(row.get("id", "")))
            outcome = "error"
        counts[outcome] += 1
    logger.info("local_rank_refresh_done", claimed=len(claimed), **counts)
    return {"state": "ok", "claimed": len(claimed), **counts}


def execute_gbp_sync(
    store: ServiceLocalStore,
    settings: Settings,
    *,
    profile_id: str,
    reader: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """READ-ONLY GBP profile enrichment for ONE profile. Never raises.

    APPROVAL-AWARE by design. The Google Business Profile API is approval-gated: a new
    Cloud project starts at a 0 QPM quota and approval takes days to weeks. So the
    keyless / token-less path is not an error state - it is the EXPECTED state for
    most of this module's life, and it must HOLD:

      * no OAuth client configured  -> ``held`` (reason ``no_oauth_client``)
      * no sealed refresh token     -> ``held`` (reason ``no_oauth_token``)

    A hold writes nothing and costs nothing; map-pack rank + citations keep working,
    so the module is fully usable without GBP ever being approved. ``reader`` is the
    injected GBP read seam (absent -> hold), which keeps this core unit-testable with
    no network.
    """
    profile = store.profile_for_ranking(profile_id)
    if profile is None:
        return {"state": "error", "reason": "unknown profile", "held": False}

    if not (settings.gbp_oauth_client_id and settings.gbp_oauth_client_secret):
        logger.info("gbp_sync_held", profile_id=profile_id, reason="no_oauth_client")
        return {"state": "held", "reason": "no_oauth_client", "held": True}
    if reader is None:
        logger.info("gbp_sync_held", profile_id=profile_id, reason="no_reader")
        return {"state": "held", "reason": "no_reader", "held": True}

    try:
        fetched = reader(profile)
    except Exception:
        logger.exception("gbp_sync_failed", profile_id=profile_id)
        return {"state": "error", "reason": "gbp read failed", "held": False}
    if fetched is None:
        # The reader itself reports "no sealed token for this client" - still a HOLD,
        # not a failure: the client simply has not connected their GBP account.
        logger.info("gbp_sync_held", profile_id=profile_id, reason="no_oauth_token")
        return {"state": "held", "reason": "no_oauth_token", "held": True}

    # Recompute the completeness checklist over the FETCHED fields, so the stored
    # score always describes what GBP actually returned.
    from app.modules.local_seo.service import profile_completeness

    merged = {**profile, **fetched}
    score, audit = profile_completeness(merged)
    rating = merged.get("avg_rating")
    store.update_profile_sync(
        profile_id,
        primary_category=str(merged.get("primary_category", "") or ""),
        secondary_categories=[str(c) for c in (merged.get("secondary_categories") or [])],
        nap_name=str(merged.get("nap_name", "") or ""),
        nap_address=str(merged.get("nap_address", "") or ""),
        nap_phone=str(merged.get("nap_phone", "") or ""),
        website_uri=str(merged.get("website_uri", "") or ""),
        regular_hours=merged.get("regular_hours") or {},
        review_count=int(merged.get("review_count", 0) or 0),
        avg_rating=float(rating) if rating is not None else None,
        completeness_score=score,
        audit=audit,
    )
    logger.info("gbp_sync_done", profile_id=profile_id, completeness=score)
    return {"state": "ok", "reason": "", "held": False, "completeness": score}


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app lazily-free at module load).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


def _try_beat_lock() -> Any | None:
    """R6: take the beat-overlap advisory lock, or ``None`` if a tick still holds it.

    The returned connection OWNS the lock for its lifetime (a session-scoped
    ``pg_try_advisory_lock``), so the caller must keep it open for the whole sweep and
    close it after - which releases the lock even if the worker dies.
    """
    from app.db.database import privileged_connection

    ctx = privileged_connection()
    cur = ctx.__enter__()
    try:
        cur.execute("select pg_try_advisory_lock(%s) as locked", (_BEAT_LOCK_KEY,))
        row = cur.fetchone()
        if row and row.get("locked"):
            return ctx
    except Exception:
        logger.warning("local_rank_beat_lock_failed")
    ctx.__exit__(None, None, None)
    return None


@celery_app.task(name="refresh_local_ranks")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def refresh_local_ranks() -> dict[str, Any]:
    """BEAT task: refresh the due map-pack rankings under the R6 overlap lock.

    Wraps the pure core in a guard so the task NEVER re-raises (a redelivery would
    re-run PAID checks); a failure comes back as a result dict.
    """
    settings = get_settings()
    lock = _try_beat_lock()
    if lock is None:
        # A previous tick is still draining. Skipping is the correct behaviour: the
        # rows are still due and the next tick will take them.
        logger.info("local_rank_refresh_skipped", reason="beat_overlap")
        return {"state": "skipped", "reason": "beat_overlap", "claimed": 0}
    try:
        return execute_refresh(
            service_local_store(),
            local_pack_provider_from_settings(settings),
            _gate(),
            settings,
            batch=settings.local_rank_refresh_batch,
        )
    except Exception:
        logger.exception("refresh_local_ranks_task_failed")
        return {"state": "error", "reason": "task failed", "claimed": 0}
    finally:
        lock.__exit__(None, None, None)  # releases the advisory lock with the session


@celery_app.task(name="sync_gbp_profile")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def sync_gbp_profile(profile_id: str) -> dict[str, Any]:
    """Read-only GBP enrichment for ONE profile; HOLDS cleanly when token-less.

    No GBP reader is wired yet (the API is approval-gated - see ``execute_gbp_sync``),
    so this currently always HOLDS. That is the designed steady state, not a bug: the
    module is fully usable on map-pack rank + citations alone until approval lands.
    """
    settings = get_settings()
    try:
        return execute_gbp_sync(service_local_store(), settings, profile_id=profile_id)
    except Exception:
        logger.exception("sync_gbp_profile_task_failed", profile_id=profile_id)
        return {"state": "error", "reason": "task failed", "held": False}
