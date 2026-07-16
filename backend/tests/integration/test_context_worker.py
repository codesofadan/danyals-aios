"""Integration: the P6B-7 CONTEXT COMPACTION WORKER, FULL PIPELINE with FAKES,
against local Postgres.

Proves the whole backbone on real SQL (the unit suite stops at the fake store):

    activity_log INSERT (service_role) -> the 0013 AFTER-INSERT trigger enqueues
    ONE context_dirty row -> execute_compaction (fakes injected, via the real
    service_context_repo) folds the events -> entity_context is 'summarized', its
    event_watermark == the max activity seq, summary + facts are populated, the
    context_vectors ledger has rows, and the dirty row is CLEARED.

A second run with no new events => 'unchanged' (idempotent), nothing re-embedded.

Runs against DATABASE_ADMIN_URL (service_role); auto-skips when unset. Everything
seeded is torn down in a finally.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest

from app.config import get_settings
from app.db.context_repo import service_context_repo
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from integrations.context_providers import providers_for_tests
from workers.tasks.context import execute_compaction

pytestmark = pytest.mark.integration


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


def _insert_event(
    cur: Any, *, action: str, kind: str, target: str, meta: str | None, entity_id: str
) -> int:
    cur.execute(
        "insert into public.activity_log (actor_name, kind, action, target, meta, "
        "entity_type, entity_id) "
        "values ('Ctx Worker Bot', %(kind)s, %(action)s, %(target)s, %(meta)s, "
        "'client'::public.context_entity, %(entity_id)s) returning seq",
        {"kind": kind, "action": action, "target": target, "meta": meta, "entity_id": entity_id},
    )
    return int(cur.fetchone()["seq"])


def test_full_pipeline_activity_to_summarized_context() -> None:
    settings = _require_local_stack()

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    tag = uuid4().hex[:8]
    entity_id = str(uuid4())
    entity = ("client", entity_id)
    providers = providers_for_tests()
    store = service_context_repo()

    try:
        # --- activity -> dirty: two linked events fire the trigger (one dirty row) ---
        with privileged_connection(pool=admin_pool) as cur:
            seq1 = _insert_event(
                cur, kind="audit", action=f"ran audit {tag}",
                target="https://acme.test", meta="87", entity_id=entity_id,
            )
            seq2 = _insert_event(
                cur, kind="client", action=f"set tier {tag}",
                target="acme", meta="Growth", entity_id=entity_id,
            )
        max_seq = max(seq1, seq2)

        # The trigger enqueued exactly one dirty row (pending) for the entity.
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "select last_seq, event_count, status from public.context_dirty "
                "where entity_type = 'client' and entity_id = %s",
                (entity_id,),
            )
            dirty = cur.fetchone()
        assert dirty is not None
        assert int(dirty["last_seq"]) == max_seq
        assert int(dirty["event_count"]) == 2
        assert dirty["status"] == "pending"

        # --- compaction: fold the events with FAKES injected (no external keys) ---
        out = execute_compaction(store, providers, *entity, settings=settings)

        assert out.state == "summarized"
        assert out.events_folded == 2
        assert out.watermark == max_seq

        # entity_context is now summarized, watermark advanced, summary + facts set.
        ctx = store.get_context_for_update("client", entity_id)
        assert ctx is not None
        assert ctx["status"] == "summarized"
        assert int(ctx["event_watermark"]) == max_seq
        assert ctx["summary"]  # bounded prose written by the FakeSummarizer
        facts = ctx["facts"]
        assert facts["last_audit"] == "https://acme.test"
        assert facts["last_audit_score"] == 87
        assert facts["tier"] == "Growth"

        # the context_vectors ledger has rows (summary chunk + fact-group chunks).
        vectors = store.list_vectors("client", entity_id)
        assert vectors
        assert any(v["chunk_key"] == "summary" for v in vectors)

        # the dirty claim is CLEARED (no new events arrived mid-fold).
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "select count(*) as n from public.context_dirty "
                "where entity_type = 'client' and entity_id = %s",
                (entity_id,),
            )
            assert int(cur.fetchone()["n"]) == 0

        # --- second run, no new events => unchanged (idempotent), no re-embed ---
        version_before = int(ctx["version"])
        vectors_before = len(vectors)
        out2 = execute_compaction(store, providers, *entity, settings=settings)
        assert out2.state == "unchanged"

        ctx2 = store.get_context_for_update("client", entity_id)
        assert ctx2 is not None
        assert int(ctx2["version"]) == version_before  # NOT bumped
        assert len(store.list_vectors("client", entity_id)) == vectors_before
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            cur.execute("delete from public.context_vectors where entity_id = %s", (entity_id,))
            cur.execute("delete from public.entity_context where entity_id = %s", (entity_id,))
            cur.execute("delete from public.context_dirty where entity_id = %s", (entity_id,))
            cur.execute("delete from public.activity_log where action like %s", (f"%{tag}%",))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
