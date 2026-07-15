"""P6B-8 unit gate: the CONTEXT RETRIEVAL API + FRESHNESS GATE.

Two layers, all with FAKES (no DB, no network, no keys):

* the service core (``get_context`` / ``context_health`` / ``org_context_health``)
  against a fake repo that satisfies BOTH the RLS-read surface and the
  ``ContextStore`` the sync recompaction path drives - proving the freshness policy
  (stale+lag, ?fresh bounded sync recompaction -> lag 0, spend-blocked / no-providers
  => 200 stale, namespace-scoped top-k retrieval, degraded => chunks=[]);
* the routes, proving the RLS gating (a client is 403 from /context/*, staff read
  any entity, /portal/context is the client's OWN only).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.context_repo import get_context_repo
from app.routers.context import get_context_provider_factory
from app.services.context_cost import GatedEmbedder, GatedSummarizer
from app.services.context_service import (
    UnknownEntityTypeError,
    context_health,
    get_context,
    org_context_health,
)
from app.services.context_vectorsync import namespace_for
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.context_providers import ContextProviders, providers_for_tests

pytestmark = pytest.mark.unit

ENTITY = ("client", "11111111-1111-1111-1111-111111111111")


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _event(seq: int, *, kind: str = "client", action: str = "set tier", target: str = "acme",
           meta: str | None = None) -> dict[str, Any]:
    return {"seq": seq, "kind": kind, "action": action, "target": target, "meta": meta, "created_at": None}


# --------------------------------------------------------------------------- #
# A fake repo: RLS reads + the ContextStore surface the ?fresh path drives.
# --------------------------------------------------------------------------- #
class FakeRepo:
    def __init__(
        self,
        *,
        events: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
        latest: int | None = None,
        portal_row: dict[str, Any] | None = None,
        contexts: list[dict[str, Any]] | None = None,
        latest_map: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self.events = events or []
        self.context = context
        self._latest = latest if latest is not None else max((e["seq"] for e in self.events), default=0)
        self.portal_row = portal_row
        self._contexts = contexts
        self._latest_map = latest_map
        self.dirty_last: int | None = self._latest or None
        self.dirty_exists = bool(self.events)
        self.rearms: list[dict[str, Any]] = []
        self.cleared = 0
        self.upserts: list[dict[str, Any]] = []
        self.ledger: dict[str, dict[str, Any]] = {}

    # --- RLS reads used by the service ---
    def get_entity_context(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return dict(self.context) if self.context is not None else None

    def latest_seq(self, entity_type: str, entity_id: str) -> int:
        return int(self._latest)

    def latest_seqs(self) -> dict[tuple[str, str], int]:
        if self._latest_map is not None:
            return dict(self._latest_map)
        return {}

    def list_contexts(
        self, entity_type: str | None = None, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        if self._contexts is not None:
            return [dict(r) for r in self._contexts]
        return [dict(self.context)] if self.context is not None else []

    def read_portal_context(self) -> dict[str, Any] | None:
        return dict(self.portal_row) if self.portal_row is not None else None

    # --- ContextStore surface (execute_compaction drives these) ---
    def get_context_for_update(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return self.context

    def upsert_context(
        self, entity_type: str, entity_id: str, *, summary: str = "",
        facts: dict[str, Any] | None = None, token_budget: int = 1200, token_count: int = 0,
        event_watermark: int = 0, status: str = "summarized", model: str = "", checksum: str = "",
    ) -> dict[str, Any]:
        prior_version = int(self.context["version"]) if self.context else 0
        prior_watermark = int(self.context["event_watermark"]) if self.context else 0
        is_insert = self.context is None
        row = {
            "id": "ctx-1", "entity_type": entity_type, "entity_id": entity_id, "summary": summary,
            "facts": dict(facts or {}), "token_budget": token_budget, "token_count": token_count,
            "event_watermark": max(prior_watermark, event_watermark), "status": status,
            "model": model, "checksum": checksum,
            "version": prior_version if is_insert else prior_version + 1, "updated_at": None,
        }
        self.context = row
        self._latest = max(self._latest, 0)  # latest_seq tracks events, unchanged here
        self.upserts.append(dict(row))
        return dict(row)

    def events_after(self, entity_type: str, entity_id: str, watermark: int) -> list[dict[str, Any]]:
        return [e for e in self.events if int(e["seq"]) > watermark]

    def dirty_last_seq(self, entity_type: str, entity_id: str) -> int | None:
        return self.dirty_last if self.dirty_exists else None

    def clear_dirty(self, entity_type: str, entity_id: str) -> None:
        self.dirty_exists = False
        self.cleared += 1

    def rearm_dirty(
        self, entity_type: str, entity_id: str, *, last_seq: int, backoff_seconds: int
    ) -> None:
        self.dirty_exists = True
        self.dirty_last = max(self.dirty_last or 0, last_seq)
        self.rearms.append({"last_seq": last_seq, "backoff_seconds": backoff_seconds})

    def claim_due_dirty(self, limit: int) -> list[dict[str, Any]]:
        return []

    def list_vectors(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return list(self.ledger.values())

    def record_vector(
        self, entity_type: str, entity_id: str, *, chunk_key: str, pinecone_id: str,
        content_checksum: str, version: int, dim: int, model: str,
    ) -> dict[str, Any]:
        row = {"chunk_key": chunk_key, "pinecone_id": pinecone_id, "content_checksum": content_checksum,
               "version": version, "dim": dim, "model": model}
        self.ledger[chunk_key] = row
        return dict(row)

    def delete_vector(self, entity_type: str, entity_id: str, chunk_key: str) -> dict[str, Any] | None:
        return self.ledger.pop(chunk_key, None)


def _summarized_row(*, watermark: int, version: int = 1, summary: str = "prior",
                    facts: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "ctx-1", "entity_type": ENTITY[0], "entity_id": ENTITY[1], "summary": summary,
        "facts": facts or {"tier": "Growth"}, "token_budget": 1200, "token_count": 3,
        "event_watermark": watermark, "status": "summarized", "model": "fake-summary",
        "checksum": "abc", "version": version, "updated_at": None,
    }


# --------------------------------------------------------------------------- #
# 1. stale=true + lag when the watermark is behind; not stale when caught up
# --------------------------------------------------------------------------- #
def test_stale_and_lag_when_watermark_behind() -> None:
    repo = FakeRepo(context=_summarized_row(watermark=10), latest=17)
    view = get_context(*ENTITY, query=None, fresh=False, providers=None, repo=repo, settings=_settings())
    assert view.lag == 7 and view.stale is True
    assert view.event_watermark == 10 and view.latest_seq == 17
    # default (async) path re-armed the dirty row so the worker catches up.
    assert repo.rearms and repo.rearms[-1]["backoff_seconds"] == 0


def test_not_stale_when_caught_up() -> None:
    repo = FakeRepo(context=_summarized_row(watermark=17), latest=17)
    view = get_context(*ENTITY, query=None, fresh=False, providers=None, repo=repo, settings=_settings())
    assert view.lag == 0 and view.stale is False
    assert repo.rearms == []  # nothing to nudge


# --------------------------------------------------------------------------- #
# 2. fresh=True on a stale context => bounded SYNC recompaction, lag -> 0
# --------------------------------------------------------------------------- #
def test_fresh_true_triggers_sync_recompaction_lag_zero() -> None:
    events = [_event(11, meta="Growth"), _event(12, kind="task", action="closed", target="onboarding")]
    repo = FakeRepo(events=events)  # no context yet, latest_seq == 12
    providers = providers_for_tests()

    view = get_context(*ENTITY, query=None, fresh=True, providers=providers, repo=repo, settings=_settings())

    assert view.status == "summarized"
    assert view.event_watermark == 12 and view.latest_seq == 12
    assert view.lag == 0 and view.stale is False
    assert view.facts["tier"] == "Growth"
    assert view.summary  # bounded prose folded synchronously
    # exactly one summarizing write happened on the request path.
    assert any(u["status"] == "summarized" for u in repo.upserts)


# --------------------------------------------------------------------------- #
# 3. fresh=True but providers None / cost-gate blocked => 200 stale, no error
# --------------------------------------------------------------------------- #
def test_fresh_true_no_providers_serves_stale_no_error() -> None:
    repo = FakeRepo(context=_summarized_row(watermark=3), latest=9)
    view = get_context(*ENTITY, query=None, fresh=True, providers=None, repo=repo, settings=_settings())
    assert view.stale is True and view.lag == 6  # NOT recompacted, NOT an error
    assert repo.upserts == []  # providers None => no compaction write at all
    assert repo.rearms[-1]["backoff_seconds"] == 0  # re-armed for the worker instead


class _BlockingCostStore:
    """Gate store whose dial is 'off' => every evaluate blocks (no spend)."""

    def dial_mode(self, feature_key: str) -> DialMode:
        return "off"

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 75.0

    def is_halted(self) -> bool:
        return False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        return None


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gated_blocking_providers() -> ContextProviders:
    base = providers_for_tests()
    gate = CostGate(_BlockingCostStore(), _NullCache())
    s = _settings()
    return replace(
        base,
        summarizer=GatedSummarizer(base.summarizer, gate, settings=s, client_id=None),
        embedder=GatedEmbedder(base.embedder, gate, settings=s, client_id=None),
    )


def test_fresh_true_spend_blocked_serves_stale_no_error() -> None:
    repo = FakeRepo(events=[_event(8, meta="Growth")], context=_summarized_row(watermark=0, version=1))
    providers = _gated_blocking_providers()

    view = get_context(*ENTITY, query=None, fresh=True, providers=providers, repo=repo, settings=_settings())

    # The gate blocked the fold -> execute_compaction DEGRADED (no crash); 200 stale.
    assert view.stale is True
    assert view.status == "degraded"
    assert view.event_watermark == 0  # watermark HELD (lag stays visible)


# --------------------------------------------------------------------------- #
# 4. query given => vectorstore.query on the CORRECT namespace only, top-k
# --------------------------------------------------------------------------- #
class _SpyVectorStore:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.query_namespaces: list[str] = []

    def upsert(self, namespace: str, items: Any) -> None:
        self.inner.upsert(namespace, items)

    def query(self, namespace: str, vector: list[float], top_k: int) -> Any:
        self.query_namespaces.append(namespace)
        return self.inner.query(namespace, vector, top_k)

    def delete(self, namespace: str, ids: list[str]) -> None:
        self.inner.delete(namespace, ids)

    def list_items(self, namespace: str) -> Any:
        return self.inner.list_items(namespace)


def test_query_hits_correct_namespace_and_returns_topk() -> None:
    base = providers_for_tests()
    spy = _SpyVectorStore(base.vector_store)
    providers = replace(base, vector_store=spy)
    events = [_event(11, meta="Growth"), _event(12, kind="audit", action="ran", target="https://acme.com")]
    repo = FakeRepo(events=events)

    # First: fresh recompaction populates the store (through the spy) for this entity.
    get_context(*ENTITY, query=None, fresh=True, providers=providers, repo=repo, settings=_settings())
    spy.query_namespaces.clear()

    # Then: a query retrieves top-k chunks - and hits ONLY this entity's namespace.
    view = get_context(*ENTITY, query="what tier is the client", fresh=False,
                       providers=providers, repo=repo, settings=_settings())

    assert spy.query_namespaces == [namespace_for(*ENTITY)]  # the correct namespace ONLY
    assert view.chunks and len(view.chunks) <= _settings().context_topk
    assert all(c.content for c in view.chunks)  # chunk_key mapped back to CURRENT content
    # the ledger internal (checksum) never rides the wire.
    assert all("content_checksum" not in c.model_dump() for c in view.chunks)


# --------------------------------------------------------------------------- #
# 5. degraded / no-providers => summary + facts, chunks = []
# --------------------------------------------------------------------------- #
def test_degraded_serves_summary_facts_no_chunks() -> None:
    row = {**_summarized_row(watermark=5), "status": "degraded", "summary": "degraded prose",
           "facts": {"tier": "Free"}}
    repo = FakeRepo(context=row, latest=9)
    providers = providers_for_tests()  # providers present, but status is degraded
    view = get_context(*ENTITY, query="anything", fresh=False, providers=providers, repo=repo, settings=_settings())
    assert view.summary == "degraded prose" and view.facts == {"tier": "Free"}
    assert view.chunks == []  # no reliable vectors for a degraded context
    assert view.stale is True


def test_no_providers_no_query_summary_facts_only() -> None:
    repo = FakeRepo(context=_summarized_row(watermark=17), latest=17)
    view = get_context(*ENTITY, query="q", fresh=False, providers=None, repo=repo, settings=_settings())
    assert view.summary == "prior" and view.chunks == []


# --------------------------------------------------------------------------- #
# 6. unknown entity_type is a validation error
# --------------------------------------------------------------------------- #
def test_unknown_entity_type_raises() -> None:
    repo = FakeRepo(context=_summarized_row(watermark=1))
    with pytest.raises(UnknownEntityTypeError):
        get_context("bogus", ENTITY[1], query=None, fresh=False, providers=None, repo=repo, settings=_settings())


# --------------------------------------------------------------------------- #
# 7. health: per-entity signal + the org rollup
# --------------------------------------------------------------------------- #
def test_context_health_per_entity() -> None:
    repo = FakeRepo(context=_summarized_row(watermark=10), latest=17)
    h = context_health(*ENTITY, repo=repo)
    assert h.lag == 7 and h.stale is True and h.latest_seq == 17 and h.event_watermark == 10


def test_context_health_absent_row() -> None:
    repo = FakeRepo(latest=4)  # no context row, but 4 events exist
    h = context_health(*ENTITY, repo=repo)
    assert h.status == "pending" and h.lag == 4 and h.stale is True


def test_org_context_health_rollup() -> None:
    a = _summarized_row(watermark=10, version=2)                      # lag 5 => stale
    b = {**_summarized_row(watermark=3), "entity_id": "22222222-2222-2222-2222-222222222222",
         "status": "degraded"}                                        # degraded => stale
    c = {**_summarized_row(watermark=8), "entity_id": "33333333-3333-3333-3333-333333333333"}  # caught up
    repo = FakeRepo(
        contexts=[a, b, c],
        latest_map={
            ("client", ENTITY[1]): 15,
            ("client", "22222222-2222-2222-2222-222222222222"): 4,
            ("client", "33333333-3333-3333-3333-333333333333"): 8,
        },
    )
    org = org_context_health(repo=repo)
    assert org.total == 3
    assert org.stale == 2  # a (lag) + b (degraded)
    assert org.degraded == 1
    assert org.worst_lag == 5  # a: 15 - 10


# =========================================================================== #
# Route layer: RLS gating (staff vs portal-client).
# =========================================================================== #
def _client_user(client_id: str | None = "cl-A") -> CurrentUser:
    return CurrentUser(
        id="u-1", email="p@acme.com", role="client", status="active", name="Acme Portal",
        title="", avatar_color="#000", phone="", two_fa=False, client_id=client_id,
    )


def _staff_user(role: str = "manager") -> CurrentUser:
    return CurrentUser(
        id="s-1", email="s@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Staff", title="", avatar_color="#000", phone="", two_fa=False,
    )


async def test_client_forbidden_from_context(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: _client_user()
    for path in (
        f"/api/v1/context/client/{ENTITY[1]}",
        f"/api/v1/context/client/{ENTITY[1]}/health",
        "/api/v1/context/health",
    ):
        resp = await client.get(path)
        assert resp.status_code == 403, path


async def test_staff_reads_any_entity(app: FastAPI, client: httpx.AsyncClient) -> None:
    repo = FakeRepo(context=_summarized_row(watermark=17, summary="the living summary"), latest=17)
    app.dependency_overrides[get_current_user] = lambda: _staff_user("viewer")  # holds view_reports
    app.dependency_overrides[get_context_repo] = lambda: repo
    app.dependency_overrides[get_context_provider_factory] = lambda: (lambda et, eid: None)

    resp = await client.get(f"/api/v1/context/client/{ENTITY[1]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == "the living summary"
    assert body["stale"] is False and body["lag"] == 0
    assert body["chunks"] == []


async def test_portal_context_returns_own_only(app: FastAPI, client: httpx.AsyncClient) -> None:
    repo = FakeRepo(portal_row={"summary": "MY own summary", "facts": {"tier": "Growth"}, "updated_at": None})
    app.dependency_overrides[get_current_user] = lambda: _client_user("cl-A")
    app.dependency_overrides[get_context_repo] = lambda: repo

    resp = await client.get("/api/v1/portal/context")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == "MY own summary" and body["facts"] == {"tier": "Growth"}


async def test_staff_forbidden_from_portal_context(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: _staff_user("owner")  # not a client
    resp = await client.get("/api/v1/portal/context")
    assert resp.status_code == 403
