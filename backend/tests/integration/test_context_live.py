"""P6B-10 live integration: the FULL context pipeline against the REAL providers.

This is the dormant, key-gated twin of ``test_context_worker.py`` (which runs the
same pipeline with FAKES against local Postgres). It auto-SKIPS unless ALL of the
real provider keys are configured - ``ANTHROPIC_API_KEY`` AND ``EMBEDDINGS_API_KEY``
AND ``PINECONE_API_KEY`` + ``PINECONE_INDEX`` (mirroring ``test_audit_engine_live``'s
env-guard) - plus the local Postgres DSNs. When the user supplies keys it runs end
to end with the REAL Anthropic / Voyage / Pinecone clients against local Postgres:

    seed activity -> the 0013 trigger enqueues a dirty row -> execute_compaction with
    the REAL ``context_providers_from_settings`` bundle folds the events -> assert
    entity_context is 'summarized', the watermark advanced, REAL embeddings were
    upserted to the REAL Pinecone namespace, get_context(query=...) returns a real
    top-k, and a SUPERSEDED fact value is gone from Pinecone (the re-embed overwrote
    it in place; the old value is nowhere in the retrieved chunk).

Everything seeded (the Pinecone namespace's vectors + all DB rows) is torn down in a
finally. Keys are DEFERRED, so today this SKIPS cleanly - it never fails the gate.
"""

from __future__ import annotations

import contextlib
import time
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
from app.services.context_service import get_context
from app.services.context_vectorsync import namespace_for
from integrations.context_providers import ContextProviders, context_providers_from_settings
from integrations.errors import ProviderNotConfiguredError
from workers.tasks.context import execute_compaction

pytestmark = pytest.mark.integration


def _require_live() -> Any:
    """Skip unless BOTH the local Postgres DSNs and ALL real provider keys are set.

    This is the env-guard that keeps the test dormant until the user supplies keys:
    the assertions below only ever run with the REAL Anthropic / Voyage / Pinecone
    clients wired to a REAL local Postgres.
    """
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    if not (
        settings.anthropic_api_key
        and settings.embeddings_api_key
        and settings.pinecone_api_key
        and settings.pinecone_index
    ):
        pytest.skip(
            "context providers not configured "
            "(ANTHROPIC_API_KEY + EMBEDDINGS_API_KEY + PINECONE_API_KEY + PINECONE_INDEX)"
        )
    return settings


def _real_providers(settings: Any) -> ContextProviders:
    """Build the REAL bundle; skip (not fail) if the optional ``[ai]`` SDKs are absent.

    Keys can be present while the ``[ai]`` extra is not installed - that is a
    configuration gap, not a product failure, so it SKIPS with the fix named.
    """
    try:
        bundle = context_providers_from_settings(settings)
    except ProviderNotConfiguredError as exc:
        pytest.skip(f"AI SDKs not installed for the live run: {exc}")
    if bundle is None:  # keys were checked above; a None here means partial config
        pytest.skip("real provider bundle unavailable despite keys (partial config)")
    return bundle


def _insert_event(
    cur: Any, *, kind: str, action: str, target: str, meta: str | None, entity_id: str
) -> int:
    cur.execute(
        "insert into public.activity_log (actor_name, kind, action, target, meta, "
        "entity_type, entity_id) "
        "values ('Ctx Live Bot', %(kind)s, %(action)s, %(target)s, %(meta)s, "
        "'client'::public.context_entity, %(entity_id)s) returning seq",
        {"kind": kind, "action": action, "target": target, "meta": meta, "entity_id": entity_id},
    )
    return int(cur.fetchone()["seq"])


def _poll_query(
    providers: ContextProviders, namespace: str, text: str, *, attempts: int = 10
) -> list[Any]:
    """Query the REAL Pinecone namespace, retrying for its eventual consistency.

    A fresh upsert is not instantly visible to a query, so we poll a few times with
    a short backoff before giving up (returning whatever the last query produced).
    """
    vector = providers.embedder.embed([text])[0]
    matches: list[Any] = []
    for _ in range(attempts):
        matches = providers.vector_store.query(namespace, vector, top_k=providers.topk)
        if matches:
            return matches
        time.sleep(1.0)
    return matches


