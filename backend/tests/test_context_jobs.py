"""The context tasks under the job contract: four states that finally have somewhere to go.

`execute_compaction` has always returned one of `unchanged | summarized | degraded |
error` with a reason. The Celery task discarded that distinction into a result dict
nothing read, so a cost-gate block and a successful fold were indistinguishable on any
operator surface. These tests pin the mapping.

The two that matter most:

  * a cost-gate block or a missing provider key is `degraded` with its reason - the
    watermark holds, nothing is corrupted, and the context is staler than it should be.
    Reporting that as success is how a quietly-degrading AI memory stays quiet.
  * `reconcile_context_vectors` with no vector store configured is `blocked`, not a
    silent skip. Before, a sweep that reconciled nothing looked exactly like a sweep
    that found nothing to reconcile.

Also pinned: `dispatch_context` DOES propagate its correlation id, because its child is
migrated - the payoff for doing children before parents.
"""

from __future__ import annotations

from typing import Any

import pytest

import workers.tasks.context as context_mod
import workers.tasks.context_reconcile as reconcile_mod
from tests.test_job_contract import FakeStore
from workers.tasks.context import CompactionOutcome, _reason_code, compact_context, dispatch_context
from workers.tasks.context_reconcile import reconcile_context_vectors

pytestmark = pytest.mark.unit


@pytest.fixture
def job_store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr("app.jobs.celery_task.job_runs_store", lambda: fake)
    return fake


def _wire_compaction(monkeypatch: pytest.MonkeyPatch, outcome: CompactionOutcome) -> None:
    monkeypatch.setattr(context_mod, "service_context_repo", lambda: object())
    monkeypatch.setattr(context_mod, "gated_providers_for", lambda *a, **k: object())
    monkeypatch.setattr(context_mod, "execute_compaction", lambda *a, **k: outcome)


def _outcome(state: str, **over: Any) -> CompactionOutcome:
    fields: dict[str, Any] = {
        "entity_type": "client",
        "entity_id": "c-1",
        "state": state,
        "version": 3,
        "watermark": 42,
        "events_folded": 5,
        "reason": "",
    }
    fields.update(over)
    return CompactionOutcome(**fields)


# --------------------------------------------------------------------------- #
# compact_context - the four states
# --------------------------------------------------------------------------- #
def test_a_fold_is_completed(monkeypatch: pytest.MonkeyPatch, job_store: FakeStore) -> None:
    _wire_compaction(monkeypatch, _outcome("summarized"))
    disposition = compact_context.run("client", "c-1")
    assert disposition["status"] == "completed"
    assert "folded 5 event(s)" in disposition["detail"]


