"""P6B-5 gate: the COMPACTION ENGINE - deterministic fact supersession + a
bounded living summary.

The proofs, all with the deterministic ``FakeSummarizer`` (no network, no keys):

* **Supersession** - a later event's value for a key overwrites the earlier one
  by ``seq``; the superseded value is GONE from facts AND from the prose.
* **Bound** - ``token_count <= token_budget`` even for many/large events.
* **Idempotent** - re-folding already-folded events yields an identical checksum
  (so the worker won't bump ``version`` pointlessly).
* **Fact cap** - more than ``max_facts`` distinct keys keeps exactly the most
  recent ``max_facts`` by ``seq``.
* **Prior carry-forward** - an untouched prior key survives; a touched one updates.
"""

from __future__ import annotations

import json

import pytest

from app.services.context_compactor import (
    CompactionResult,
    ContextEvent,
    PriorContext,
    compact,
)
from integrations.llm import FakeSummarizer

pytestmark = pytest.mark.unit

_MODEL = "claude-haiku-4-5"


def _fact_blob(result: CompactionResult) -> str:
    """Every fact key+value rendered as one string (for absence assertions)."""
    return json.dumps(result.new_facts, sort_keys=True, default=str)


def _run(
    prior: PriorContext,
    events: list[ContextEvent],
    *,
    token_budget: int = 200,
    max_facts: int = 32,
) -> CompactionResult:
    return compact(
        prior,
        events,
        FakeSummarizer(),
        token_budget=token_budget,
        max_facts=max_facts,
        model=_MODEL,
    )


# --------------------------------------------------------------------------- #
# Supersession - the heart of "never stale"
# --------------------------------------------------------------------------- #
def test_later_event_supersedes_earlier_by_seq() -> None:
    """tier A (seq 10) -> B (seq 20): new_facts["tier"] == "B" and NO trace of A."""
    events = [
        ContextEvent(seq=10, kind="client", action="set delivery tier", target="client-42", meta="A"),
        ContextEvent(seq=20, kind="client", action="set delivery tier", target="client-42", meta="B"),
    ]
    result = _run(PriorContext(), events)

    # The superseding fact is B; the superseded value A is gone from facts...
    assert result.new_facts["tier"] == "B"
    assert result.new_facts["delivery_tier"] == "B"
    assert "A" not in _fact_blob(result)
    # ...and, because the prompt carries only the folded facts (never the raw
    # superseded meta), A never reaches the FakeSummarizer's prose either.
    assert "A" not in result.new_summary
    assert result.high_watermark == 20


def test_out_of_order_older_event_does_not_override_newer() -> None:
    """A lower-seq event supplied AFTER a higher-seq one must not win."""
    events = [
        ContextEvent(seq=20, kind="client", action="set delivery tier", target="c", meta="B"),
        ContextEvent(seq=10, kind="client", action="set delivery tier", target="c", meta="A"),
    ]
    result = _run(PriorContext(), events)
    assert result.new_facts["tier"] == "B"  # seq 20 wins regardless of list order
    assert result.high_watermark == 20


# --------------------------------------------------------------------------- #
# Bound - the token budget is a guarantee, not a hint
# --------------------------------------------------------------------------- #
def test_token_count_never_exceeds_budget() -> None:
    events = [
        ContextEvent(
            seq=i,
            kind="task",
            action="assigned a very long task description " * 20,
            target=f"client-{i} " * 20,
        )
        for i in range(1, 60)
    ]
    for budget in (8, 16, 64, 200):
        result = _run(PriorContext(summary="x" * 5000), events, token_budget=budget)
        assert result.token_count <= budget


# --------------------------------------------------------------------------- #
# Idempotent - re-folding is a no-op the worker can detect
# --------------------------------------------------------------------------- #
def test_idempotent_refold_same_checksum() -> None:
    events = [
        ContextEvent(seq=10, kind="audit", action="ran an audit", target="https://a.example", meta="90"),
        ContextEvent(seq=20, kind="task", action="assigned a task", target="Acme"),
    ]
    first = _run(PriorContext(), events)

    # The worker persists ``first`` then re-fires; with the watermark caught up
    # there are NO new events, so the fold returns the prior verbatim -> identical
    # checksum and facts -> no spurious version bump.
    prior = PriorContext(
        summary=first.new_summary,
        facts=first.new_facts,
        event_watermark=first.high_watermark,
        version=1,
    )
    second = _run(prior, [])
    assert second.checksum == first.checksum
    assert second.new_facts == first.new_facts
    assert second.new_summary == first.new_summary

    # Two identical calls are also byte-for-byte identical (pure + deterministic).
    assert _run(PriorContext(), events).checksum == first.checksum


# --------------------------------------------------------------------------- #
# Fact cap - recency eviction keeps the most recent max_facts keys
# --------------------------------------------------------------------------- #
def test_fact_cap_keeps_most_recent_by_seq() -> None:
    # Five distinct single-key events, seq 1..5.
    events = [
        ContextEvent(seq=1, kind="audit", action="ran an audit", target="url"),        # last_audit
        ContextEvent(seq=2, kind="task", action="assigned a task", target="t"),         # last_task
        ContextEvent(seq=3, kind="content", action="approved content", target="c"),     # last_content
        ContextEvent(seq=4, kind="access", action="rotated a vault key", target="k"),   # last_access
        ContextEvent(seq=5, kind="login", action="signed in", target="user-9"),         # last_login
    ]
    result = _run(PriorContext(), events, max_facts=3)

    assert len(result.new_facts) == 3
    assert set(result.new_facts) == {"last_content", "last_access", "last_login"}  # seq 3,4,5
    assert "last_audit" not in result.new_facts  # seq 1 evicted
    assert "last_task" not in result.new_facts   # seq 2 evicted


# --------------------------------------------------------------------------- #
# Prior carry-forward - untouched keys survive; touched keys update
# --------------------------------------------------------------------------- #
def test_prior_facts_carry_forward_and_update() -> None:
    prior = PriorContext(
        summary="known context",
        facts={"tier": "starter", "last_audit": "https://old.example"},
        event_watermark=5,
    )
    events = [
        ContextEvent(seq=6, kind="audit", action="ran an audit", target="https://new.example"),
    ]
    result = _run(prior, events)

    assert result.new_facts["tier"] == "starter"                 # untouched -> survives
    assert result.new_facts["last_audit"] == "https://new.example"  # touched -> updated
    assert result.high_watermark == 6


# --------------------------------------------------------------------------- #
# Chunking - a summary chunk + one per fact group, each checksummed
# --------------------------------------------------------------------------- #
def test_chunks_cover_summary_and_fact_groups_with_checksums() -> None:
    events = [
        ContextEvent(seq=10, kind="client", action="set delivery tier", target="c", meta="pro"),
        ContextEvent(seq=11, kind="audit", action="ran an audit", target="https://a.example", meta="88"),
    ]
    result = _run(PriorContext(), events)
    keys = {chunk.chunk_key for chunk in result.chunks}
    assert "summary" in keys
    assert "facts:client" in keys and "facts:audit" in keys
    for chunk in result.chunks:
        assert chunk.content_checksum  # every chunk carries a sha256
    # The checksum is excluded from the wire projection.
    assert "content_checksum" not in result.chunks[0].model_dump()
