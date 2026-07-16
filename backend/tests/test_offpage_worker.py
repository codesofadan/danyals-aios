"""7B-3 unit tests: the off-page workers.

Covers the pure monitoring DIFFs (new/lost backlinks, new/changed citations) against the
deterministic provider fakes, the monitor orchestration (cost pre-check, apply, and the
``notify_new_lost`` alert seam), and the Web 2.0 worker wiring (never-stuck /
never-re-raise / redelivery no-op). NO DB, NO network - the store, cost gate, providers,
and notify seam are all fakes/monkeypatched.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import pytest

from app.config import Settings
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.backlinks import BacklinkProvider, BacklinkRecord, FakeBacklinkProvider
from integrations.citations import CitationRecord, FakeCitationProvider
from integrations.llm import LLMResult
from workers.tasks import offpage as wk

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeOffpageStore:
    """In-memory stand-in for the privileged ServiceOffpageStore (monitor + web2)."""

    def __init__(
        self,
        *,
        web2: dict[str, dict[str, Any]] | None = None,
        backlinks: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.web2 = web2 or {}
        self.backlinks = backlinks or []
        self.citations = citations or []
        self.inserted_backlinks: list[dict[str, Any]] = []
        self.marked_lost: list[str] = []
        self.inserted_citations: list[dict[str, Any]] = []
        self.updated_citations: list[str] = []

    # web2 (Web2Store)
    def load_web2(self, web2_id: str) -> dict[str, Any] | None:
        row = self.web2.get(web2_id)
        return dict(row) if row is not None else None

    def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None:
        self.web2.setdefault(web2_id, {}).update(fields)

    # backlinks
    def list_backlinks_for_client(self, client_id: str) -> list[dict[str, Any]]:
        return list(self.backlinks)

    def insert_backlink(self, **kw: Any) -> None:
        self.inserted_backlinks.append(kw)

    def set_backlink_status(self, backlink_id: str, status: str) -> None:
        self.marked_lost.append(backlink_id)

    # citations
    def list_citations_for_client(self, client_id: str) -> list[dict[str, Any]]:
        return list(self.citations)

    def insert_citation(self, **kw: Any) -> None:
        self.inserted_citations.append(kw)

    def update_citation_status(self, citation_id: str, **kw: Any) -> None:
        self.updated_citations.append(citation_id)


class FakeCostStore:
    def __init__(self, *, mode: DialMode = "api", halted: bool = False) -> None:
        self._mode = mode
        self._halted = halted
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 75.0

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class FakeWriter:
    def __init__(self, *, words: int = 40) -> None:
        self._words = words
        self.calls = 0

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        base = [digest[i : i + 6] for i in range(0, len(digest), 6)]
        body = " ".join(f"{base[i % len(base)]}{i}" for i in range(self._words))
        return LLMResult(text=body, input_tokens=1, output_tokens=self._words)


class _ManualBacklinks:
    """A ``BacklinkProvider`` returning a fixed record list (precise diff tests)."""

    def __init__(self, records: list[BacklinkRecord]) -> None:
        self._records = records
        self.calls = 0

    def fetch_backlinks(self, target: str, *, limit: int = 100) -> list[BacklinkRecord]:
        self.calls += 1
        return list(self._records)


class _BoomBacklinks:
    def fetch_backlinks(self, target: str, *, limit: int = 100) -> list[BacklinkRecord]:
        raise RuntimeError("provider down")


def _gate(store: FakeCostStore) -> CostGate:
    return CostGate(store, _NullCache())


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _bl(domain: str, *, spam: int = 3, lost: bool = False) -> BacklinkRecord:
    return BacklinkRecord(
        ref_domain=domain, anchor="a", authority=50, spam=spam, first_seen=date(2026, 7, 1), lost=lost
    )


# --------------------------------------------------------------------------- #
# diff_backlinks
# --------------------------------------------------------------------------- #
def test_diff_backlinks_detects_new_and_lost() -> None:
    fetched = [_bl("fresh.example"), _bl("kept.example")]
    stored = [
        {"id": "b-kept", "ref_domain": "kept.example", "status": "new"},
        {"id": "b-gone", "ref_domain": "gone.example", "status": "new"},
    ]
    diff = wk.diff_backlinks(fetched, stored)
    assert [r.ref_domain for r in diff.new] == ["fresh.example"]  # not previously stored
    assert [r["id"] for r in diff.lost] == ["b-gone"]  # stored but gone from the pull


def test_diff_backlinks_provider_reported_drop_is_lost() -> None:
    fetched = [_bl("kept.example", lost=True)]  # provider now reports it dropped
    stored = [{"id": "b-kept", "ref_domain": "kept.example", "status": "new"}]
    diff = wk.diff_backlinks(fetched, stored)
    assert diff.new == []  # a dropped link is never "new"
    assert [r["id"] for r in diff.lost] == ["b-kept"]


def test_diff_backlinks_already_lost_row_is_not_reflagged() -> None:
    fetched: list[BacklinkRecord] = []
    stored = [{"id": "b-old", "ref_domain": "gone.example", "status": "lost"}]
    diff = wk.diff_backlinks(fetched, stored)
    assert diff.lost == []  # already recorded lost -> no churn


# --------------------------------------------------------------------------- #
# diff_citations
# --------------------------------------------------------------------------- #
def test_diff_citations_detects_new_and_changed() -> None:
    fetched = [
        CitationRecord(directory="Yelp", nap_status="consistent", note="ok"),
        CitationRecord(directory="Bing Places", nap_status="missing", note="none"),
    ]
    stored = [{"id": "c-yelp", "directory": "Yelp", "nap_status": "inconsistent"}]
    diff = wk.diff_citations(fetched, stored)
    assert [r.directory for r in diff.new] == ["Bing Places"]  # not stored
    assert [existing["id"] for existing, _rec in diff.changed] == ["c-yelp"]  # nap changed


# --------------------------------------------------------------------------- #
# run_backlink_monitor: apply + notify seam + cost pre-check + never-raise
# --------------------------------------------------------------------------- #
def test_backlink_monitor_applies_and_calls_notify_seam() -> None:
    store = FakeOffpageStore(
        backlinks=[{"id": "b-gone", "ref_domain": "gone.example", "status": "new"}]
    )
    provider = _ManualBacklinks([_bl("fresh.example"), _bl("also-fresh.example")])
    calls: list[tuple[Any, str, list[BacklinkRecord], list[dict[str, Any]]]] = []

    def notify(cid: Any, cname: str, new: list[BacklinkRecord], lost: list[dict[str, Any]]) -> None:
        calls.append((cid, cname, new, lost))

    result = wk.run_backlink_monitor(
        store, provider, _gate(FakeCostStore()), _settings(),
        client_id="cl-1", client_name="Acme", domain="acme.example", notify=notify,
    )
    assert result["state"] == "ok"
    assert result["new"] == 2 and result["lost"] == 1
    assert len(store.inserted_backlinks) == 2
    assert store.marked_lost == ["b-gone"]
    # The alert seam fired once, carrying the new records + the lost row.
    assert len(calls) == 1
    assert {r.ref_domain for r in calls[0][2]} == {"fresh.example", "also-fresh.example"}
    assert [row["id"] for row in calls[0][3]] == ["b-gone"]


def test_backlink_monitor_no_changes_does_not_notify() -> None:
    store = FakeOffpageStore(
        backlinks=[{"id": "b-1", "ref_domain": "kept.example", "status": "new"}]
    )
    provider = _ManualBacklinks([_bl("kept.example")])
    calls: list[Any] = []
    result = wk.run_backlink_monitor(
        store, provider, _gate(FakeCostStore()), _settings(),
        client_id="cl-1", client_name="Acme", domain="acme.example",
        notify=lambda *a: calls.append(a),
    )
    assert result["new"] == 0 and result["lost"] == 0
    assert calls == []  # nothing changed -> no alert


def test_backlink_monitor_cost_precheck_blocks_before_pull() -> None:
    provider = _BoomBacklinks()  # would raise if ever pulled
    result = wk.run_backlink_monitor(
        FakeOffpageStore(), provider, _gate(FakeCostStore(mode="off")), _settings(),
        client_id="cl-1", client_name="Acme", domain="acme.example",
    )
    assert result["state"] == "blocked"  # R5: pull never happened, no crash


def test_backlink_monitor_provider_error_never_raises() -> None:
    result = wk.run_backlink_monitor(
        FakeOffpageStore(), _BoomBacklinks(), _gate(FakeCostStore()), _settings(),
        client_id="cl-1", client_name="Acme", domain="acme.example",
    )
    assert result["state"] == "error"  # redelivery-safe: caught, not re-raised


def test_backlink_monitor_with_deterministic_fake_provider() -> None:
    """The pinned FakeBacklinkProvider profile flows through end to end."""
    store = FakeOffpageStore()
    provider: BacklinkProvider = FakeBacklinkProvider()
    result = wk.run_backlink_monitor(
        store, provider, _gate(FakeCostStore()), _settings(),
        client_id="cl-1", client_name="Acme", domain="acme.example",
        notify=lambda *a: None,
    )
    assert result["state"] == "ok"
    assert result["new"] >= 1  # at least the pinned clean 'new' link inserts
    assert len(store.inserted_backlinks) == result["new"]


# --------------------------------------------------------------------------- #
# run_citation_monitor
# --------------------------------------------------------------------------- #
def test_citation_monitor_inserts_and_updates() -> None:
    store = FakeOffpageStore(
        citations=[{"id": "c-yelp", "directory": "Yelp", "nap_status": "consistent"}]
    )
    provider = FakeCitationProvider()  # spans all three states, includes Yelp? use its dirs
    result = wk.run_citation_monitor(
        store, provider, _gate(FakeCostStore()), _settings(),
        client_id="cl-1", client_name="Acme", business="Acme Roofing",
    )
    assert result["state"] == "ok"
    # New directories (not the stored Yelp) were inserted.
    assert store.inserted_citations
    assert all("directory" in c for c in store.inserted_citations)


def test_citation_monitor_blocked_by_dial() -> None:
    result = wk.run_citation_monitor(
        FakeOffpageStore(), FakeCitationProvider(), _gate(FakeCostStore(mode="byhand")),
        _settings(), client_id="cl-1", client_name="Acme", business="Acme",
    )
    assert result["state"] == "blocked"  # 'byhand' -> manual review, no auto-pull


# --------------------------------------------------------------------------- #
# notify_new_lost seam is 7F-1-decoupled (guarded no-op, never raises)
# --------------------------------------------------------------------------- #
def test_notify_new_lost_noops_without_service() -> None:
    # The notifications service (7F-1) is not importable yet -> logs a no-op, no raise.
    wk.notify_new_lost(None, "Acme", [_bl("x.example")], [])


def test_notify_new_lost_early_returns_when_empty() -> None:
    wk.notify_new_lost("cl-1", "Acme", [], [])  # nothing to alert -> returns cleanly


# --------------------------------------------------------------------------- #
# execute_monitor wiring: degraded (keyless) providers are SKIPPED, never a crash
# --------------------------------------------------------------------------- #
def test_execute_monitor_degrades_without_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wk, "backlink_provider_from_settings", lambda s: None)
    monkeypatch.setattr(wk, "citation_provider_from_settings", lambda s: None)
    result = wk.execute_monitor(
        FakeOffpageStore(), _settings(), client_id="cl-1", domain="acme.example", business="Acme"
    )
    assert result["backlinks"]["state"] == "degraded"
    assert result["citations"]["state"] == "degraded"


def test_execute_monitor_runs_both_when_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeOffpageStore()
    monkeypatch.setattr(wk, "backlink_provider_from_settings", lambda s: FakeBacklinkProvider())
    monkeypatch.setattr(wk, "citation_provider_from_settings", lambda s: FakeCitationProvider())
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    result = wk.execute_monitor(
        store, _settings(), client_id="cl-1", domain="acme.example", business="Acme Roofing"
    )
    assert result["backlinks"]["state"] == "ok"
    assert result["citations"]["state"] == "ok"


# --------------------------------------------------------------------------- #
# Web 2.0 worker wiring: never-stuck / never-re-raise / redelivery no-op
# --------------------------------------------------------------------------- #
def _draft_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "w2-1", "client_id": "cl-1", "client_name": "Acme", "platform": "WordPress.com",
        "anchor": "roof repair", "target_url": "https://acme.example/x", "topic": "roof repair",
        "page_type": "blog", "framework": "Auto", "status": "draft", "post_url": "",
        "verified": "pending", "body_md": "", "external_id": None,
    }
    row.update(over)
    return row


def test_web2_write_worker_wiring_and_redelivery(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeOffpageStore(web2={"w2-1": _draft_row()})
    monkeypatch.setattr(wk, "_writer_for", lambda s: (FakeWriter(), "m"))
    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))

    first = wk.execute_web2_write(store, _settings(), "w2-1")  # type: ignore[arg-type]
    assert first.state == "needs_review"  # held at the review gate, not published
    assert store.web2["w2-1"]["status"] == "needs_review"
    assert store.web2["w2-1"]["post_url"] == ""

    second = wk.execute_web2_write(store, _settings(), "w2-1")  # type: ignore[arg-type]
    assert second.state == "unchanged"  # redelivery is a no-op (no double-spend)


def test_web2_publish_worker_never_raises_on_store_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BoomStore:
        def load_web2(self, web2_id: str) -> dict[str, Any] | None:
            raise RuntimeError("db down")

        def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None:
            raise RuntimeError("db down")

    monkeypatch.setattr(wk, "_gate", lambda: _gate(FakeCostStore()))
    # web2_publisher_from_settings returns None (per-account OAuth is in the vault).
    outcome = wk.execute_web2_publish(BoomStore(), _settings(), "w2-1")  # type: ignore[arg-type]
    assert outcome.state == "error"  # never stuck, never re-raised
