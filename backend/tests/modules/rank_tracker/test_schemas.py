"""Rank-tracker wire shapes: the frozen key sets + the enum tuples.

These models are SERVER-AUTHORITATIVE (no ``lib/*.ts`` type mirrors them), so there is
no contract-lock file to catch a drift. These tests ARE the lock: they freeze the
emitted key set of every response model and pin each enum tuple against the ``0036``
migration's ``create type``, so an app-vs-database divergence fails here rather than as
an opaque 22P02 at runtime.

The load-bearing assertion in this file is that ``position`` SERIALIZES AS NULL when
unranked. A ``or 0`` anywhere in the projection chain would turn "not in the top 100"
into "position 0" - better than #1 - which is exactly the kind of quiet lie a shape
test exists to catch.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.rank_tracker.schemas import (
    CADENCES,
    DEVICES,
    DIRECTIONS,
    ENGINES,
    STATUSES,
    RankChange,
    RankCheckQueued,
    RankCostProjection,
    RankHistoryPoint,
    RankKeywordResponse,
    RankKeywordsAdded,
    RankStats,
)

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[4] / "db" / "migrations" / "0036_rank_tracker.sql"
)

_KEYWORD_KEYS = {
    "code", "keyword", "client", "position", "change", "bestPosition", "url",
    "targetUrl", "tags", "engine", "device", "location", "cadence", "status",
    "features", "checked", "stale",
}
_STATS_KEYS = {"tracked", "avgPosition", "topThree"}
_HISTORY_KEYS = {"date", "position", "url", "features", "delta"}
_PROJECTION_KEYS = {
    "client", "tracked", "daily", "weekly", "checksPerMonth", "costPerCheck",
    "monthlyCost", "budgetCap", "budgetSpent", "budgetRemaining", "withinBudget",
    "provider", "live", "message",
}


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "kw-1", "code": "RK-00001", "client_id": "cl-secret",
        "client_name": "NorthPeak Dental", "keyword": "dental implants karachi",
        "normalized_keyword": "dental implants karachi", "target_url": "https://np.example/x",
        "engine": "google", "device": "desktop", "location": "Karachi,Pakistan",
        "language": "en", "country": "pk", "tags": ["money"], "cadence": "weekly",
        "status": "active", "latest_position": 3, "latest_url": "https://np.example/y",
        "previous_position": 7, "best_position": 2, "latest_features": ["local_pack"],
        "latest_checked_at": datetime.now(UTC),
    }
    row.update(over)
    return row


def _dump(model: object) -> dict[str, object]:
    return model.model_dump(by_alias=True)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# 1. Frozen key sets.
# --------------------------------------------------------------------------- #
def test_keyword_response_emits_exactly_the_frozen_key_set() -> None:
    body = _dump(
        RankKeywordResponse.from_row(
            _row(), change=RankChange(value="4", direction="up"), stale=False
        )
    )
    assert set(body) == _KEYWORD_KEYS


def test_stats_emits_exactly_the_frozen_key_set() -> None:
    body = _dump(RankStats.from_row({"tracked": 128, "avg_position": 8.44, "top_three": 34}))
    assert set(body) == _STATS_KEYS
    assert body == {"tracked": 128, "avgPosition": 8.4, "topThree": 34}


def test_history_point_emits_exactly_the_frozen_key_set() -> None:
    body = _dump(
        RankHistoryPoint.from_row(
            {"checked_on": "2026-07-16", "position": 3, "ranking_url": "/x",
             "serp_features": ["ai_overview"], "delta": 4}
        )
    )
    assert set(body) == _HISTORY_KEYS


def test_projection_emits_exactly_the_frozen_key_set() -> None:
    body = _dump(
        RankCostProjection(
            client="Acme", tracked=10, daily=2, weekly=8, checks_per_month=95.6,
            cost_per_check=0.001, monthly_cost=0.0956, budget_cap=50.0, budget_spent=10.0,
            budget_remaining=40.0, within_budget=True, provider="serper", live=True,
            message="ok",
        )
    )
    assert set(body) == _PROJECTION_KEYS


def test_added_response_nests_the_keywords_and_the_projection() -> None:
    # The bulk-add's whole point: the standing commitment travels WITH the rows.
    added = RankKeywordsAdded(
        keywords=[
            RankKeywordResponse.from_row(
                _row(), change=RankChange(value="4", direction="up"), stale=False
            )
        ],
        projection=RankCostProjection(
            client="Acme", tracked=1, daily=0, weekly=1, checks_per_month=4.35,
            cost_per_check=0.001, monthly_cost=0.0044, budget_cap=0.0, budget_spent=0.0,
            budget_remaining=0.0, within_budget=True, provider="serper", live=True,
            message="ok",
        ),
    )
    body = _dump(added)
    assert set(body) == {"keywords", "projection"}
    assert set(body["keywords"][0]) == _KEYWORD_KEYS  # type: ignore[index]


def test_check_queued_shape() -> None:
    assert _dump(RankCheckQueued(code="RK-00001", queued=True)) == {
        "code": "RK-00001", "queued": True, "reason": ""
    }


# --------------------------------------------------------------------------- #
# 2. client_id never leaks.
# --------------------------------------------------------------------------- #
def test_the_internal_client_id_never_reaches_the_wire() -> None:
    """The row carries the secret tenant id; the response must carry only the name."""
    body = _dump(
        RankKeywordResponse.from_row(
            _row(), change=RankChange(value="4", direction="up"), stale=False
        )
    )
    assert "cl-secret" not in str(body)
    assert body["client"] == "NorthPeak Dental"  # the snapshot replaces the id


# --------------------------------------------------------------------------- #
# 3. The load-bearing NULL: unranked is not position 0.
# --------------------------------------------------------------------------- #
def test_an_unranked_keyword_serializes_position_as_null_not_zero() -> None:
    """``None`` means "checked, not in the top-N". Coercing it to 0 would render the
    keyword as ranking BETTER than #1 - the single most dangerous silent lie here."""
    body = _dump(
        RankKeywordResponse.from_row(
            _row(latest_position=None, best_position=None),
            change=RankChange(value="lost", direction="lost"),
            stale=False,
        )
    )
    assert body["position"] is None
    assert body["bestPosition"] is None


