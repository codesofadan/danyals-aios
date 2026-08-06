"""Unit gate for the daily Policy-Radar GENERATOR (Anthropic, replaces the scrape watcher).

The generator now runs entirely on the Cloud API with PURE Claude generation (the Anthropic
Messages API, NO web search) - Claude returns the current top developments from its OWN
expert knowledge. Proven with the summarizer + gate ALL faked - NO network, NO DB, NO real
provider:

* the pure core (:func:`run_policy_generation`):
  - happy path -> N structured, enum-clamped items; the SINGLE paid call is metered under
    the ``policy`` dial and committed as the ACTUAL TOKEN cost ONLY (no web-search term);
    the generator's own N-item system prompt is passed through;
  - keyless (no summarizer) DEGRADES to no items WITHOUT touching the gate;
  - a cost-gate block DEGRADES with NO summarizer call + NO spend (never bypassed);
  - a generation failure DEGRADES cleanly with no spend committed;
  - the requested count caps the produced items.
* the parse (:func:`parse_generation`) is DEFENSIVE: non-JSON / missing-items / bad-item /
  hallucinated-enum inputs never crash and clamp to the 0019 vocabulary; an item that omits
  its own source_url falls back to an empty string (no web retrieval).
* the persistence core (``store_generated_items``) writes a change_event + kb_entry +
  recommendation per item, with a ``kb-gen-*`` ref.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import Settings
from app.services import pricing
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.policy_generate import (
    _GENERATE_SYSTEM_PROMPT,
    DEGRADE_GENERATION_FAILED,
    DEGRADE_NO_ANTHROPIC,
    build_generate_prompt,
    parse_generation,
    run_policy_generation,
)
from integrations.llm import LLMResult
from workers.tasks.policy import store_generated_items

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class SpySummarizer:
    """A ``SystemSummarizer`` returning fixed text; records the prompt + system it was given."""

    def __init__(
        self,
        *,
        text: str,
        input_tokens: int = 300,
        output_tokens: int = 800,
    ) -> None:
        self._text = text
        self._in = input_tokens
        self._out = output_tokens
        self.calls: list[str] = []
        self.systems: list[str | None] = []

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
    ) -> LLMResult:
        self.calls.append(prompt)
        self.systems.append(system)
        return LLMResult(text=self._text, input_tokens=self._in, output_tokens=self._out)


class RaisingSummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
    ) -> LLMResult:
        self.calls.append(prompt)
        raise RuntimeError("generation unavailable")


class SpyCostStore:
    """A ``CostStore`` with a fixed dial mode; records every commit."""

    def __init__(self, mode: DialMode = "api", *, halted: bool = False) -> None:
        self._mode = mode
        self._halted = halted
        self.commits: list[tuple[str, str, float]] = []

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
        self.commits.append((ctx.feature_key, ctx.provider, cost))


class NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class FakeGenStore:
    """In-memory stand-in for the generator's slice of ``PolicyWatchStore``."""

    def __init__(self) -> None:
        self.changes: list[dict[str, Any]] = []
        self.kb: list[dict[str, Any]] = []
        self.recs: list[dict[str, Any]] = []
        self.triggered: list[tuple[str, str]] = []
        self._seq = 0

    def insert_change_event(self, source_name: str, summary: str, severity: str) -> str:
        self._seq += 1
        cid = f"ch-{self._seq}"
        self.changes.append(
            {"id": cid, "source_name": source_name, "summary": summary, "severity": severity}
        )
        return cid

    def insert_kb_entry(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        stored = {**row, "id": f"kb-{self._seq}"}
        self.kb.append(stored)
        return stored

    def insert_recommendation(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        stored = {**row, "id": f"rec-{self._seq}"}
        self.recs.append(stored)
        return stored

    def set_triggered_job(self, change_event_id: str, kb_job: str) -> None:
        self.triggered.append((change_event_id, kb_job))


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(mode: DialMode = "api", *, halted: bool = False) -> tuple[CostGate, SpyCostStore]:
    store = SpyCostStore(mode=mode, halted=halted)
    return CostGate(store, NullCache()), store


def _item(i: int, **over: Any) -> dict[str, Any]:
    base = {
        "title": f"Policy item {i}",
        "summary": f"Summary of policy item {i} with an actionable detail.",
        "severity": "major",
        "category": "algorithm",
        "region": "global",
        "region_label": "Global",
        "source_name": "Google Search Central",
        "source_url": f"https://developers.google.com/search/item-{i}",
        "rec_title": f"Action {i}",
        "rec_why": f"Why {i}",
        "rec_action": f"Do {i}",
        "target_module": "content",
    }
    base.update(over)
    return base


def _items_json(n: int = 6, **over: Any) -> str:
    return json.dumps({"items": [_item(i, **over) for i in range(n)]})


# --------------------------------------------------------------------------- #
# build_generate_prompt
# --------------------------------------------------------------------------- #
def test_prompt_requests_exact_count_from_knowledge() -> None:
    prompt = build_generate_prompt(6)
    assert "6" in prompt
    assert "knowledge" in prompt.lower()


# --------------------------------------------------------------------------- #
# Happy path: N items + a single metered spend (TOKEN cost only)
# --------------------------------------------------------------------------- #
def test_happy_path_returns_items_and_meters_token_only() -> None:
    summarizer = SpySummarizer(text=_items_json(6), input_tokens=300, output_tokens=800)
    gate, store = _gate("api")
    settings = _settings()

    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=settings, count=6)

    assert result.status == "ok"
    assert len(result.items) == 6
    first = result.items[0]
    assert first.analysis.title == "Policy item 0"
    assert first.analysis.severity == "major"
    assert first.source_url == "https://developers.google.com/search/item-0"
    # exactly one paid call, carrying the GENERATOR system prompt (its N-item JSON contract)
    assert len(summarizer.calls) == 1
    assert summarizer.systems == [_GENERATE_SYSTEM_PROMPT]
    # ONE committed cost row under the policy dial = TOKEN cost only (no web-search term).
    assert len(store.commits) == 1
    feature, provider, cost = store.commits[0]
    assert (feature, provider) == ("policy", "Anthropic")
    expected = pricing.anthropic_cost(
        settings, model=settings.policy_generate_model, input_tokens=300, output_tokens=800
    )
    assert cost == expected and cost > 0


def test_count_defaults_to_settings_policy_daily_count() -> None:
    summarizer = SpySummarizer(text=_items_json(8))
    gate, _ = _gate("api")
    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=_settings())
    assert len(result.items) == 6  # capped at policy_daily_count (default 6), not the 8 returned


