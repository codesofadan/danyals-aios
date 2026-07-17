"""Competitor-intel wire shapes - the SERVER-AUTHORITATIVE contract lock.

No ``frontend/lib/*.ts`` type mirrors this module, so ``test_contract_lock``'s field-set
lock does not apply. These tests are its substitute: they FREEZE the emitted key set of
every response model and pin each enum tuple against the migration's own ``create type``,
so a drift is caught here rather than by a frontend that silently renders undefined.

The enum tuples are read out of ``db/migrations/0037_competitor_intel.sql`` rather than
retyped, so the Python and the database cannot disagree - and ``search_intent`` is
asserted to be REUSED from 0035 rather than re-declared.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.competitor_intel.schemas import (
    DISCOVERY_SOURCES,
    GAP_TYPES,
    SEARCH_INTENTS,
    AnalysisQueued,
    BacklinkGapResponse,
    CompetitorCreate,
    CompetitorResponse,
    CompetitorStats,
    CompetitorUpdate,
    DiscoveryQueued,
    GapPromoted,
    KeywordGapResponse,
    ShareOfVoiceEntry,
    ShareOfVoiceResponse,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3].parent
_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0037_competitor_intel.sql"
_KEYWORD_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0035_keyword_research.sql"


def _enum_labels(sql_text: str, type_name: str) -> list[str]:
    """The labels of one ``create type ... as enum (...)`` block, in declared order."""
    match = re.search(
        rf"create type public\.{type_name} as enum\s*\((.*?)\)", sql_text, re.DOTALL
    )
    assert match, f"enum '{type_name}' not found - this reader is parsing something else"
    return re.findall(r"'([^']*)'", match.group(1))


# --------------------------------------------------------------------------- #
# 1. Enum fidelity vs the migration.
# --------------------------------------------------------------------------- #
def test_the_migration_exists_and_the_reader_matches() -> None:
    # Guards the reader itself: a regex that stopped matching would make every enum
    # assertion below pass vacuously.
    assert _MIGRATION.exists(), f"{_MIGRATION} is missing"
    with pytest.raises(AssertionError, match="not found"):
        _enum_labels(_MIGRATION.read_text(encoding="utf-8"), "definitely_not_an_enum")


def test_discovery_source_matches_the_migration() -> None:
    labels = _enum_labels(_MIGRATION.read_text(encoding="utf-8"), "discovery_source")
    assert tuple(labels) == DISCOVERY_SOURCES == ("manual", "serp_auto")


def test_gap_type_matches_the_migration() -> None:
    labels = _enum_labels(_MIGRATION.read_text(encoding="utf-8"), "gap_type")
    assert tuple(labels) == GAP_TYPES == ("missing", "weak", "shared", "untapped")


def test_search_intent_is_reused_from_0035_never_redeclared() -> None:
    """0037 must NOT declare its own ``search_intent``.

    A gap's intent is the same fact as a bank keyword's intent, and ``promote`` writes
    the value straight into ``public.keywords`` - a parallel enum would be an immediate
    cast error the moment the two drifted by one label.
    """
    sql_text = _MIGRATION.read_text(encoding="utf-8")
    assert "create type public.search_intent" not in sql_text, (
        "0037 re-declares search_intent - it must REUSE 0035's enum"
    )
    assert "public.search_intent" in sql_text, "0037 should reference 0035's search_intent"
    # ... and the module's tuple must equal the one 0035 actually declares.
    declared = _enum_labels(_KEYWORD_MIGRATION.read_text(encoding="utf-8"), "search_intent")
    assert tuple(declared) == SEARCH_INTENTS


def test_search_intent_matches_the_keyword_data_seam() -> None:
    """The same five labels the provider seam normalises onto - so a gap promoted into
    the bank carries an intent the bank already understands."""
    from integrations.keyword_data import INTENT_LABELS

    assert SEARCH_INTENTS == INTENT_LABELS


# --------------------------------------------------------------------------- #
# 2. Frozen emitted key sets.
# --------------------------------------------------------------------------- #
def _competitor_row() -> dict[str, object]:
    return {
        "code": "CI-0001", "domain": "rival.com", "client_id": "cl-secret",
        "client_name": "NorthPeak Dental", "label": "Main rival",
        "discovery_source": "manual", "tracked": True, "overlap_pct": 38.5,
        "keyword_gaps_count": 24, "common_keywords": 12, "share_of_voice": 18.25,
        "last_analyzed_at": None,
    }


def test_competitor_response_emits_a_frozen_key_set() -> None:
    body = CompetitorResponse.from_row(_competitor_row()).model_dump(by_alias=True)
    assert set(body) == {
        "code", "domain", "client", "label", "source", "tracked", "overlap",
        "keywordGaps", "commonKeywords", "shareOfVoice", "analyzed",
    }


def test_keyword_gap_response_emits_a_frozen_key_set() -> None:
    body = KeywordGapResponse.from_row(
        {
            "id": "g-1", "keyword": "dental implants", "volume": 8100,
            "difficulty": 42.0, "intent": "Commercial", "competitor_position": 3,
            "client_position": None, "gap_type": "untapped", "opportunity": 71.5,
            "keyword_id": None, "client_id": "cl-secret",
        }
    ).model_dump(by_alias=True)
    assert set(body) == {
        "id", "keyword", "volume", "difficulty", "intent", "competitorPosition",
        "clientPosition", "gapType", "opportunity", "promoted",
    }


def test_stats_and_report_shapes_emit_frozen_key_sets() -> None:
    stats = CompetitorStats.from_row(
        {"tracked": 18, "keyword_gaps": 92, "share_of_voice": 41.0}
    ).model_dump(by_alias=True)
    assert set(stats) == {"tracked", "keywordGaps", "shareOfVoice", "provisional"}

    entry = ShareOfVoiceEntry(
        domain="rival.com", label="", is_client=False, visibility=120.5, share=18.25
    )
    assert set(entry.model_dump(by_alias=True)) == {
        "domain", "label", "isClient", "visibility", "share"
    }
    report = ShareOfVoiceResponse(client="NorthPeak", entries=[entry], curve=[0.3, 0.1])
    assert set(report.model_dump(by_alias=True)) == {
        "client", "entries", "curve", "provisional"
    }

    gap = BacklinkGapResponse(ref_domain="dir.com", competitors=3, authority=61, spam=2)
    assert set(gap.model_dump(by_alias=True)) == {
        "refDomain", "competitors", "authority", "spam"
    }


def test_ack_shapes_emit_frozen_key_sets() -> None:
    assert set(DiscoveryQueued(client="NorthPeak", queued=True).model_dump(by_alias=True)) == {
        "client", "queued", "reason"
    }
    assert set(AnalysisQueued(code="CI-0001", queued=True).model_dump(by_alias=True)) == {
        "code", "queued", "reason"
    }
    assert set(
        GapPromoted(keyword="x", code="KW-00001", created=True).model_dump(by_alias=True)
    ) == {"keyword", "code", "created"}


# --------------------------------------------------------------------------- #
# 3. The load-bearing semantics.
# --------------------------------------------------------------------------- #
def test_client_id_never_appears_in_any_emitted_body() -> None:
    """The internal client_id must NEVER leak - ``client`` is the snapshotted name.
    Both source rows below deliberately CARRY a client_id."""
    competitor = CompetitorResponse.from_row(_competitor_row()).model_dump(by_alias=True)
    assert "client_id" not in competitor and "clientId" not in competitor
    assert competitor["client"] == "NorthPeak Dental"
    assert "cl-secret" not in str(competitor)

    gap = KeywordGapResponse.from_row(
        {"id": "g-1", "keyword": "k", "client_id": "cl-secret", "client_position": 4}
    ).model_dump(by_alias=True)
    assert "cl-secret" not in str(gap)


def test_a_null_client_position_survives_as_null_never_zero() -> None:
    """THE module rule, at the wire edge: ``null`` = the client does not rank (a PURE
    gap). An ``or 0`` anywhere in the projection would render it as position 0 - i.e.
    better than #1 - and invert the board."""
    gap = KeywordGapResponse.from_row(
        {"id": "g-1", "keyword": "k", "client_position": None, "competitor_position": 3}
    )
    assert gap.client_position is None
    assert gap.model_dump(by_alias=True)["clientPosition"] is None


