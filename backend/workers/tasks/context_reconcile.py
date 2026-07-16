"""P6B-9: the scheduled RECONCILE SWEEP - a slow BEAT that keeps Pinecone honest.

Postgres is the source of truth; Pinecone is a DERIVED index (P6B-6). Per fold,
``sync_vectors`` already embeds only the changed chunks and GC's superseded ones
from BOTH stores, so the two are kept in step on the write path. This sweep is the
SAFETY NET for residual drift the write path cannot catch: a lost Pinecone upsert,
a delete that never landed, a manual index edit, a half-applied batch. It walks
every entity that has vectors and runs the :func:`reconcile` drift detector per
namespace, logging orphan / missing / mismatch counts; behind a flag it also
REPAIRS (delete orphans, re-embed missing/mismatched to the ledger's truth).

The core :func:`run_reconcile_sweep` is pure (injected repo + store + optional
embedder/context-resolver): no Celery, no config, so it is unit-tested with the
in-memory fakes. The thin Celery task wires the concrete service_role repo + the
real vector store (or SKIPS when keys are absent - a degraded deploy has no store
to reconcile). Like every context task it NEVER re-raises: a single entity's
failure is logged and the sweep moves on, so one bad namespace can't wedge the
beat or (with ``task_acks_late``) trigger a re-run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings
from app.logging_setup import get_logger
from app.schemas.context import ContextChunk
from app.services.context_compactor import build_context_chunks
from app.services.context_vectorsync import VectorLedger, reconcile
from integrations.context_providers import context_providers_from_settings
from integrations.embeddings import Embedder
from integrations.vectorstore import VectorStore

logger = get_logger("workers.context_reconcile")

# A resolver that returns the CURRENT (chunks, version) for an entity, or None when
# the entity has no context row to rebuild from (so nothing can be re-embedded).
ContextResolver = Callable[[str, str], "tuple[list[ContextChunk], int] | None"]


class ReconcileRepo(VectorLedger, Protocol):
    """The repo surface the sweep needs: the vector-ledger writes + the entity walk.

    ``ContextRepo`` satisfies this structurally (it is a ``VectorLedger`` and adds
    ``distinct_vector_entities`` / ``get_context_admin``).
    """

    def distinct_vector_entities(self) -> list[tuple[str, str]]: ...
    def get_context_admin(self, entity_type: str, entity_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ReconcileSweepReport:
    """The aggregate verdict of one sweep across every entity with vectors.

    ``entities`` were walked; ``healthy`` were fully in sync; ``drift`` had at least
    one discrepancy. The ``orphans`` / ``missing`` / ``mismatched`` totals sum the
    per-entity drift; the ``*_repaired`` totals are 0 unless the sweep ran with
    ``repair=True``. ``errors`` counts entities whose reconcile raised (each swallowed).
    """

    entities: int = 0
    healthy: int = 0
    drift: int = 0
    orphans: int = 0
    missing: int = 0
    mismatched: int = 0
    orphans_deleted: int = 0
    missing_repaired: int = 0
    mismatched_repaired: int = 0
    errors: int = 0

    @property
    def drift_count(self) -> int:
        """Total discrepancies flagged across every entity in the sweep."""
        return self.orphans + self.missing + self.mismatched

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable summary (the Celery task returns this)."""
        return {
            "entities": self.entities,
            "healthy": self.healthy,
            "drift": self.drift,
            "orphans": self.orphans,
            "missing": self.missing,
            "mismatched": self.mismatched,
            "orphans_deleted": self.orphans_deleted,
            "missing_repaired": self.missing_repaired,
            "mismatched_repaired": self.mismatched_repaired,
            "errors": self.errors,
        }