def test_nothing_to_do_is_still_completed(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    _wire_compaction(monkeypatch, _outcome("unchanged", events_folded=0))
    assert compact_context.run("client", "c-1")["status"] == "completed"


@pytest.mark.parametrize(
    ("reason", "expected_code"),
    [
        ("providers_unconfigured", "providers_unconfigured"),
        ("spend_blocked:blocked_cap", "spend_blocked"),
        ("spend_blocked:blocked_halt", "spend_blocked"),
    ],
)
def test_a_held_watermark_is_degraded_with_a_groupable_code(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore, reason: str, expected_code: str
) -> None:
    """The behaviour change worth having.

    A cost-gate block holds the watermark: nothing is corrupted, and the client's AI
    memory is staler than it should be. That is a partial outcome, and it used to
    report as success. The code strips the qualifier so "how often does spend block
    compaction" is one GROUP BY rather than a grep over free text.
    """
    _wire_compaction(monkeypatch, _outcome("degraded", reason=reason))
    disposition = compact_context.run("client", "c-1")

    assert disposition["status"] == "degraded"
    row = job_store.rows[disposition["run_id"]]
    assert row["reason_code"] == expected_code
    assert reason in row["reason"], "the specific reason must survive alongside the code"


def test_a_compaction_error_is_failed(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    _wire_compaction(monkeypatch, _outcome("error", reason="ValueError('bad seq')"))
    disposition = compact_context.run("client", "c-1")
    assert disposition["status"] == "failed"
    assert job_store.dead_letters, "a failed compaction belongs in the dead-letter queue"


def test_a_clients_compactions_are_capped_against_that_client(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    """One client's 300 dirty rows must not own every worker - and because compaction
    is AI spend, the cap is also a per-tenant spend-rate limit."""
    _wire_compaction(monkeypatch, _outcome("summarized"))
    disposition = compact_context.run("client", "c-1")
    assert job_store.rows[disposition["run_id"]]["client_id"] == "c-1"


def test_a_non_client_entity_is_not_capped_against_a_tenant(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    _wire_compaction(monkeypatch, _outcome("summarized", entity_type="site", entity_id="s-1"))
    disposition = compact_context.run("site", "s-1")
    assert job_store.rows[disposition["run_id"]]["client_id"] is None


@pytest.mark.parametrize(
    ("raw", "expected"), [("", "unspecified"), ("ab", "unspecified"), ("x:y", "unspecified")]
)
def test_a_reason_code_is_never_invalid(raw: str, expected: str) -> None:
    """The code must always satisfy the contract's format, or recording WHY a job
    degraded would itself raise at the moment it mattered."""
    assert _reason_code(raw) == expected


# --------------------------------------------------------------------------- #
# dispatch_context - the fan-out that DOES carry correlation
# --------------------------------------------------------------------------- #
def test_the_dispatcher_propagates_its_correlation_id(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    """The payoff for migrating the child first.

    `compact_context` strips the reserved kwargs, so `enqueue_child` is safe here - and
    one sweep plus its N compactions become a single indexed query in `job_runs`.
    """
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(context_mod, "service_context_repo", lambda: object())
    monkeypatch.setattr(
        context_mod,
        "dispatch_due",
        lambda store, *, batch, enqueue: [enqueue("client", "c-1"), enqueue("site", "s-1")],
    )
    monkeypatch.setattr(
        context_mod,
        "enqueue_child",
        lambda ctx, task, *args, **kw: sent.append(
            {"task": task, "args": args, "correlation_id": ctx.correlation_id}
        ),
    )

    disposition = dispatch_context.run()
    assert disposition["status"] == "completed"
    assert len(sent) == 2
    assert {s["correlation_id"] for s in sent} == {disposition["correlation_id"]}


# --------------------------------------------------------------------------- #
# reconcile_context_vectors - a silent skip becomes a loud refusal
# --------------------------------------------------------------------------- #
def test_no_vector_store_is_blocked_not_skipped(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    """Before, this returned {"skipped": "providers_unconfigured"} and logged at INFO.
    A sweep that reconciled nothing looked exactly like one that found nothing."""
    monkeypatch.setattr(reconcile_mod, "context_providers_from_settings", lambda _s: None)

    disposition = reconcile_context_vectors.run()
    assert disposition["status"] == "blocked"
    row = job_store.rows[disposition["run_id"]]
    assert row["reason_code"] == "providers_unconfigured"
    assert "PINECONE_API_KEY" in row["reason"], "a refusal should say how to lift it"
    assert not job_store.dead_letters, "a refusal is not a failure"


def test_detected_but_unrepaired_drift_is_degraded(
    monkeypatch: pytest.MonkeyPatch, job_store: FakeStore
) -> None:
    """The sweep did its job and the ledger is still wrong. Reporting that as a clean
    success is how drift becomes permanent."""

    class _Report:
        def as_dict(self) -> dict[str, Any]:
            return {"drifted": 4, "checked": 100}

    monkeypatch.setattr(
        reconcile_mod, "context_providers_from_settings", lambda _s: _Bundle()
    )
    monkeypatch.setattr(reconcile_mod, "service_context_repo", lambda: object())
    monkeypatch.setattr(reconcile_mod, "run_reconcile_sweep", lambda *a, **k: _Report())
    monkeypatch.setattr(reconcile_mod, "_context_resolver", lambda _r: None)

    settings = reconcile_mod.get_settings()
    monkeypatch.setattr(settings, "context_reconcile_repair", False, raising=False)

    disposition = reconcile_context_vectors.run()
    assert disposition["status"] == "degraded"
    assert job_store.rows[disposition["run_id"]]["reason_code"] == "drift_detected_repair_disabled"


class _Bundle:
    vector_store = object()
    embedder = object()
    model_summary = "fake"