def test_an_unranked_history_point_serializes_position_as_null() -> None:
    body = _dump(
        RankHistoryPoint.from_row(
            {"checked_on": "2026-07-16", "position": None, "ranking_url": "",
             "serp_features": [], "delta": None}
        )
    )
    assert body["position"] is None and body["delta"] is None


@pytest.mark.parametrize("garbage", ["", "n/a", object()])
def test_an_uncoercible_position_degrades_to_null_never_to_zero(garbage: object) -> None:
    body = _dump(
        RankKeywordResponse.from_row(
            _row(latest_position=garbage), change=RankChange(value="0", direction="flat"),
            stale=False,
        )
    )
    assert body["position"] is None


def test_a_never_checked_keyword_reads_never() -> None:
    body = _dump(
        RankKeywordResponse.from_row(
            _row(latest_checked_at=None), change=RankChange(value="0", direction="flat"),
            stale=True,
        )
    )
    assert body["checked"] == "never"
    assert body["stale"] is True


# --------------------------------------------------------------------------- #
# 4. The enum tuples match the 0036 migration.
# --------------------------------------------------------------------------- #
def _enum_labels(type_name: str) -> tuple[str, ...]:
    """The labels of one ``create type ... as enum (...)`` in the 0036 migration.

    Asserts on the match, so a migration reformat FAILS loudly rather than silently
    comparing against an empty tuple (which every test below would then pass).
    """
    sql = _MIGRATION.read_text(encoding="utf-8")
    match = re.search(
        rf"create type public\.{type_name} as enum\s*\(([^)]*)\)", sql, re.DOTALL
    )
    assert match, f"0036 no longer declares the {type_name} enum"
    labels = tuple(re.findall(r"'([^']+)'", match.group(1)))
    assert labels, f"no labels parsed for {type_name}"
    return labels


@pytest.mark.parametrize(
    ("python_tuple", "type_name"),
    [
        (ENGINES, "rank_engine"),
        (DEVICES, "rank_device"),
        (STATUSES, "rank_status"),
        (CADENCES, "rank_cadence"),
    ],
)
def test_every_enum_matches_the_migration_byte_for_byte(
    python_tuple: tuple[str, ...], type_name: str
) -> None:
    """The app's Literal and the database's enum must agree exactly - a value that
    passes Pydantic but not Postgres surfaces as an opaque 22P02, not a clean 422."""
    assert python_tuple == _enum_labels(type_name)


def test_the_enum_reader_rejects_an_unknown_type() -> None:
    # Proves the reader MATCHES rather than vacuously returning empty data.
    with pytest.raises(AssertionError, match="no longer declares"):
        _enum_labels("definitely_not_a_real_enum")


def test_direction_tuple_is_pinned() -> None:
    # Not a DB enum - a wire vocabulary the frontend switches on. Pin it anyway: a
    # silently added direction would render as an unstyled cell.
    assert DIRECTIONS == ("up", "down", "flat", "new", "lost")
