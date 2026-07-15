"""P6B-2 unit gate: context schemas + context_repo SQL shape (no DB).

Covers the response-model round-trips (EntityContextResponse / ContextHealth lag
math / ContextChunk) and asserts the parameterized-SQL SHAPE of every
``context_repo`` method through a capturing fake cursor (the RLS-read vs
service-write split, the enum casts, the version bump + watermark ``greatest``,
the on-conflict upserts) - the same style as ``test_activity``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from app.db.context_repo import ContextRepo
from app.schemas.context import ContextChunk, ContextHealth, EntityContextResponse

pytestmark = pytest.mark.unit

_ENTITY = "3f8b8c2e-1d4a-4c6b-9e2f-000000000001"


class _FakeCursor:
    """Captures each ``execute`` (query, params) and returns preset rows."""

    def __init__(self, *, one: Any = None, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[Any, Any]] = []
        self._one = one
        self._rows = rows or []

    def execute(self, query: Any, params: Any = None) -> None:
        self.calls.append((query, params))

    def fetchone(self) -> Any:
        return self._one

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


@contextmanager
def _conn(cur: _FakeCursor) -> Iterator[_FakeCursor]:
    yield cur


def _patch(monkeypatch: pytest.MonkeyPatch, cur: _FakeCursor) -> None:
    """Redirect BOTH seams the repo uses to the one capturing cursor."""
    monkeypatch.setattr("app.db.context_repo.rls_connection", lambda *_a, **_k: _conn(cur))
    monkeypatch.setattr("app.db.context_repo.privileged_connection", lambda *_a, **_k: _conn(cur))


# --------------------------------------------------------------------------- #
# Schema round-trips
# --------------------------------------------------------------------------- #
def test_entity_context_response_from_row() -> None:
    now = datetime.now(UTC)
    row = {
        "id": "ctx-1", "entity_type": "client", "entity_id": _ENTITY,
        "summary": "living summary", "facts": {"tier": "B"}, "version": 3,
        "status": "summarized", "event_watermark": 42, "checksum": "deadbeef",
        "updated_at": now,
    }
    resp = EntityContextResponse.from_row(row)
    assert resp.entity_type == "client"
    assert resp.facts == {"tier": "B"}
    assert resp.version == 3
    assert resp.status == "summarized"
    assert resp.updated_at == now
    dumped = resp.model_dump()
    # The ledger internals never leak into the response.
    assert "checksum" not in dumped and "event_watermark" not in dumped


def test_entity_context_response_defaults_on_bad_values() -> None:
    resp = EntityContextResponse.from_row(
        {"id": "x", "entity_type": "bogus", "entity_id": _ENTITY,
         "facts": None, "status": None, "version": None, "updated_at": datetime.now(UTC)}
    )
    assert resp.entity_type == "client"  # coerced from unknown
    assert resp.facts == {}              # None -> {}
    assert resp.status == "pending"
    assert resp.version == 0


def test_context_health_lag_math() -> None:
    now = datetime.now(UTC)
    row = {"entity_type": "client", "entity_id": _ENTITY, "status": "pending",
           "version": 1, "event_watermark": 10, "updated_at": now}
    h = ContextHealth.from_row(row, latest_seq=17)
    assert h.lag == 7 and h.stale is True and h.latest_seq == 17

    fresh = ContextHealth.from_row({**row, "status": "summarized", "event_watermark": 20}, latest_seq=17)
    assert fresh.lag == 0 and fresh.stale is False  # watermark >= latest_seq -> not stale


def test_context_chunk_round_trip() -> None:
    c = ContextChunk(chunk_key="facts:seo", content="the client focuses on local SEO", score=0.87)
    assert c.chunk_key == "facts:seo" and c.score == 0.87
    assert ContextChunk(chunk_key="summary", content="x").score == 0.0  # default


# --------------------------------------------------------------------------- #
# Repo SQL shape - RLS reads
# --------------------------------------------------------------------------- #
def test_get_entity_context_rls_read(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(one={"id": "ctx-1"})
    _patch(monkeypatch, cur)
    ContextRepo("u-1").get_entity_context("client", _ENTITY)
    query, params = cur.calls[0]
    assert "from public.entity_context" in query
    assert "%s::public.context_entity" in query  # enum cast so a text bind assigns
    assert params == ("client", _ENTITY)


def test_list_contexts_filter_and_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(rows=[{"id": "a"}])
    _patch(monkeypatch, cur)
    ContextRepo("u-1").list_contexts("site", limit=5, offset=10)
    query, params = cur.calls[0]
    assert "where entity_type = %s::public.context_entity" in query
    assert "order by updated_at desc" in query and "limit %s offset %s" in query
    assert params == ["site", 5, 10]


def test_read_portal_context_uses_view(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(one={"summary": "s"})
    _patch(monkeypatch, cur)
    ContextRepo("u-1").read_portal_context()
    query, _params = cur.calls[0]
    assert "from public.portal_context" in query  # the security-barrier view, not the base table
    assert "entity_context" not in query


# --------------------------------------------------------------------------- #
# Repo SQL shape - service_role writes
# --------------------------------------------------------------------------- #
def test_upsert_context_bumps_version_and_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(one={"id": "ctx-1", "version": 1})
    _patch(monkeypatch, cur)
    ContextRepo("u-1").upsert_context(
        "client", _ENTITY, summary="s", facts={"tier": "B"},
        event_watermark=99, status="summarized", model="haiku", checksum="cs",
    )
    query, params = cur.calls[0]
    assert "insert into public.entity_context" in query
    assert "on conflict (entity_type, entity_id) do update" in query
    assert "version         = public.entity_context.version + 1" in query
    assert "greatest(public.entity_context.event_watermark" in query  # never regresses
    assert "%(status)s::public.context_status" in query
    assert isinstance(params["facts"], Jsonb)  # facts bound as jsonb, never string-built
    assert params["event_watermark"] == 99


def test_get_context_for_update_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(one={"id": "ctx-1"})
    _patch(monkeypatch, cur)
    ContextRepo("u-1").get_context_for_update("client", _ENTITY)
    query, params = cur.calls[0]
    assert "for update" in query and "from public.entity_context" in query
    assert params == ("client", _ENTITY)


def test_record_vector_upserts_on_chunk_key(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(one={"id": "v-1"})
    _patch(monkeypatch, cur)
    ContextRepo("u-1").record_vector(
        "client", _ENTITY, chunk_key="summary", pinecone_id="client:xyz#summary",
        content_checksum="abc", version=2, dim=1024, model="voyage-3",
    )
    query, params = cur.calls[0]
    assert "insert into public.context_vectors" in query
    assert "on conflict (entity_type, entity_id, chunk_key) do update" in query
    assert "embedded_at      = now()" in query
    assert params["chunk_key"] == "summary" and params["dim"] == 1024


def test_delete_vector_returns_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(one={"pinecone_id": "client:xyz#stale"})
    _patch(monkeypatch, cur)
    row = ContextRepo("u-1").delete_vector("client", _ENTITY, "facts:old")
    query, params = cur.calls[0]
    assert "delete from public.context_vectors" in query and "returning *" in query
    assert params == ("client", _ENTITY, "facts:old")
    assert row == {"pinecone_id": "client:xyz#stale"}  # so the caller GCs the store too


def test_list_vectors_orders_by_chunk_key(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(rows=[{"chunk_key": "a"}, {"chunk_key": "b"}])
    _patch(monkeypatch, cur)
    rows = ContextRepo("u-1").list_vectors("client", _ENTITY)
    query, params = cur.calls[0]
    assert "from public.context_vectors" in query and "order by chunk_key" in query
    assert params == ("client", _ENTITY)
    assert len(rows) == 2