def test_live_pipeline_end_to_end_with_real_providers() -> None:
    settings = _require_live()
    providers = _real_providers(settings)

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    tag = uuid4().hex[:8]
    entity_id = str(uuid4())
    entity = ("client", entity_id)
    namespace = namespace_for(*entity)
    store = service_context_repo()

    try:
        # --- activity -> dirty: an audit + a tier=Basic event (one dirty row) ---
        with privileged_connection(pool=admin_pool) as cur:
            seq1 = _insert_event(
                cur, kind="audit", action=f"ran audit {tag}",
                target="https://acme.live", meta="88", entity_id=entity_id,
            )
            seq2 = _insert_event(
                cur, kind="client", action=f"set tier {tag}",
                target="acme", meta="Basic", entity_id=entity_id,
            )
        max_seq = max(seq1, seq2)

        # --- compaction with the REAL providers: real summarize + real embeddings ---
        out = execute_compaction(store, providers, *entity, settings=settings)
        assert out.state == "summarized", out.reason
        assert out.watermark == max_seq

        ctx = store.get_context_for_update(*entity)
        assert ctx is not None
        assert ctx["status"] == "summarized"
        assert int(ctx["event_watermark"]) == max_seq
        assert ctx["summary"]  # real Claude prose
        assert ctx["facts"]["tier"] == "Basic"

        # Real embeddings landed in the REAL Pinecone namespace (via the ledger).
        vectors = store.list_vectors(*entity)
        assert vectors and any(v["chunk_key"] == "facts:client" for v in vectors)
        client_checksum_v1 = next(v["content_checksum"] for v in vectors if v["chunk_key"] == "facts:client")

        # get_context(query=...) returns a REAL top-k from this entity's namespace.
        view = get_context(
            *entity, query="what subscription tier is the client on",
            providers=providers, repo=store, settings=settings,
        )
        assert view.status == "summarized"
        assert view.chunks, "expected a real Pinecone top-k"
        # A direct namespace query is non-empty too (eventual-consistency tolerant).
        assert _poll_query(providers, namespace, "subscription tier"), "no Pinecone matches"

        # --- SUPERSESSION: tier Basic -> Growth. The re-embed overwrites the client
        # facts vector IN PLACE (stable id); the old value is gone from Pinecone. ---
        with privileged_connection(pool=admin_pool) as cur:
            seq3 = _insert_event(
                cur, kind="client", action=f"set tier {tag}",
                target="acme", meta="Growth", entity_id=entity_id,
            )
        out2 = execute_compaction(store, providers, *entity, settings=settings)
        assert out2.state == "summarized" and out2.watermark == seq3

        ctx2 = store.get_context_for_update(*entity)
        assert ctx2 is not None and ctx2["facts"]["tier"] == "Growth"
        vectors2 = store.list_vectors(*entity)
        client_checksum_v2 = next(v["content_checksum"] for v in vectors2 if v["chunk_key"] == "facts:client")
        # The facts:client chunk was RE-EMBEDDED (checksum changed) -> the superseded
        # "Basic" vector is overwritten; the old value no longer exists in Pinecone.
        assert client_checksum_v2 != client_checksum_v1

        view2 = get_context(
            *entity, query="what subscription tier is the client on",
            providers=providers, repo=store, settings=settings,
        )
        client_chunk = next((c for c in view2.chunks if c.chunk_key == "facts:client"), None)
        assert client_chunk is not None
        assert "Growth" in client_chunk.content and "Basic" not in client_chunk.content
    finally:
        with contextlib.suppress(Exception):
            # Delete this run's REAL Pinecone vectors, then the DB rows.
            leftover = store.list_vectors(*entity)
            ids = [str(v["pinecone_id"]) for v in leftover if v.get("pinecone_id")]
            if ids:
                with contextlib.suppress(Exception):
                    providers.vector_store.delete(namespace, ids)
            with privileged_connection(pool=admin_pool) as cur:
                cur.execute("delete from public.context_vectors where entity_id = %s", (entity_id,))
                cur.execute("delete from public.entity_context where entity_id = %s", (entity_id,))
                cur.execute("delete from public.context_dirty where entity_id = %s", (entity_id,))
                cur.execute("delete from public.activity_log where action like %s", (f"%{tag}%",))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
