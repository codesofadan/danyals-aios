"""P6B-8: the CONTEXT RETRIEVAL API + FRESHNESS GATE - the fast, RLS-scoped
contract the AI layer calls to get an entity's CURRENT context.

``get_context`` is the ONE door the Content / audit-narrative / assistant modules
read through: it returns the living ``summary`` + folded ``facts`` + the top-k
relevant ``chunks`` alongside an EXPLICIT freshness signal (``lag`` / ``stale`` /
``status`` / ``version``), so a caller always knows whether it is reading current
context. It is a pure orchestration over the injected ``ContextRepo`` (RLS reads +
service-role writes) + a providers bundle (or ``None``, degraded).

THE FRESHNESS POLICY (decision D) - never block, never lie, never crash:

* ``lag = max(latest_seq - event_watermark, 0)`` where ``latest_seq`` is the
  entity's highest ``activity_log.seq``; ``stale`` is ``lag > 0`` OR a
  non-``summarized`` status (a ``pending``/``degraded``/``error`` context is
  honestly stale regardless of the arithmetic).
* **default (``fresh=False``)** - serve the CURRENT context immediately with its
  ``stale``/``lag``, and (best-effort) RE-ARM the entity's dirty row so the
  compaction worker catches up. The read NEVER blocks on compaction.
* **``fresh=True`` and stale** - run a bounded, cost-gated SYNCHRONOUS
  ``execute_compaction`` (the same pure core the worker uses), then serve the
  freshened context. ``execute_compaction`` never raises - a blocked cost gate
  degrades and any error is caught - so if the spend is blocked OR providers are
  absent the endpoint still returns 200 with ``stale=true`` (it does NOT error).

RETRIEVAL is namespace-scoped so it can never cross tenants: a ``query`` (with
live providers, on a ``summarized`` context) is embedded with the gated embedder
and matched against ``vectorstore.query(namespace_for(entity), ..., top_k)`` -
the entity's OWN namespace only. Vectors carry no text, so each hit's ``chunk_key``
is mapped back to its CURRENT content via the deterministic chunk rebuild. No
query / no providers / degraded => ``chunks=[]`` (summary + facts still serve).
"""

from __future__ import annotations

from typing import Any, cast

from app.config import Settings
from app.db.context_repo import ContextRepo
from app.logging_setup import get_logger
from app.schemas.context import (
    _ENTITY_TYPES,
    _STALE_STATUSES,
    _STATUSES,
    ContextChunk,
    ContextEntityType,
    ContextHealth,
    ContextStatus,
    ContextView,
    OrgContextHealth,
)
from app.services.context_compactor import build_context_chunks
from app.services.context_cost import ContextSpendBlocked
from app.services.context_vectorsync import namespace_for
from integrations.context_providers import ContextProviders
from workers.tasks.context import execute_compaction

logger = get_logger("app.context_service")


class UnknownEntityTypeError(ValueError):
    """Raised when ``entity_type`` is not a ``context_entity`` enum value.

    The router maps this to a 422 - a request for a bogus entity kind is a
    validation error, never a silent empty read.
    """

    def __init__(self, entity_type: str) -> None:
        super().__init__(f"unknown entity_type '{entity_type}' (expected one of {sorted(_ENTITY_TYPES)})")
        self.entity_type = entity_type


def validate_entity_type(entity_type: str) -> None:
    """Guard: reject any ``entity_type`` outside the ``context_entity`` enum."""
    if entity_type not in _ENTITY_TYPES:
        raise UnknownEntityTypeError(entity_type)


def _freshness(row: dict[str, Any] | None, latest_seq: int) -> tuple[int, int, bool, str, int]:
    """Compute ``(event_watermark, lag, stale, status, version)`` for a context row.

    An ABSENT row is an entity never compacted: watermark 0, lag == latest_seq,
    stale iff any events exist, status ``pending``. A PRESENT row is stale when it
    lags OR its status is not a clean ``summarized`` (see ``_STALE_STATUSES``).
    """
    if row is None:
        lag = max(latest_seq, 0)
        return 0, lag, lag > 0, "pending", 0
    watermark = int(row.get("event_watermark", 0) or 0)
    version = int(row.get("version", 0) or 0)
    raw_status = row.get("status")
    status = raw_status if raw_status in _STATUSES else "pending"
    lag = max(latest_seq - watermark, 0)
    stale = lag > 0 or status in _STALE_STATUSES
    return watermark, lag, stale, str(status), version


def _rearm_best_effort(repo: ContextRepo, entity_type: str, entity_id: str, latest_seq: int) -> None:
    """Re-arm the entity's dirty row eligible NOW so the worker catches up (default,
    async freshness path). Best-effort: a failure here must NEVER fail the read."""
    try:
        repo.rearm_dirty(entity_type, entity_id, last_seq=latest_seq, backoff_seconds=0)
    except Exception:  # never block/fail the read on an outbox hiccup
        logger.warning("context_rearm_failed", entity_type=entity_type, entity_id=entity_id)