def test_requested_count_caps_items() -> None:
    summarizer = SpySummarizer(text=_items_json(6))
    gate, _ = _gate("api")
    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=_settings(), count=3)
    assert len(result.items) == 3


def test_bad_enums_are_clamped_and_source_url_falls_back_to_empty() -> None:
    payload = json.dumps(
        {"items": [_item(0, severity="bogus", category="nope", target_module="zzz", source_url="")]}
    )
    summarizer = SpySummarizer(text=payload)
    gate, _ = _gate("api")
    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=_settings(), count=1)
    item = result.items[0]
    assert item.analysis.severity == "info"  # clamped
    assert item.analysis.category == "algorithm"  # clamped
    assert item.analysis.target_module == "audit"  # clamped
    assert item.source_url == ""  # no web fallback under pure generation


# --------------------------------------------------------------------------- #
# parse_generation defensive
# --------------------------------------------------------------------------- #
def test_parse_generation_is_defensive() -> None:
    assert parse_generation("not json at all", count=6) == []
    assert parse_generation('{"items": "not a list"}', count=6) == []
    assert parse_generation('{"nope": 1}', count=6) == []
    # a non-dict item is skipped; a valid sibling survives.
    mixed = json.dumps({"items": ["oops", _item(1)]})
    got = parse_generation(mixed, count=6)
    assert len(got) == 1 and got[0].analysis.title == "Policy item 1"


def test_parse_generation_salvages_a_truncated_reply() -> None:
    # The real prod failure: the model hit the token ceiling mid-array, so the outer object
    # + array never close and the strict parse drops everything. Salvage recovers the items
    # that WERE fully written (0 and 1); the incomplete 3rd item is skipped.
    full = json.dumps({"items": [_item(0), _item(1), _item(2)]})
    truncated = full[: full.index("Policy item 2") + 4]  # chop mid-3rd item (its {} never closes)
    got = parse_generation(truncated, count=6)
    assert [g.analysis.title for g in got] == ["Policy item 0", "Policy item 1"]


# --------------------------------------------------------------------------- #
# Degrade paths
# --------------------------------------------------------------------------- #
def test_keyless_degrades_without_touching_the_gate() -> None:
    gate, store = _gate("api")
    result = run_policy_generation(summarizer=None, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert result.items == [] and store.commits == []


@pytest.mark.parametrize(
    ("mode", "halted", "expected"),
    [("off", False, "skip"), ("byhand", False, "manual"), ("api", True, "blocked_halt")],
)
def test_gate_block_degrades_without_calling_the_summarizer(
    mode: str, halted: bool, expected: str
) -> None:
    summarizer = SpySummarizer(text=_items_json(6))
    gate, store = _gate(mode, halted=halted)  # type: ignore[arg-type]
    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == f"cost_gate:{expected}"
    assert summarizer.calls == [] and store.commits == []  # no bypass


def test_generation_failure_degrades_with_no_spend() -> None:
    summarizer = RaisingSummarizer()
    gate, store = _gate("api")
    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=_settings())
    assert result.status == "degraded"
    assert result.reason == DEGRADE_GENERATION_FAILED
    assert summarizer.calls  # the gate allowed the attempt
    assert store.commits == []  # nothing billed - usage unknown


# --------------------------------------------------------------------------- #
# store_generated_items: change_event + kb_entry + recommendation per item
# --------------------------------------------------------------------------- #
def test_store_generated_items_writes_the_three_rows_per_item() -> None:
    summarizer = SpySummarizer(text=_items_json(2))
    gate, _ = _gate("api")
    result = run_policy_generation(summarizer=summarizer, gate=gate, settings=_settings(), count=2)

    store = FakeGenStore()
    written = store_generated_items(store, result.items)

    assert written == 2
    assert len(store.changes) == 2 and len(store.kb) == 2 and len(store.recs) == 2
    # KB refs are the generator's own kb-gen-* namespace, and link the change -> rec.
    assert all(r["kb_ref"].startswith("kb-gen-") for r in store.recs)
    assert store.triggered and store.triggered[0][1].startswith("kb-gen-")
    # the kb entry is not tied to a watched source row (source_id NULL).
    assert store.kb[0]["source_id"] is None
    assert store.recs[0]["status"] == "new" and store.recs[0]["scope"] == "global"
