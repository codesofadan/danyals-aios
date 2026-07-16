"""P6B-7: the CONTEXT COMPACTION WORKER - the event-driven, debounced,
exactly-once-ish recompaction pipeline that wires the whole context module
together and NEVER blocks a user mutation or double-spends.

The flow, end to end:

    a mutation records an activity_log row -> the AFTER-INSERT trigger (0013)
    coalesces the affected entity into public.context_dirty (debounced) ->
    the Celery BEAT fires ``dispatch_context`` every ``context_debounce_seconds``
    -> it CLAIMS due rows with ``FOR UPDATE SKIP LOCKED`` and fans out one
    ``compact_context.delay(entity)`` per claim -> the task builds cost-gated
    providers (or None, degraded) and runs the PURE ``execute_compaction`` core.

``execute_compaction`` is a pure function of an injected ``ContextStore`` seam +
a providers bundle (or ``None``), so it is unit-tested directly with a fake store
and fake providers - NO Celery, NO DB, NO network in the core. It has exactly
four terminal states and one atomic write:

* **unchanged** - no events past the watermark (idempotent redelivery): clear the
  dirty claim, touch nothing else.
* **degraded** - providers absent (keys not configured) OR the cost gate blocked
  the spend (``ContextSpendBlocked``): mark ``status='degraded'``, HOLD the
  watermark (so freshness lag stays visible), and re-arm the dirty row with a
  backoff so it retries later - never a hot spin, never a crash.
* **summarized** - the happy path: fold -> sync vectors -> ONE ``upsert_context``
  (the single atomic write). Then the RE-DIRTY CHECK: if an event landed mid-fold
  (``context_dirty.last_seq`` > the watermark just folded) leave the row pending;
  else clear it.
* **error** - any unexpected exception: mark ``status='error'``, re-arm with
  backoff, and NEVER re-raise (with ``task_acks_late`` a raised exception would
  redeliver the job and re-run the fold = double spend). Because the ONLY write to
  ``entity_context`` is the final upsert, a mid-fold crash leaves no half-written
  context.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from app.config import Settings, get_settings
from app.db.context_repo import service_context_repo
from app.logging_setup import get_logger
from app.services.context_compactor import ContextEvent, PriorContext, compact
from app.services.context_cost import (
    ContextSpendBlocked,
    GatedEmbedder,
    GatedSummarizer,
    resolve_budget_client,
)
from app.services.context_vectorsync import sync_vectors
from app.services.cost_gate import CostGate
from app.services.cost_store import PostgresCostStore
from integrations.context_providers import ContextProviders, context_providers_from_settings

logger = get_logger("workers.context")

_ERROR_MAX = 500  # cap the stored/logged error string; server-side only

CompactionState = Literal["unchanged", "degraded", "summarized", "error"]


# --------------------------------------------------------------------------- #
# Seams: the DB the core needs + a cost cache the worker's gate needs
# --------------------------------------------------------------------------- #
class ContextStore(Protocol):
    """The repo surface ``execute_compaction`` needs (``ContextRepo`` satisfies it).

    Every method here is a service_role (privileged) operation. The store doubles as
    the ``VectorLedger`` for :func:`sync_vectors` (``list_vectors`` / ``record_vector``
    / ``delete_vector``), so the worker hands ``ledger=store`` and never opens a second
    connection seam.
    """

    def get_context_for_update(
        self, entity_type: str, entity_id: str
    ) -> dict[str, Any] | None: ...

    def upsert_context(
        self,
        entity_type: str,
        entity_id: str,
        *,
        summary: str = ...,
        facts: dict[str, Any] | None = ...,
        token_budget: int = ...,
        token_count: int = ...,
        event_watermark: int = ...,
        status: str = ...,
        model: str = ...,
        checksum: str = ...,
    ) -> dict[str, Any]: ...

    def events_after(self, entity_type: str, entity_id: str, watermark: int) -> list[dict[str, Any]]: ...
    def dirty_last_seq(self, entity_type: str, entity_id: str) -> int | None: ...
    def clear_dirty(self, entity_type: str, entity_id: str) -> None: ...
    def rearm_dirty(
        self, entity_type: str, entity_id: str, *, last_seq: int, backoff_seconds: int
    ) -> None: ...
    def claim_due_dirty(self, limit: int) -> list[dict[str, Any]]: ...

    # VectorLedger surface (sync_vectors writes through the store as ledger):
    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]: ...
    def record_vector(
        self,
        entity_type: str,
        entity_id: str,
        *,
        chunk_key: str,
        pinecone_id: str,
        content_checksum: str,
        version: int,
        dim: int,
        model: str,
    ) -> dict[str, Any]: ...
    def delete_vector(
        self, entity_type: str, entity_id: str, chunk_key: str
    ) -> dict[str, Any] | None: ...


class _NullCostCache:
    """A no-op ``CostCache`` for the worker's gate.

    ``sync_vectors`` already diffs the ``context_vectors`` ledger by checksum and
    embeds ONLY changed chunks BEFORE the embedder is called, so an unchanged chunk
    never reaches the gate in the first place - the gate's own embedding cache would
    be a redundant second layer. A null cache keeps the worker sync-safe (no shared
    async Redis client) without paying for anything twice.
    """

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


# --------------------------------------------------------------------------- #
# Outcome
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CompactionOutcome:
    """The verdict of one :func:`execute_compaction` run (a small, comparable value)."""

    entity_type: str
    entity_id: str
    state: CompactionState
    version: int = 0
    watermark: int = 0
    events_folded: int = 0
    redirtied: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable summary (the Celery task returns this)."""
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "state": self.state,
            "version": self.version,
            "watermark": self.watermark,
            "events_folded": self.events_folded,
            "redirtied": self.redirtied,
            "reason": self.reason,
        }


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _prior_from_row(row: dict[str, Any]) -> PriorContext:
    """Project an ``entity_context`` row into the compactor's ``PriorContext``."""
    facts = row.get("facts")
    return PriorContext(
        summary=str(row.get("summary", "") or ""),
        facts=facts if isinstance(facts, dict) else {},
        event_watermark=int(row.get("event_watermark", 0) or 0),
        version=int(row.get("version", 0) or 0),
    )