def _retrieve_chunks(
    entity_type: str,
    entity_id: str,
    query: str | None,
    row: dict[str, Any] | None,
    providers: ContextProviders | None,
    settings: Settings,
) -> list[ContextChunk]:
    """Top-k relevant chunks for ``query`` in the entity's OWN namespace, or ``[]``.

    Returns ``[]`` (summary + facts still serve) when there is no query, no live
    providers, or the context is not ``summarized`` (a pending/degraded/error
    context has no reliable vectors). Otherwise embeds the query with the gated
    embedder and queries ONLY ``namespace_for(entity)`` - never a foreign tenant -
    then maps each hit's ``chunk_key`` to its current content. A blocked cost gate
    or any store hiccup degrades to ``[]``; it never crashes the request.
    """
    if not query or providers is None or row is None:
        return []
    if str(row.get("status")) != "summarized":
        return []
    try:
        vectors = providers.embedder.embed([query])
        if not vectors:
            return []
        namespace = namespace_for(entity_type, entity_id)
        matches = providers.vector_store.query(namespace, vectors[0], top_k=settings.context_topk)
        summary = str(row.get("summary", "") or "")
        raw_facts = row.get("facts")
        facts: dict[str, Any] = raw_facts if isinstance(raw_facts, dict) else {}
        content_by_key = {c.chunk_key: c.content for c in build_context_chunks(summary, facts)}
        return [
            ContextChunk(
                chunk_key=str(m.metadata.get("chunk_key", "")),
                content=content_by_key.get(str(m.metadata.get("chunk_key", "")), ""),
                score=float(m.score),
            )
            for m in matches
        ]
    except ContextSpendBlocked:
        logger.info("context_retrieval_spend_blocked", entity_type=entity_type, entity_id=entity_id)
        return []
    except Exception:  # retrieval is best-effort: summary+facts must still serve
        logger.warning("context_retrieval_failed", entity_type=entity_type, entity_id=entity_id)
        return []


def get_context(
    entity_type: str,
    entity_id: str,
    *,
    query: str | None = None,
    fresh: bool = False,
    providers: ContextProviders | None,
    repo: ContextRepo,
    settings: Settings,
) -> ContextView:
    """The retrieval contract: an entity's CURRENT context + freshness + top-k chunks.

    Blocking (psycopg is sync); the caller offloads with ``asyncio.to_thread``. See
    the module docstring for the freshness policy: default is non-blocking (serve +
    re-arm), ``fresh=True`` on a stale context runs a bounded cost-gated sync
    recompaction, and neither path ever raises out of the request.
    """
    validate_entity_type(entity_type)

    row = repo.get_entity_context(entity_type, entity_id)
    latest = repo.latest_seq(entity_type, entity_id)
    _, _, stale, _, _ = _freshness(row, latest)

    if stale:
        if fresh and providers is not None:
            # Bounded, cost-gated, SYNCHRONOUS recompaction. Never raises: a blocked
            # gate degrades and any error is caught inside execute_compaction.
            execute_compaction(repo, providers, entity_type, entity_id, settings=settings)
            row = repo.get_entity_context(entity_type, entity_id)
            latest = repo.latest_seq(entity_type, entity_id)
        else:
            # Default (or fresh with no providers): serve stale, nudge the worker.
            _rearm_best_effort(repo, entity_type, entity_id, latest)

    watermark, lag, stale, status, version = _freshness(row, latest)
    chunks = _retrieve_chunks(entity_type, entity_id, query, row, providers, settings)
    raw_facts = row.get("facts") if row else None
    facts: dict[str, Any] = raw_facts if isinstance(raw_facts, dict) else {}
    return ContextView(
        entity_type=cast(ContextEntityType, entity_type),  # validated by validate_entity_type
        entity_id=entity_id,
        summary=str(row.get("summary", "") or "") if row else "",
        facts=facts,
        chunks=chunks,
        version=version,
        status=cast(ContextStatus, status),  # normalized to the enum in _freshness
        event_watermark=watermark,
        latest_seq=latest,
        lag=lag,
        stale=stale,
        updated_at=(row.get("updated_at") if row else None),
    )


def context_health(entity_type: str, entity_id: str, *, repo: ContextRepo) -> ContextHealth:
    """Per-entity freshness signal (lag / stale / status / version). Read-only:
    unlike ``get_context`` it never re-arms or recompacts."""
    validate_entity_type(entity_type)
    latest = repo.latest_seq(entity_type, entity_id)
    row = repo.get_entity_context(entity_type, entity_id)
    if row is None:
        return ContextHealth(
            entity_type=entity_type,  # type: ignore[arg-type]  # validated above
            entity_id=entity_id,
            status="pending",
            version=0,
            event_watermark=0,
            latest_seq=latest,
            lag=max(latest, 0),
            stale=latest > 0,
            updated_at=None,
        )
    return ContextHealth.from_row(row, latest)


def org_context_health(*, repo: ContextRepo) -> OrgContextHealth:
    """The org-wide freshness rollup: worst lag + stale/degraded/error counts over
    every context the staff caller may see. Two reads (contexts + grouped latest
    seqs), joined in Python - never ``N + 1``."""
    rows = repo.list_contexts()
    latest_by_entity = repo.latest_seqs()
    stale = degraded = error = worst_lag = 0
    for row in rows:
        key = (str(row.get("entity_type")), str(row.get("entity_id")))
        health = ContextHealth.from_row(row, latest_by_entity.get(key, 0))
        if health.stale:
            stale += 1
        if health.status == "degraded":
            degraded += 1
        if health.status == "error":
            error += 1
        worst_lag = max(worst_lag, health.lag)
    return OrgContextHealth(
        total=len(rows), stale=stale, degraded=degraded, error=error, worst_lag=worst_lag
    )
