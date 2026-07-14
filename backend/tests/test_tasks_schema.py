"""P5-2 gate: task schema helpers + TaskResponse shape (pure, no I/O)."""

from __future__ import annotations

from datetime import date

import pytest

from app.schemas.tasks import (
    TaskResponse,
    format_due,
    needs_review,
    next_status,
    type_from_db,
    type_to_db,
)

pytestmark = pytest.mark.unit

# The EXACT frontend Task field set - TaskResponse must expose these and no more.
_TASK_FIELDS = {"id", "title", "client", "type", "assignee", "priority", "status", "due"}


def test_type_roundtrip() -> None:
    assert type_to_db("Content Sprint") == "content_sprint"
    assert type_to_db("Local SEO") == "local_seo"
    assert type_from_db("content_sprint") == "Content Sprint"
    assert type_from_db("technical_audit") == "Technical Audit"
    # unknown canonical falls back safely (never raises)
    assert type_from_db(None) == "Technical Audit"


def test_needs_review_only_content_sprint() -> None:
    assert needs_review("content_sprint") is True
    for other in ("technical_audit", "actionable_audit", "backlink_audit", "local_seo", "publishing"):
        assert needs_review(other) is False


def test_next_status_mirrors_portal_ts() -> None:
    # todo -> in_progress for every type
    assert next_status("technical_audit", "todo") == "in_progress"
    assert next_status("content_sprint", "todo") == "in_progress"
    # in_progress -> review ONLY for content_sprint, else -> done
    assert next_status("content_sprint", "in_progress") == "review"
    assert next_status("technical_audit", "in_progress") == "done"
    assert next_status("publishing", "in_progress") == "done"
    # review -> done (reviewer sign-off); done / unknown -> None
    assert next_status("content_sprint", "review") == "done"
    assert next_status("technical_audit", "done") is None
    assert next_status("technical_audit", "bogus") is None


def test_format_due() -> None:
    assert format_due(date(2026, 7, 12)) == "Jul 12"
    assert format_due("2026-07-08") == "Jul 08"
    assert format_due(None) == ""
    assert format_due("not-a-date") == ""


def test_response_exposes_only_task_fields_with_public_code() -> None:
    row = {
        "id": "11111111-1111-1111-1111-111111111111",  # internal UUID - must NOT leak
        "code": "J-2041",
        "title": "Full technical crawl",
        "client_id": "cl-secret",  # must NOT leak
        "client_name": "NorthPeak Dental",
        "type": "content_sprint",
        "assignee_id": "u-bilal",
        "priority": "high",
        "status": "in_progress",
        "due_date": "2026-07-12",
        "audit_id": "aud-secret",  # must NOT leak
        "created_by": "u-owner",  # must NOT leak
        "created_at": "2026-07-01T00:00:00Z",
    }
    resp = TaskResponse.from_row(row)
    dumped = resp.model_dump()
    assert set(dumped) == _TASK_FIELDS
    assert dumped["id"] == "J-2041"  # the PUBLIC code, never the UUID
    assert dumped["type"] == "Content Sprint"  # display label
    assert dumped["client"] == "NorthPeak Dental"
    assert dumped["assignee"] == "u-bilal"
    assert dumped["due"] == "Jul 12"
    # none of the internal columns surface, under any name
    assert "cl-secret" not in dumped.values()
    assert "aud-secret" not in dumped.values()


def test_response_unassigned_and_defaults() -> None:
    row = {"code": "J-9", "title": "x", "type": "publishing", "assignee_id": None,
           "priority": "med", "status": "todo", "due_date": None}
    dumped = TaskResponse.from_row(row).model_dump()
    assert dumped["assignee"] == ""
    assert dumped["due"] == ""
    assert dumped["type"] == "Publishing"
