"""Keyword-research schema lock: the SERVER-AUTHORITATIVE shape gate.

No ``frontend/lib/*.ts`` type mirrors this module, so ``test_contract_lock.py``
cannot cover it. This file is the equivalent: it FREEZES each response model's
emitted (aliased) key set and the ``search_intent`` enum tuple, so a drift is
still a build failure rather than a silently reshaped API.

The ``SearchIntent`` labels are load-bearing three times over - they are the wire
value, the ``public.search_intent`` DB enum, AND the exact cell the tool workspace
renders verbatim - so they are cross-locked against the migration and the provider
seam here, not just asserted in one place.
"""

from __future__ import annotations

import re
import typing
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.keyword_research.schemas import (
    _INTENTS,
    CannibalizationConflict,
    ClusterResponse,
    KeywordCreate,
    KeywordResearchRequest,
    KeywordResponse,
    KeywordStats,
    KeywordUpdate,
    ResearchQueuedResponse,
    SearchIntent,
)
from integrations.keyword_data import INTENT_LABELS

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0035_keyword_research.sql"

# The frozen wire shapes. A change here must be a DELIBERATE product decision.
_KEYWORD_KEYS = {
    "code", "keyword", "client", "volume", "difficulty", "cpc", "intent",
    "cluster", "opportunity", "winnable", "targetUrl", "geo",
}
_STATS_KEYS = {"saved", "clusters", "avgDifficulty"}
_CLUSTER_KEYS = {"name", "pillar", "intent", "size", "volume", "avgDifficulty", "client"}
_QUEUED_KEYS = {"seed", "queued"}
_CONFLICT_KEYS = {"targetUrl", "intents", "keywords"}

# The five display labels, in order. Capitalised = the exact tool-workspace cell.
_EXPECTED_INTENTS = ("Informational", "Commercial", "Transactional", "Navigational", "Local")


def _emitted(model: type[Any]) -> set[str]:
    """The JSON keys the model emits (serialization_alias wins, like FastAPI)."""
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


def _sql_enum(name: str) -> tuple[str, ...]:
    """The labels of ``create type public.<name> as enum (...)`` in migration 0035."""
    src = _MIGRATION.read_text(encoding="utf-8")
    match = re.search(rf"create type public\.{name} as enum\s*\((.*?)\);", src, re.DOTALL)
    assert match, f"enum {name} not found in {_MIGRATION}"
    labels = tuple(re.findall(r"'([^']*)'", match.group(1)))
    assert labels, f"no labels parsed for enum {name}"
    return labels


# --------------------------------------------------------------------------- #
# 1. Emitted key sets (the server-authoritative contract lock).
# --------------------------------------------------------------------------- #
def test_response_models_emit_exactly_the_frozen_key_sets() -> None:
    assert _emitted(KeywordResponse) == _KEYWORD_KEYS
    assert _emitted(KeywordStats) == _STATS_KEYS
    assert _emitted(ClusterResponse) == _CLUSTER_KEYS
    assert _emitted(ResearchQueuedResponse) == _QUEUED_KEYS
    assert _emitted(CannibalizationConflict) == _CONFLICT_KEYS


def test_no_response_model_exposes_the_internal_client_id() -> None:
    # `client` is the snapshotted display name; the tenant id must never be a field.
    for model in (KeywordResponse, ClusterResponse, KeywordStats, CannibalizationConflict):
        assert "client_id" not in _emitted(model)
        assert "clientId" not in _emitted(model)


def test_multi_word_wire_keys_are_camel_cased() -> None:
    # snake_case attributes, camelCase on the wire (ruff N815 forbids raw camelCase).
    assert KeywordResponse.model_fields["target_url"].serialization_alias == "targetUrl"
    assert KeywordStats.model_fields["avg_difficulty"].serialization_alias == "avgDifficulty"
    assert ClusterResponse.model_fields["avg_difficulty"].serialization_alias == "avgDifficulty"
    assert CannibalizationConflict.model_fields["target_url"].serialization_alias == "targetUrl"


# --------------------------------------------------------------------------- #
# 2. The search_intent enum - the display cells.
# --------------------------------------------------------------------------- #
def test_search_intent_literal_tuple_is_pinned_verbatim() -> None:
    assert typing.get_args(SearchIntent) == _EXPECTED_INTENTS


