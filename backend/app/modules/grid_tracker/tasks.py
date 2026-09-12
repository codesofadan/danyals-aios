"""Grid workers: run one grid, and dispatch the grids that are due.

Rides the never-stuck / never-re-raise / idempotent worker template
(``app.modules.local_seo.tasks`` / ``app.modules.rank_tracker.tasks``): with
``task_acks_late`` a raised exception redelivers the job and re-runs up to 41 PAID
probes, so the pure core returns a result dict and the Celery entry point translates
it into a ``JobOutcome``.

THREE THINGS THIS WORKER DOES DIFFERENTLY FROM THE SINGLE-LOCALE REFRESH, ALL FOR THE
SAME REASON - a grid run is expensive and PARTIAL RESULTS ARE VALUABLE.

1. **The gate is charged per point, checked before each probe.** A run is not one
   purchase, it is up to 41. Evaluating once for the whole run would let a client
   whose budget covers 6 more probes either spend 41 or spend none. Checking per point
   means the run stops exactly where the budget stops, keeps everything it bought, and
   reports the rest as unmeasured.

2. **Points are written as they are probed**, not batched at the end. A crash, a
   redeploy or a reaped lease must not discard observations that were already paid
   for. See ``repo``'s module docstring.

3. **A partial run is kept and labelled ``degraded``, never discarded.** The
   single-locale worker writes nothing on error because one failed check simply means
   "no observation today". A grid that measured 12 of 17 points has twelve real
   observations; throwing them away burns money for nothing, and silently completing
   them as if they were seventeen is the fabrication ``service.summarize`` exists to
   prevent.

**THE REFUSAL COMES BEFORE ANYTHING ELSE.** With no coordinate-capable provider the
job raises ``JobBlocked`` and no run row is opened at all. This is the
``rank_tracker`` lesson: refusing after the claim burns the slot AND fills an
append-only evidence table with synthetic positions. Grid tracking has NO fake
fallback by design (``grid_provider_from_settings`` returns ``None``, never a fake) -
a Serper-only deploy cannot run a grid, and says so.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.grid_tracker.provider import (
    GridProbeResult,
    GridProvider,
    build_grid,
    grid_provider_from_settings,
    grid_provider_is_live,
)
from app.modules.grid_tracker.repo import ServiceGridStore, service_grid_store
from app.modules.grid_tracker.service import summarize
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore

logger = get_logger("workers.grid_tracker")

# The REGISTERED dial key (app/schemas/cost.py). Its own dial rather than a reuse of
# "local_seo": the two have different cost shapes (one probe vs up to 41), and an
# operator throttling the grid must not be forced to throttle the single-locale
# surface with it. An unregistered key would make dial_mode() fall back to "off" AND
# make PATCH /cost/dials reject it - unswitchable-on, i.e. dead on arrival (e8964de).
_FEATURE = "grid_tracker"
_JOB_TYPE = "grid_probe"

# R6: the dispatch-overlap lock. Keyed by a constant unique to this beat so a tick
# arriving while the previous one is still fanning out returns instead of claiming a
# second batch of grids on top.
_DISPATCH_LOCK_KEY = 803_902  # arbitrary but STABLE - a change would defeat the lock


class _NullCostCache:
    """A no-op ``CostCache``: a live probe must hit the provider (a cached position is
    a stale position); the dial + budgets still gate it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(store=PostgresCostStore(), cache=_NullCostCache())