def _event_from_row(row: dict[str, Any]) -> ContextEvent:
    """Project an ``activity_log`` row into a ``ContextEvent`` to fold."""
    return ContextEvent(
        seq=int(row["seq"]),
        kind=str(row.get("kind", "") or ""),
        action=str(row.get("action", "") or ""),
        target=str(row.get("target", "") or ""),
        meta=(str(row["meta"]) if row.get("meta") is not None else None),
        created_at=row.get("created_at"),
    )


def _degrade(
    store: ContextStore,
    settings: Settings,
    entity_type: str,
    entity_id: str,
    row: dict[str, Any],
    prior: PriorContext,
    *,
    max_seq: int,
    events_folded: int,
    reason: str,
) -> CompactionOutcome:
    """Mark the entity ``degraded``, HOLD the watermark, and re-arm with backoff.

    The status write is idempotent-guarded: it only upserts when the row is not
    ALREADY ``degraded``, so a long keyless stretch does not churn ``version`` on
    every backoff retry. The watermark is passed as the PRIOR watermark so
    ``greatest`` holds it (lag stays visible). Provider was never reached -> $0.
    """
    if row.get("status") != "degraded":
        store.upsert_context(
            entity_type,
            entity_id,
            summary=prior.summary,
            facts=dict(prior.facts),
            token_budget=settings.context_summary_token_budget,
            event_watermark=prior.event_watermark,  # HELD (greatest keeps it)
            status="degraded",
            model=str(row.get("model", "") or ""),
            checksum=str(row.get("checksum", "") or ""),
        )
    store.rearm_dirty(
        entity_type, entity_id, last_seq=max_seq, backoff_seconds=settings.context_backoff_seconds
    )
    logger.info(
        "context_compaction_degraded", entity_type=entity_type, entity_id=entity_id, reason=reason
    )
    return CompactionOutcome(
        entity_type,
        entity_id,
        "degraded",
        version=prior.version,
        watermark=prior.event_watermark,
        events_folded=events_folded,
        reason=reason,
    )