def test_search_intent_matches_the_db_enum_and_the_provider_seam() -> None:
    # Three declarations of the SAME five labels must agree: the wire Literal, the
    # public.search_intent DB enum, and the provider seam's INTENT_LABELS.
    assert _sql_enum("search_intent") == _EXPECTED_INTENTS
    assert INTENT_LABELS == _EXPECTED_INTENTS
    assert frozenset(_EXPECTED_INTENTS) == _INTENTS


def test_intent_labels_are_capitalised_display_cells() -> None:
    # The workspace renders these verbatim - a lowercase label would ship to the UI.
    for label in _EXPECTED_INTENTS:
        assert label[0].isupper(), f"{label} is not a display-cased cell"


def test_intent_source_db_enum_records_the_full_cascade() -> None:
    # The DB records how intent was decided. 'llm' is RESERVED (the shipped cascade in
    # service.classify_keyword_intent is provider -> serp_heuristic -> manual).
    assert _sql_enum("intent_source") == ("provider", "serp_heuristic", "llm", "manual")


def test_keyword_update_intent_accepts_only_the_five_labels() -> None:
    ann = KeywordUpdate.model_fields["intent"].annotation
    literal = next(a for a in typing.get_args(ann) if a is not type(None))
    assert typing.get_args(literal) == _EXPECTED_INTENTS


# --------------------------------------------------------------------------- #
# 3. from_row tolerance (psycopg hands back Decimals, NULLs, and missing joins).
# --------------------------------------------------------------------------- #
def _keyword_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "KW-00001", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "keyword": "invisalign cost", "volume": 8100, "difficulty": Decimal("42.00"),
        "cpc": Decimal("6.40"), "intent": "Commercial", "cluster_name": "invisalign",
        "opportunity": Decimal("79.84"), "winnable": True,
        "target_url": "https://np.example/invisalign", "geo": "us",
    }
    row.update(over)
    return row


def test_keyword_from_row_maps_and_never_leaks_client_id() -> None:
    dumped = KeywordResponse.from_row(_keyword_row()).model_dump(by_alias=True)
    assert set(dumped) == _KEYWORD_KEYS
    assert "client_id" not in dumped
    assert dumped["client"] == "NorthPeak Dental"  # the snapshot name, not the id
    assert dumped["targetUrl"] == "https://np.example/invisalign"
    assert dumped["cluster"] == "invisalign"


def test_keyword_from_row_coerces_decimals_to_rounded_floats() -> None:
    resp = KeywordResponse.from_row(
        _keyword_row(difficulty=Decimal("42.4449"), cpc=Decimal("6.409"),
                     opportunity=Decimal("79.8371"))
    )
    assert resp.difficulty == 42.44 and isinstance(resp.difficulty, float)
    assert resp.cpc == 6.41
    assert resp.opportunity == 79.84


def test_keyword_from_row_tolerates_a_totally_empty_row() -> None:
    # Every field is optional at the row level: an empty dict must not raise.
    resp = KeywordResponse.from_row({})
    assert resp.code == "" and resp.keyword == "" and resp.client == ""
    assert resp.volume == 0 and resp.difficulty == 0.0 and resp.cpc == 0.0
    assert resp.opportunity == 0.0 and resp.winnable is False
    assert resp.intent == "" and resp.cluster == "" and resp.target_url == "" and resp.geo == ""


def test_keyword_from_row_tolerates_explicit_nulls() -> None:
    # psycopg returns None for a NULL column / an unmatched left join.
    resp = KeywordResponse.from_row(
        _keyword_row(client_name=None, cluster_name=None, intent=None, winnable=None,
                     target_url=None, geo=None, volume=None, difficulty=None,
                     cpc=None, opportunity=None)
    )
    assert resp.client == "" and resp.cluster == ""  # unassigned bank row / unclustered
    assert resp.intent == "" and resp.winnable is False
    assert resp.volume == 0 and resp.difficulty == 0.0
    assert resp.cpc == 0.0 and resp.opportunity == 0.0
    assert resp.target_url == "" and resp.geo == ""