def run_reconcile_sweep(
    repo: ReconcileRepo,
    store: VectorStore,
    *,
    repair: bool = False,
    embedder: Embedder | None = None,
    context_for: ContextResolver | None = None,
    model: str | None = None,
) -> ReconcileSweepReport:
    """Walk every entity with vectors, reconcile each namespace, aggregate the drift.

    Pure: the repo (ledger + entity walk), the vector store, and - for repair - the
    embedder + a ``context_for`` resolver (current chunks + version per entity) are
    all injected. Detection always runs; ``repair=True`` deletes orphans and (when an
    embedder + resolver are supplied) re-embeds missing/mismatched vectors to the
    ledger's truth. Each entity is isolated in its own try/except so one failure is
    logged and skipped - the sweep NEVER raises.
    """
    entities = repo.distinct_vector_entities()
    totals: dict[str, int] = {
        "healthy": 0, "drift": 0, "orphans": 0, "missing": 0, "mismatched": 0,
        "orphans_deleted": 0, "missing_repaired": 0, "mismatched_repaired": 0, "errors": 0,
    }
    for entity_type, entity_id in entities:
        try:
            chunks: list[ContextChunk] | None = None
            version = 0
            if repair and context_for is not None:
                resolved = context_for(entity_type, entity_id)
                if resolved is not None:
                    chunks, version = resolved
            report = reconcile(
                entity_type,
                entity_id,
                store=store,
                ledger=repo,
                repair=repair,
                chunks=chunks,
                embedder=embedder if repair else None,
                version=version,
                model=model,
            )
            totals["orphans"] += len(report.orphans)
            totals["missing"] += len(report.missing)
            totals["mismatched"] += len(report.mismatched)
            totals["orphans_deleted"] += report.orphans_deleted
            totals["missing_repaired"] += report.missing_repaired
            totals["mismatched_repaired"] += report.mismatched_repaired
            if report.healthy:
                totals["healthy"] += 1
            else:
                totals["drift"] += 1
                logger.warning(
                    "context_reconcile_drift",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    orphans=len(report.orphans),
                    missing=len(report.missing),
                    mismatched=len(report.mismatched),
                    repaired=report.orphans_deleted + report.missing_repaired + report.mismatched_repaired,
                )
        except Exception:  # one bad namespace must never wedge the sweep / redeliver
            totals["errors"] += 1
            logger.exception(
                "context_reconcile_entity_failed", entity_type=entity_type, entity_id=entity_id
            )

    result = ReconcileSweepReport(entities=len(entities), **totals)
    logger.info(
        "context_reconcile_sweep",
        entities=result.entities,
        healthy=result.healthy,
        drift=result.drift,
        drift_count=result.drift_count,
        repaired=result.orphans_deleted + result.missing_repaired + result.mismatched_repaired,
        errors=result.errors,
        repair=repair,
    )
    return result


def _context_resolver(repo: ReconcileRepo) -> ContextResolver:
    """A repair resolver: rebuild an entity's CURRENT chunks + version from its
    stored context (the same deterministic chunking the embed pipeline uses), so the
    sweep can re-embed a missing/mismatched vector to exactly the ledger's truth.
    Returns ``None`` for an entity with no context row (nothing to rebuild)."""

    def _resolve(entity_type: str, entity_id: str) -> tuple[list[ContextChunk], int] | None:
        row = repo.get_context_admin(entity_type, entity_id)
        if row is None:
            return None
        summary = str(row.get("summary", "") or "")
        raw_facts = row.get("facts")
        facts = raw_facts if isinstance(raw_facts, dict) else {}
        version = int(row.get("version", 0) or 0)
        return build_context_chunks(summary, facts), version

    return _resolve


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app after the pure core, per the template)
# --------------------------------------------------------------------------- #
from app.db.context_repo import service_context_repo  # noqa: E402 - after the pure core
from workers.celery_app import celery_app  # noqa: E402 - after the pure core


@celery_app.task(name="reconcile_context_vectors")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def reconcile_context_vectors() -> dict[str, Any]:
    """BEAT task: reconcile the whole vector ledger against the store.

    Wires the service_role repo + the REAL vector store (from the key-gated bundle);
    SKIPS when providers are unconfigured (a degraded deploy has no store to
    reconcile). Repair is gated on ``context_reconcile_repair``. Never re-raises."""
    settings = get_settings()
    bundle = context_providers_from_settings(settings)
    if bundle is None:
        logger.info("context_reconcile_skipped", reason="providers_unconfigured")
        return {"skipped": "providers_unconfigured"}
    repo = service_context_repo()
    repair = settings.context_reconcile_repair
    report = run_reconcile_sweep(
        repo,
        bundle.vector_store,
        repair=repair,
        embedder=bundle.embedder if repair else None,
        context_for=_context_resolver(repo) if repair else None,
        model=bundle.model_summary,
    )
    return report.as_dict()
