"""P3-1 gate: audit models mirror lib/audit.ts + the runtime/when formatters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.audits import (
    PAID_AUDIT_TYPES,
    AuditCreate,
    AuditResponse,
    tier_from_db,
    tier_to_db,
)
from app.util.timefmt import format_runtime, format_when

pytestmark = pytest.mark.unit


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "aud-1",
        "client_name": "NorthPeak Dental",
        "url": "northpeakdental.com",
        "types": ["technical", "onpage", "local"],
        "tier": "paid",
        "status": "done",
        "score": 82,
        "scores": {"overall": 82.4, "technical": 90},
        "pdf_path": "audits/aud-1/report.pdf",
        "json_path": "audits/aud-1/findings.json",
        "runtime_seconds": 372,
        "created_at": datetime.now(UTC).isoformat(),
    }
    row.update(over)
    return row


def test_response_matches_auditrow_shape() -> None:
    body = AuditResponse.from_row(_row()).model_dump(by_alias=True)
    assert set(body) == {
        "id", "client", "url", "types", "tier", "status",
        "score", "runtime", "when", "pdf", "json",
        # The depth axis (migration 0084): the breadth this run was asked for and
        # the figure the pre-flight gate was given. `AuditRow` in
        # frontend/lib/audit.ts carries the same three; test_contract_lock.py
        # fails the build if either side moves alone.
        "depth", "maxPages", "estimatedCost",
        # The committed figure, beside the quote. Present so the comparison happens
        # where audits are reviewed rather than one screen away in Cost Controls.
        "cost",
        # Whether this audit is shared into the client's portal. It was settable
        # at creation and readable nowhere, so exposure could not be reviewed or
        # revoked. PATCH /audits/{id}/visibility is the other half.
        "visibleToClient",
        # Whether a client is attached at all. An audit may legitimately have
        # none - an internal or prospect run - and the UI needs that fact itself
        # rather than inferring it from an empty `client` name, which is the
        # client's NAME and not the same question.
        "hasClient",
    }
    assert body["client"] == "NorthPeak Dental"
    assert body["tier"] == "Paid"  # stored 'paid' -> surfaced 'Paid'
    assert body["status"] == "done"
    assert body["score"] == 82
    assert body["runtime"] == "6m 12s"
    assert body["pdf"] is True
    assert body["json"] is True  # serialization alias, not the field name json_
    assert body["types"] == ["technical", "onpage", "local"]


def test_response_pending_row() -> None:
    body = AuditResponse.from_row(
        _row(status="queued", score=None, runtime_seconds=None, pdf_path=None, json_path=None, tier="free")
    ).model_dump(by_alias=True)
    assert body["tier"] == "Free"
    assert body["score"] is None
    assert body["runtime"] == "—"
    assert body["pdf"] is False
    assert body["json"] is False


def test_response_filters_unknown_types() -> None:
    # The RESPONSE keeps `types`: historical rows carry a real selection, and
    # dropping the field would make an old audit's scope unreadable.
    body = AuditResponse.from_row(_row(types=["technical", "bogus", "geo"]))
    assert body.types == ["technical", "geo"]


def test_a_create_request_can_no_longer_ask_for_a_type_selection() -> None:
    """The picker is gone, and a request that still sends one is not an error.

    It could not do what its labels said: the engine has no per-dimension flag, so
    the deterministic crawl always ran in full and a run scoped to "on-page +
    technical" still returned GEO and strategy findings. Ignoring the field is the
    correct reading of such a request - the caller wanted an audit, and every
    audit is now the full one. Rejecting it would break older clients over a
    preference the server no longer has any way to honour.
    """
    c = AuditCreate(client_id="cl-1", url="example.com", types=["local", "technical"])
    assert not hasattr(c, "types")
    assert c.resolved_depth() == "free"  # Free tier by default


def test_tier_roundtrip() -> None:
    assert tier_to_db("Paid") == "paid"
    assert tier_to_db("Free") == "free"
    assert tier_from_db("paid") == "Paid"
    assert tier_from_db("free") == "Free"
    assert tier_from_db(None) == "Free"


def test_format_runtime() -> None:
    assert format_runtime(None) == "—"
    assert format_runtime(-1) == "—"
    assert format_runtime(372) == "6m 12s"
    assert format_runtime(66) == "1m 06s"
    assert format_runtime(45) == "45s"
    assert format_runtime(0) == "0s"


def test_format_when_buckets() -> None:
    now = datetime.now(UTC)
    assert format_when(now).startswith("Today · ")
    assert format_when(now - timedelta(days=1)).startswith("Yesterday · ")
    older = now - timedelta(days=5)
    assert format_when(older).startswith(older.strftime("%b %d") + " · ")
    assert format_when(None) == "—"