def test_keyword_from_row_blanks_an_unknown_intent() -> None:
    # An off-enum value can never reach the display cell.
    assert KeywordResponse.from_row(_keyword_row(intent="Bogus")).intent == ""
    assert KeywordResponse.from_row(_keyword_row(intent="commercial")).intent == ""  # case matters


@pytest.mark.parametrize("label", _EXPECTED_INTENTS)
def test_keyword_from_row_round_trips_every_intent_label(label: str) -> None:
    assert KeywordResponse.from_row(_keyword_row(intent=label)).intent == label


def test_stats_from_row_rounds_avg_difficulty_to_one_decimal() -> None:
    stats = KeywordStats.from_row(
        {"saved": 640, "clusters": 28, "avg_difficulty": Decimal("34.249")}
    )
    assert stats.saved == 640 and stats.clusters == 28
    assert stats.avg_difficulty == 34.2


def test_stats_from_row_empty_bank_is_zeros_not_an_error() -> None:
    stats = KeywordStats.from_row({})
    assert (stats.saved, stats.clusters, stats.avg_difficulty) == (0, 0, 0.0)
    nulls = KeywordStats.from_row({"saved": None, "clusters": None, "avg_difficulty": None})
    assert (nulls.saved, nulls.clusters, nulls.avg_difficulty) == (0, 0, 0.0)


def test_cluster_from_row_maps_and_hides_client_id() -> None:
    dumped = ClusterResponse.from_row({
        "client_id": "cl-secret", "client_name": "Verde Cafe", "name": "vegan brunch",
        "pillar_keyword": "vegan brunch", "dominant_intent": "Local", "size": 12,
        "total_volume": 3600, "avg_difficulty": Decimal("21.44"),
    }).model_dump(by_alias=True)
    assert set(dumped) == _CLUSTER_KEYS
    assert "client_id" not in dumped
    assert dumped["pillar"] == "vegan brunch"  # pillar_keyword -> pillar
    assert dumped["volume"] == 3600  # total_volume -> volume
    assert dumped["intent"] == "Local"
    assert dumped["avgDifficulty"] == 21.4


def test_cluster_from_row_tolerates_empty_and_unknown_intent() -> None:
    empty = ClusterResponse.from_row({})
    assert empty.name == "" and empty.pillar == "" and empty.intent == ""
    assert empty.size == 0 and empty.volume == 0 and empty.avg_difficulty == 0.0
    assert ClusterResponse.from_row({"dominant_intent": "???"}).intent == ""


# --------------------------------------------------------------------------- #
# 4. Request models (input validation at the edge).
# --------------------------------------------------------------------------- #
def test_keyword_create_requires_at_least_one_keyword_and_caps_the_batch() -> None:
    assert KeywordCreate(keywords=["a"]).keywords == ["a"]
    with pytest.raises(ValueError, match="at least 1 item"):
        KeywordCreate(keywords=[])
    with pytest.raises(ValueError, match="at most 500 items"):
        KeywordCreate(keywords=[f"kw{i}" for i in range(501)])


def test_keyword_create_accepts_the_camel_case_alias() -> None:
    assert KeywordCreate(clientId="cl-1", keywords=["a"]).client_id == "cl-1"  # type: ignore[call-arg]
    assert KeywordCreate(client_id="cl-1", keywords=["a"]).client_id == "cl-1"  # populate_by_name


def test_research_request_bounds_the_seed() -> None:
    assert KeywordResearchRequest(seed="plumber").seed == "plumber"
    with pytest.raises(ValueError, match="at least 1 character"):
        KeywordResearchRequest(seed="")
    with pytest.raises(ValueError, match="at most 200 characters"):
        KeywordResearchRequest(seed="x" * 201)


def test_keyword_update_fields_are_all_optional_and_track_unset() -> None:
    # The PATCH handler branches on exclude_unset, so "absent" must differ from "null":
    # an absent client_id changes nothing; an explicit null unassigns to the bank.
    assert KeywordUpdate().model_dump(exclude_unset=True) == {}
    assert KeywordUpdate(client_id=None).model_dump(exclude_unset=True) == {"client_id": None}