def _resolve_dirty(
    store: ContextStore,
    entity_type: str,
    entity_id: str,
    *,
    high_watermark: int,
    now_seq_source: Callable[[], int | None] | None,
) -> bool:
    """The RE-DIRTY CHECK, run AFTER the atomic summarized upsert (best-effort).

    Reads the CURRENT ``context_dirty.last_seq`` (the trigger bumps it, and flips
    ``processing`` back to ``pending``, whenever a new event lands). If it exceeds
    the watermark just folded, an event arrived mid-fold -> re-arm the row PENDING
    and immediately eligible (backoff 0) so the next beat tick re-folds it. Else the
    claim is fully drained -> clear it. Its own failures are swallowed: a summarized
    context must never be undone by an outbox hiccup (the row simply stays
    ``processing`` and is re-claimed later).
    """
    try:
        current = now_seq_source() if now_seq_source is not None else store.dirty_last_seq(
            entity_type, entity_id
        )
        if current is not None and current > high_watermark:
            store.rearm_dirty(entity_type, entity_id, last_seq=current, backoff_seconds=0)
            return True
        store.clear_dirty(entity_type, entity_id)
        return False
    except Exception:
        logger.warning(
            "context_dirty_resolve_failed", entity_type=entity_type, entity_id=entity_id
        )
        return False


def _safe_mark_error(
    store: ContextStore, settings: Settings, entity_type: str, entity_id: str
) -> None:
    """Best-effort: flip the row to ``status='error'`` (holding its content) and
    re-arm with backoff. Every step is suppressed - the error path must not raise."""
    try:
        row = store.get_context_for_update(entity_type, entity_id)
        if row is not None:
            prior = _prior_from_row(row)
            store.upsert_context(
                entity_type,
                entity_id,
                summary=prior.summary,
                facts=dict(prior.facts),
                token_budget=settings.context_summary_token_budget,
                event_watermark=prior.event_watermark,  # HELD
                status="error",
                model=str(row.get("model", "") or ""),
                checksum=str(row.get("checksum", "") or ""),
            )
    except Exception:
        logger.warning("context_error_mark_failed", entity_type=entity_type, entity_id=entity_id)
    try:
        store.rearm_dirty(
            entity_type, entity_id, last_seq=0, backoff_seconds=settings.context_backoff_seconds
        )
    except Exception:
        logger.warning("context_error_rearm_failed", entity_type=entity_type, entity_id=entity_id)


# --------------------------------------------------------------------------- #
# The pure core
# --------------------------------------------------------------------------- #
def execute_compaction(
    store: ContextStore,
    providers: ContextProviders | None,
    entity_type: str,
    entity_id: str,
    *,
    settings: Settings,
    now_seq_source: Callable[[], int | None] | None = None,
) -> CompactionOutcome:
    """Fold one entity's un-absorbed events into its living context. NEVER raises.

    Pure of Celery/DB/network (all injected). ``providers is None`` -> degraded;
    a ``ContextSpendBlocked`` from the gated providers -> degraded; any other
    exception -> error. The single write to ``entity_context`` is the final
    ``upsert_context`` (summarized), so a mid-fold failure leaves no half-write.
    """
    try:
        row = store.get_context_for_update(entity_type, entity_id)
        if row is None:
            # Create the pending base row so the fold has a versioned prior.
            row = store.upsert_context(entity_type, entity_id, status="pending")
        prior = _prior_from_row(row)

        event_rows = store.events_after(entity_type, entity_id, prior.event_watermark)
        if not event_rows:
            # No-op (idempotent redelivery / watermark already caught up).
            store.clear_dirty(entity_type, entity_id)
            return CompactionOutcome(
                entity_type,
                entity_id,
                "unchanged",
                version=prior.version,
                watermark=prior.event_watermark,
            )

        events = [_event_from_row(r) for r in event_rows]
        max_seq = max(event.seq for event in events)

        if providers is None:
            return _degrade(
                store, settings, entity_type, entity_id, row, prior,
                max_seq=max_seq, events_folded=len(events), reason="providers_unconfigured",
            )

        try:
            result = compact(
                prior,
                events,
                providers.summarizer,
                token_budget=settings.context_summary_token_budget,
                max_facts=settings.context_max_facts,
                model=providers.model_summary,
            )
            new_version = prior.version + 1
            sync_vectors(
                entity_type,
                entity_id,
                result.chunks,
                version=new_version,
                embedder=providers.embedder,
                store=providers.vector_store,
                ledger=store,
                model=providers.model_summary,
            )
            persisted = store.upsert_context(
                entity_type,
                entity_id,
                summary=result.new_summary,
                facts=result.new_facts,
                token_budget=settings.context_summary_token_budget,
                token_count=result.token_count,
                event_watermark=result.high_watermark,
                status="summarized",
                model=providers.model_summary,
                checksum=result.checksum,
            )
        except ContextSpendBlocked as exc:
            # The cost gate denied the spend: NO provider call happened, and the
            # atomic upsert has not run -> no half-write. Degrade, don't crash.
            return _degrade(
                store, settings, entity_type, entity_id, row, prior,
                max_seq=max_seq, events_folded=len(events),
                reason=f"spend_blocked:{exc.outcome}",
            )

        # Context is durably summarized; the outbox is best-effort from here.
        redirtied = _resolve_dirty(
            store, entity_type, entity_id,
            high_watermark=result.high_watermark, now_seq_source=now_seq_source,
        )
        return CompactionOutcome(
            entity_type,
            entity_id,
            "summarized",
            version=int(persisted.get("version", new_version) or new_version),
            watermark=result.high_watermark,
            events_folded=len(events),
            redirtied=redirtied,
        )
    except Exception as exc:  # never re-raise: acks_late would redeliver = double spend
        logger.exception(
            "context_compaction_error", entity_type=entity_type, entity_id=entity_id
        )
        _safe_mark_error(store, settings, entity_type, entity_id)
        return CompactionOutcome(
            entity_type, entity_id, "error", reason=f"{exc!r}"[:_ERROR_MAX]
        )


