"""The campaign as a durable, pollable thing — the "nothing came back" fix.

2026-09-01: a campaign POST returned 201 "queued 45 directories", every row was
refused within a second (43 no_verified_spec / 1 no_engine / 1 price_unknown), and
the batch then ceased to exist as a unit — no id, no rollup, the skip ledger gone
with the HTTP response. These tests pin the shape that makes that night legible:
the response carries a campaignId, and the rollup renders the per-reason breakdown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.citations.service import summarize_campaign_rows

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 1, 19, 0, tzinfo=UTC)


def _row(directory: str, status: str, reason: str = "", *, minutes_old: int = 0,
         live_url: str = "") -> dict[str, Any]:
    return {
        "id": f"c-{directory}", "directory": directory, "submit_status": status,
        "blocked_reason": reason, "error": "", "live_url": live_url,
        "updated_at": _NOW - timedelta(minutes=minutes_old),
    }


def test_the_exact_outage_rollup_renders_its_reasons() -> None:
    """43/1/1 — tonight's refusals, renderable at last. Goes red if blocked_reason
    stops being written or the rollup stops grouping on it."""
    rows = (
        [_row(f"dir-{i}", "ready_for_human", "no_verified_spec") for i in range(43)]
        + [_row("Apple Business Connect", "ready_for_human", "no_engine")]
        + [_row("Data Axle (Local Listings)", "blocked", "price_unknown")]
    )
    rollup = summarize_campaign_rows(rows, now=_NOW)
    assert rollup["by_blocked_reason"] == {
        "no_verified_spec": 43, "no_engine": 1, "price_unknown": 1,
    }
    assert rollup["by_status"] == {"ready_for_human": 44, "blocked": 1}
    assert rollup["stuck"] == 0
    assert rollup["live_urls"] == []


def test_stale_in_flight_rows_count_as_stuck_never_as_progress() -> None:
    rows = [
        _row("Yelp", "queued", minutes_old=20),
        _row("Hotfrog", "queued", minutes_old=1),
        _row("Brownbook", "submitting", minutes_old=45),
    ]
    rollup = summarize_campaign_rows(rows, now=_NOW)
    assert rollup["stuck"] == 2
    assert rollup["by_status"] == {"queued": 2, "submitting": 1}


def test_only_a_fetch_verified_live_row_contributes_a_url() -> None:
    rows = [
        _row("Brownbook", "live", live_url="https://brownbook.net/biz/1"),
        # `submitted` with a URL-shaped value must NOT count — nothing confirmed it.
        _row("Hotfrog", "submitted", live_url="https://hotfrog.example/biz/2"),
    ]
    rollup = summarize_campaign_rows(rows, now=_NOW)
    assert rollup["live_urls"] == [
        {"directory": "Brownbook", "url": "https://brownbook.net/biz/1", "status": "live"}
    ]