def test_a_real_zero_position_is_not_confused_with_absent() -> None:
    gap = KeywordGapResponse.from_row({"id": "g-1", "keyword": "k", "client_position": 0})
    assert gap.client_position == 0
    assert gap.client_position is not None


def test_promoted_is_driven_by_the_keyword_id_stamp() -> None:
    """The idempotency signal: a gap already in the bank must not offer the action
    again."""
    assert not KeywordGapResponse.from_row(
        {"id": "g", "keyword": "k", "keyword_id": None}
    ).promoted
    assert KeywordGapResponse.from_row(
        {"id": "g", "keyword": "k", "keyword_id": "kw-1"}
    ).promoted


def test_an_unanalyzed_competitor_reads_never_not_a_zero_gap_rival() -> None:
    """An un-analysed competitor must be legible as exactly that, rather than looking
    like a rival we checked and found harmless."""
    assert CompetitorResponse.from_row(_competitor_row()).analyzed == "never"


def test_share_of_voice_is_always_flagged_provisional() -> None:
    """It is a CTR-curve estimate, not a measurement - and the flag is not decoration:
    it is the difference between a comparable index and a traffic claim."""
    assert CompetitorStats.from_row({"tracked": 1, "keyword_gaps": 0, "share_of_voice": 0}).provisional
    assert ShareOfVoiceResponse(client="c", entries=[], curve=[0.3]).provisional


def test_create_accepts_camel_case_and_requires_a_client() -> None:
    body = CompetitorCreate.model_validate({"clientId": "cl-1", "domain": "rival.com"})
    assert body.client_id == "cl-1"
    with pytest.raises(ValueError, match="clientId"):
        CompetitorCreate.model_validate({"domain": "rival.com"})


def test_the_competitor_domain_is_not_patchable() -> None:
    """The domain is half the uniqueness key and the subject of every gap already
    analysed; re-pointing it would silently re-label another business's ranking data as
    this one's. It must not be an accepted PATCH field."""
    assert "domain" not in CompetitorUpdate.model_fields
    patch = CompetitorUpdate.model_validate({"domain": "other.com", "label": "x"})
    assert patch.model_dump(exclude_unset=True) == {"label": "x"}