# --------------------------------------------------------------------------- #
# The pure dispatch core (claim + fan-out; NO Celery import)
# --------------------------------------------------------------------------- #
def dispatch_due(
    store: ContextStore, *, batch: int, enqueue: Callable[[str, str], Any]
) -> list[tuple[str, str]]:
    """Claim up to ``batch`` due dirty rows (SKIP LOCKED) and ``enqueue`` one compaction
    per claim. Pure: the store does the atomic claim, ``enqueue`` is injected (the task
    passes ``compact_context.delay``), so this is unit-testable with fakes."""
    dispatched: list[tuple[str, str]] = []
    for row in store.claim_due_dirty(batch):
        entity_type = str(row["entity_type"])
        entity_id = str(row["entity_id"])
        enqueue(entity_type, entity_id)
        dispatched.append((entity_type, entity_id))
    return dispatched


# --------------------------------------------------------------------------- #
# Provider wiring (cost-gated bundle or None)
# --------------------------------------------------------------------------- #
def gated_providers_for(
    settings: Settings, entity_type: str, entity_id: str
) -> ContextProviders | None:
    """The key-gated providers bundle with its summarizer + embedder wrapped in the
    cost gate, or ``None`` (degraded) when keys are absent.

    The gate meters every context AI call against the money-dial / client cap / daily
    spend-stop (a block raises ``ContextSpendBlocked``, which the worker degrades on).
    The budget client is resolved from the entity; the cache is null (see
    ``_NullCostCache``)."""
    bundle = context_providers_from_settings(settings)
    if bundle is None:
        return None
    client_id = resolve_budget_client(entity_type, entity_id)
    gate = CostGate(PostgresCostStore(), _NullCostCache())
    entity = (entity_type, entity_id)
    gated_summarizer = GatedSummarizer(
        bundle.summarizer, gate, settings=settings, client_id=client_id, entity=entity
    )
    gated_embedder = GatedEmbedder(
        bundle.embedder, gate, settings=settings, client_id=client_id, entity=entity
    )
    return replace(bundle, summarizer=gated_summarizer, embedder=gated_embedder)


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app lazily-free at module load)
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="compact_context")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def compact_context(entity_type: str, entity_id: str) -> dict[str, Any]:
    """Compact ONE entity. Wires the concrete store + gated providers and runs the
    pure core, which never raises - so this task never re-raises (acks_late-safe)."""
    settings = get_settings()
    store = service_context_repo()
    providers = gated_providers_for(settings, entity_type, entity_id)
    outcome = execute_compaction(store, providers, entity_type, entity_id, settings=settings)
    return outcome.as_dict()


@celery_app.task(name="dispatch_context")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def dispatch_context() -> dict[str, Any]:
    """BEAT task: claim due dirty rows (SKIP LOCKED) and fan out one
    ``compact_context`` per claim. The debounce lives in ``context_dirty`` +
    ``next_eligible_at``; this just drains what is due."""
    settings = get_settings()
    store = service_context_repo()
    dispatched = dispatch_due(
        store,
        batch=settings.context_dispatch_batch,
        enqueue=lambda et, eid: compact_context.delay(et, eid),
    )
    return {"claimed": len(dispatched)}
