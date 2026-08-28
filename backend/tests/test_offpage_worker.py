"""7B-3 unit tests: the off-page workers.

Covers the pure monitoring DIFFs (new/lost backlinks, new/changed citations) against the
deterministic provider fakes, the monitor orchestration (cost pre-check, apply, and the
``notify_new_lost`` alert seam), and the Web 2.0 worker wiring (never-stuck /
never-re-raise / redelivery no-op). NO DB, NO network - the store, cost gate, providers,
and notify seam are all fakes/monkeypatched.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from app.config import Settings
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.web2_pipeline import Web2Outcome
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

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.systems = [*getattr(self, "systems", []), system]
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


def test_client_geo_is_carried_from_the_joined_business_profile() -> None:
    """`Web2Client.geo` was declared and consumed but NEVER populated, so it was None in
    production. That is two defects at once: the writer generated every local-business
    article with no geo signal, and the similarity gate could not mask the city - the
    exact token whose presence lets two templated articles score as distinct. The store
    now joins it in as `client_geo`; this pins that it reaches the client object."""
    client = wk._client_from_row(_draft_row(client_geo="Leeds"))
    assert client.geo == "Leeds"


def test_a_missing_business_profile_leaves_geo_none_not_blank() -> None:
    """A client with no profile must degrade to None (the generator's 'no geo' path),
    never to an empty string that would mask nothing and read as a real value."""
    assert wk._client_from_row(_draft_row()).geo is None
    assert wk._client_from_row(_draft_row(client_geo="   ")).geo is None


def test_web2_write_celery_task_never_auto_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CELERY TASK - not just the pure core - must park a clean draft at review.

    This covers the wrapper, which is where an auto-publish branch previously lived and
    where no test reached it: ``execute_web2_write`` never published, so the pure-core
    tests above stayed green while the task shipped a cleanly-drafted property straight
    to ``publishing`` with no lead approval. The only legal path out of ``needs_review``
    is a lead's approve call, so a publish enqueue from here is a defect by definition.
    """
    store = FakeOffpageStore(web2={"w2-1": _draft_row(status="needs_review")})
    enqueued: list[str] = []

    # Stub the pure core (tested above) so this test drives the WRAPPER against the
    # exact outcome the removed branch keyed on: a clean, non-degraded 'drafted' write.
    # Without pinning that outcome the branch never fires and the guard is vacuous.
    monkeypatch.setattr(
        wk,
        "execute_web2_write",
        lambda store, settings, web2_id: Web2Outcome(
            web2_id, "write", "needs_review", degraded=False, reason="drafted"
        ),
    )
    monkeypatch.setattr(wk, "service_offpage_store", lambda: store)
    monkeypatch.setattr(wk, "get_settings", _settings)
    monkeypatch.setattr(wk.web2_publish_job, "delay", lambda web2_id: enqueued.append(web2_id))

    outcome = wk.web2_write_job.run("w2-1")

    assert outcome["state"] == "needs_review"
    assert store.web2["w2-1"]["status"] == "needs_review"  # NOT flipped to 'publishing'
    assert enqueued == []  # the publish job was never enqueued
    assert store.web2["w2-1"]["post_url"] == ""  # nothing went live


def test_the_release_tick_publishes_due_rows_and_defers_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drip in one test: several properties come due together, the pacing caps
    permit one, and the rest are RESCHEDULED rather than published or dropped.

    Releasing all of them is the obvious implementation and it turns a carefully paced
    campaign into a burst at exactly the moment the caps were meant to bite.
    """
    due = [
        {
            "id": f"w2-{i}", "client_id": "cl-1", "platform": "Blogger",
            "status": "publishing", "account_id": None, "ownership": "per_client",
        }
        for i in range(4)
    ]
    store = FakeOffpageStore(web2={d["id"]: dict(d) for d in due})
    store.pacing_caps_row = lambda: {"publish_jitter_max_hours": 0}  # type: ignore[method-assign]
    store.recent_web2_publishes = lambda **_kw: []  # type: ignore[method-assign]
    enqueued: list[str] = []

    monkeypatch.setattr(wk, "claim_due_web2_releases", lambda: due)
    monkeypatch.setattr(wk.web2_publish_job, "delay", lambda web2_id: enqueued.append(web2_id))

    result = wk.execute_web2_release(store, _settings())  # type: ignore[arg-type]

    assert result["claimed"] == 4
    assert len(result["released"]) == 1  # the per-client daily cap bites inside the tick
    assert len(result["deferred"]) == 3
    assert enqueued == result["released"]
    # A released row's slot is CLEARED so a redelivered tick cannot claim it again;
    # a deferred row's slot MOVES so it is still going out, just later.
    assert store.web2[result["released"][0]]["scheduled_for"] is None
    for web2_id in result["deferred"]:
        assert store.web2[web2_id]["scheduled_for"] is not None


def test_the_release_tick_is_a_no_op_when_nothing_is_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wk, "claim_due_web2_releases", lambda: [])
    result = wk.execute_web2_release(FakeOffpageStore(), _settings())  # type: ignore[arg-type]
    assert result == {"claimed": 0, "released": [], "deferred": []}


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


# --------------------------------------------------------------------------- #
# Web 2.0 source-pack grounding (7B-4 proof wiring)
# --------------------------------------------------------------------------- #
def test_source_pack_from_web2_row_builds_grounded_pack() -> None:
    """The write worker turns the placement's seeded source_pack jsonb into a real
    grounding pack so the draft is gap-free (proof / testimonials / unique data)."""
    row = {
        "client_name": "Acme Roofing",
        "source_pack": {
            "client_name": "Acme Roofing",
            "proof_points": ["Rebuilt 40 storm-damaged roofs in 2025", "  "],
            "testimonials": ["'They saved our home' - J. Doe"],
            "unique_data": ["2025 study of 500 roofs: 30% spot-repair only"],
            "services": ["Roof repair"],
            "facts": {"years": 18},
        },
    }
    pack = wk._source_pack_from_web2_row(row)
    assert pack.client_name == "Acme Roofing"
    assert pack.proof_points == ["Rebuilt 40 storm-damaged roofs in 2025"]  # blank dropped
    assert pack.testimonials == ["'They saved our home' - J. Doe"]
    assert pack.unique_data == ["2025 study of 500 roofs: 30% spot-repair only"]
    assert pack.services == ["Roof repair"]
    assert pack.facts == {"years": "18"}


def test_source_pack_from_web2_row_empty_degrades_to_name_only() -> None:
    """No seeded pack -> just the client name, so the generator emits [NEEDS:] gaps
    that hold at review (the pre-grounding behaviour, never a hallucination)."""
    pack = wk._source_pack_from_web2_row({"client_name": "Acme", "source_pack": {}})
    assert pack.client_name == "Acme"
    assert pack.proof_points == [] and pack.testimonials == [] and pack.unique_data == []


def test_client_from_row_carries_source_pack() -> None:
    """_client_from_row now populates Web2Client.source_pack (the run_write seam)."""
    client = wk._client_from_row({
        "client_id": "cl-1", "client_name": "Acme",
        "source_pack": {"proof_points": ["Did a real thing"]},
    })
    assert client.source_pack is not None
    assert client.source_pack.proof_points == ["Did a real thing"]
