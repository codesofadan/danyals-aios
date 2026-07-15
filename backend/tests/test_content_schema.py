"""Unit tests for the Content module's response/request models + server rules.

Guards the contract shape (the exact 15 ``ContentJob`` keys, the ``schema`` alias
gotcha) and the two server rules the router reuses (``auto_framework`` /
``schema_for``) - no DB, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.content import (
    ContentJobResponse,
    auto_framework,
    schema_for,
    to_response,
)

pytestmark = pytest.mark.unit

# The frontend ``ContentJob`` keys, verbatim (order-independent).
_CONTRACT_KEYS = {
    "id", "client", "color", "pageType", "topic", "framework", "auto",
    "target", "status", "cost", "words", "schema", "images", "stage", "ago",
}


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "code": "CJ-4200",
        "client_name": "Verde Cafe",
        "color": "#22c55e",
        "page_type": "service",
        "topic": "Emergency plumbing in Austin",
        "framework": "AIDA",
        "auto": True,
        "target": "WordPress",
        "status": "queued",
        "cost": 16,
        "words": 0,
        "schema_type": "Service",
        "images": 0,
        "stage": "Queued",
        "created_at": datetime(2026, 7, 16, tzinfo=UTC),
    }
    row.update(over)
    return row


def test_response_emits_exactly_the_15_contract_keys() -> None:
    emitted = {
        f.serialization_alias or f.alias or name
        for name, f in ContentJobResponse.model_fields.items()
    }
    assert emitted == _CONTRACT_KEYS


def test_schema_attribute_is_emitted_as_wire_key_schema() -> None:
    # The Python attribute is `schema_type` (dodging Pydantic's reserved `schema`),
    # but the emitted JSON key MUST be `schema` for the frontend contract.
    dumped = to_response(_row()).model_dump(by_alias=True)
    assert set(dumped) == _CONTRACT_KEYS
    assert "schema" in dumped and "schema_type" not in dumped
    assert dumped["schema"] == "Service"


def test_id_is_the_public_code_never_a_uuid() -> None:
    resp = to_response(_row(code="CJ-4207"))
    assert resp.id == "CJ-4207"


def test_no_internal_columns_leak() -> None:
    dumped = to_response(
        _row(id="00000000-0000-0000-0000-000000000001", client_id="secret-uuid")
    ).model_dump(by_alias=True)
    assert "client_id" not in dumped
    assert dumped["id"] == "CJ-4200"  # the public code, not the injected uuid


@pytest.mark.parametrize(
    ("page_type", "framework"),
    [("service", "AIDA"), ("local", "BAB"), ("blog", "PAS")],
)
def test_auto_framework_rules(page_type: str, framework: str) -> None:
    assert auto_framework(page_type) == framework


@pytest.mark.parametrize(
    ("page_type", "schema"),
    [("service", "Service"), ("local", "LocalBusiness"), ("blog", "Article")],
)
def test_schema_for_rules(page_type: str, schema: str) -> None:
    assert schema_for(page_type) == schema


def test_unknown_enum_values_fall_back_safely() -> None:
    resp = to_response(_row(page_type="???", framework="???", target="???", status="???"))
    assert resp.page_type == "service"
    assert resp.framework == "AIDA"
    assert resp.target == "WordPress"
    assert resp.status == "queued"


def test_missing_created_at_gives_just_now() -> None:
    row = _row()
    del row["created_at"]
    assert to_response(row).ago == "just now"