def execute_grid_run(
    store: ServiceGridStore,
    provider: GridProvider,
    gate: CostGate,
    settings: Settings,
    *,
    definition_id: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run ONE grid end to end. Never raises.

    ``run_id`` lets a redelivery ADOPT the run row a previous attempt opened instead
    of opening a second one - which would double-count the grid's history and leave an
    orphaned `running` row for the reaper. The caller resolves it from
    ``open_run_ids``.

    Returns a result dict whose ``state`` is one of ``completed`` / ``degraded`` /
    ``failed`` / ``blocked`` / ``skipped``.
    """
    definition = store.definition(definition_id)
    if definition is None:
        # Deleted between the claim and here; the cascade takes its runs too.
        logger.info("grid_run_skipped", definition_id=definition_id, reason="definition_gone")
        return {"state": "skipped", "reason": "definition_gone"}

    client_id = str(definition["client_id"])
    points = build_grid(
        center_lat=float(definition["center_lat"]),
        center_lng=float(definition["center_lng"]),
        shape=str(definition.get("shape") or "square"),
        size=int(definition.get("grid_size") or 5),
        rings=int(definition["rings"]),
        spacing_km=float(definition["ring_spacing_km"]),
    )

    if run_id is None:
        run_id = store.open_run(definition_id)
    if run_id is None:
        logger.warning("grid_run_not_opened", definition_id=definition_id)
        return {"state": "skipped", "reason": "run_not_opened"}

    place_id = str(definition["place_id"]) if definition.get("place_id") else None
    # The profile's own NAP name is the business identity to match in the pack; the
    # client's account name is a billing label and may differ.
    business_name = str(definition.get("nap_name") or definition.get("client_name") or "")
    keyword = str(definition["keyword"])

    probes: list[GridProbeResult] = []
    spent = 0.0
    blocked_at: int | None = None

    for point in points:
        # R5: the cost pre-check BEFORE each paid probe, billed to the grid's CLIENT.
        ctx = GateContext(
            feature_key=_FEATURE,
            client_id=client_id,
            provider=provider.provider,
            estimated_cost=provider.estimated_cost(),
            job_id=run_id,
            job_type=_JOB_TYPE,
            client_name=str(definition.get("client_name", "") or ""),
        )
        decision = gate.evaluate(ctx)
        if not decision.allowed:
            # Stop here and keep everything already measured. The remaining points are
            # counted as unmeasured by summarize(), which is the truth: the budget ran
            # out before we looked, not "the business does not rank there".
            blocked_at = len(probes)
            logger.info(
                "grid_run_blocked",
                run_id=run_id,
                outcome=decision.outcome,
                probed=len(probes),
                of=len(points),
            )
            break

        try:
            result = provider.probe(
                keyword=keyword,
                lat=point.lat,
                lng=point.lng,
                place_id=place_id,
                business_name=business_name,
            )
        except Exception:
            # A provider that RAISES instead of returning an error result is still a
            # failed probe, not an absence. One point, one failure.
            logger.exception("grid_probe_raised", run_id=run_id, label=point.label)
            result = GridProbeResult(
                status="error", error="probe_raised", provider=provider.provider
            )

        if result.measured:
            # Only a probe that actually answered is charged.
            gate.commit(ctx, ctx.estimated_cost)
            spent += ctx.estimated_cost

        probes.append(result)
        store.record_point(
            run_id,
            client_id=client_id,
            lat=point.lat,
            lng=point.lng,
            label=point.label,
            ring=point.ring,
            status=result.status,
            rank=result.rank,
            top_competitors=list(result.top_competitors),
            found_url=result.found_url,
            error=result.error,
        )

    summary = summarize(probes, points_total=len(points))
    reason = summary.reason
    if blocked_at is not None and summary.status != "completed":
        # Say WHICH constraint stopped the run. "17 probes could not be measured" and
        # "the budget stopped this run after 6 probes" send an operator to different
        # places, and only one of them is a provider problem.
        reason = (
            f"the spend gate stopped this run after {blocked_at} of {len(points)} "
            f"probe(s); every figure is over what was measured"
        )

    store.finalize_run(
        run_id,
        status=summary.status,
        reason=reason,
        points_ranked=summary.points_ranked,
        points_absent=summary.points_absent,
        points_error=summary.points_error,
        avg_rank=summary.avg_rank,
        share_top3=summary.share_top3,
        provider=provider.provider,
        cost_usd=round(spent, 4),
    )
    return {
        "state": summary.status,
        "run_id": run_id,
        "reason": reason,
        "points_total": summary.points_total,
        "points_measured": summary.points_measured,
        "points_error": summary.points_error,
        "cost_usd": round(spent, 4),
    }


def dispatch_due_grids(
    store: ServiceGridStore, *, batch: int, enqueue: Any
) -> list[str]:
    """Claim up to ``batch`` due grids and fan out one run each. Never raises."""
    claimed = store.claim_due_definitions(batch)
    out: list[str] = []
    for row in claimed:
        definition_id = str(row["id"])
        try:
            enqueue(definition_id)
            out.append(definition_id)
        except Exception:
            # One grid failing to enqueue must not strand the rest of the batch.
            logger.exception("grid_dispatch_enqueue_failed", definition_id=definition_id)
    return out


# --------------------------------------------------------------------------- #
# Celery entry points (thin; the app is imported after the pure core).
# --------------------------------------------------------------------------- #
from app.jobs import JobBlocked, JobContext, JobOutcome, JobTarget  # noqa: E402
from app.jobs.celery_task import aios_job, enqueue_child  # noqa: E402
from app.jobs.status import JobQueue  # noqa: E402
from workers.celery_app import celery_app  # noqa: E402,F401 - keeps the app importable


def _grid_run_target(definition_id: str, force: bool = False) -> JobTarget:
    """One run per grid per dispatch, unless an operator forced it.

    Unlike the nightly rank check this is NOT keyed per calendar day: a grid is run on
    demand as well as on a schedule, and two legitimate runs on the same day are
    normal (before and after a fix). The key is therefore the definition alone while a
    run is in flight - the router's ``has_open_run`` 409 and the contract's claim
    together stop a double-click becoming a double bill - and ``force`` drops it,
    because a manual re-run IS a request to spend again.
    """
    if force:
        return JobTarget(scope_id=definition_id)
    return JobTarget(idempotency_key=f"grid.run:{definition_id}", scope_id=definition_id)


@aios_job(
    name="run_grid",
    job_name="grid.run",
    # LONG: up to 41 sequential provider round trips. On the standard queue a slow
    # provider would run past the time limit and be redelivered mid-run.
    queue=JobQueue.LONG,
    # ONE attempt. Every probe is paid, so a retry is a second bill for the same
    # heat map. A redelivery finds the terminal run under the idempotency key.
    max_attempts=1,
    scope_type="grid_definition",
    target=_grid_run_target,
)
def run_grid(ctx: JobContext, definition_id: str, force: bool = False) -> JobOutcome:
    """Run one grid's probes and record the heat map."""
    settings = get_settings()
    if not grid_provider_is_live(settings):
        raise JobBlocked(
            "no_coordinate_provider",
            "no coordinate-capable provider is configured (grid tracking needs "
            "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD); refusing rather than probing "
            "by place NAME, which would return the same unlocalised result at every "
            "point and record a uniform, fictional heat map as measured evidence",
        )
    provider = grid_provider_from_settings(settings)
    if provider is None:  # pragma: no cover - guarded by grid_provider_is_live above
        raise JobBlocked("no_coordinate_provider", "no grid provider could be constructed")

    store = service_grid_store()
    # Adopt an in-flight run row rather than opening a second one on a redelivery.
    open_runs = store.open_run_ids(definition_id)
    result = execute_grid_run(
        store, provider, _gate(), settings,
        definition_id=definition_id,
        run_id=open_runs[0] if open_runs else None,
    )

    state = str(result.get("state", ""))
    if state == "completed":
        return JobOutcome.completed(
            f"measured {result.get('points_measured', 0)} point(s)", result=result
        )
    if state in {"degraded", "failed", "skipped"}:
        reason = str(result.get("reason") or f"the run finished as '{state}'")
        # `failed` and `skipped` are reported as degraded rather than raised: the run
        # row already carries the terminal state and its reason, and raising here would
        # redeliver under acks_late and re-probe everything that did succeed.
        return JobOutcome.degraded(f"grid_{state}", reason, result=result)
    return JobOutcome.degraded(
        "grid_unknown_state", f"the run finished as '{state}'", result=result
    )


@aios_job(
    name="dispatch_grid_runs",
    job_name="grid.dispatch",
    queue=JobQueue.STANDARD,
    max_attempts=2,
    retry_backoff=300.0,
    scope_type="workspace",
)
def dispatch_grid_runs(ctx: JobContext) -> JobOutcome:
    """Claim every due grid and fan out one run each.

    THE REFUSAL COMES BEFORE THE CLAIM. Claiming stamps ``last_run_at``, so a fan-out
    with no live provider would burn the slot for every grid it touched AND queue N
    child jobs that each refuse individually. Refusing first leaves the grids due.
    """
    settings = get_settings()
    if not grid_provider_is_live(settings):
        raise JobBlocked(
            "no_coordinate_provider",
            "no coordinate-capable provider is configured; not claiming due grids, "
            "which would burn their slots and queue runs that can only refuse",
        )
    dispatched = dispatch_due_grids(
        service_grid_store(),
        batch=int(settings.grid_dispatch_batch),
        enqueue=lambda did: enqueue_child(ctx, "run_grid", did),
    )
    return JobOutcome.completed(
        f"claimed {len(dispatched)} due grid(s)", result={"claimed": len(dispatched)}
    )
