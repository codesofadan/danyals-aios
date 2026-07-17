"""Billing schema lock: the SERVER-AUTHORITATIVE shape gate.

No ``frontend/lib/*.ts`` type mirrors the invoice models, so ``test_contract_lock.py``
cannot cover them. This file is the equivalent: it FREEZES each response model's
emitted (aliased) key set and the ``invoice_status`` / ``invoice_kind`` enum tuples
against the ``0043`` migration, so a drift is a build failure rather than a silently
reshaped API.

The single most important assertion here is a NEGATIVE one:
``test_no_request_model_can_express_a_total``. The server computes every total; the
request models must give a caller no field in which to state one. "Ignored if
supplied" is a rule someone deletes - an absent field is a rule the type system keeps.
"""

from __future__ import annotations

import re
import typing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.billing.schemas import (
    _KINDS,
    _STATUSES,
    BillingStats,
    InvoiceCreate,
    InvoiceDetailResponse,
    InvoiceKind,
    InvoiceLineCreate,
    InvoiceLineItemResponse,
    InvoiceResponse,
    InvoiceStatus,
    InvoiceStatusUpdate,
    InvoiceUpdate,
    RevenuePeriodResponse,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0043_billing.sql"

# The frozen wire shapes. A change here must be a DELIBERATE product decision.
_INVOICE_KEYS = {
    "number", "client", "amount", "subtotal", "tax", "currency", "status", "kind",
    "issued", "due", "periodStart", "periodEnd", "notes", "paidAt", "paidMethod",
}
_DETAIL_KEYS = _INVOICE_KEYS | {"lines"}
_LINE_KEYS = {"id", "description", "quantity", "unitAmount", "lineTotal", "sortOrder"}
_STATS_KEYS = {"mrr", "openInvoices", "pastDue"}
_REVENUE_KEYS = {"period", "invoices", "collected"}

# The lifecycle + kind labels, in order.
_EXPECTED_STATUSES = ("draft", "open", "paid", "past_due", "void", "refunded")
_EXPECTED_KINDS = ("retainer", "one_off")

# Every model a caller POSTs/PATCHes. None of them may carry a money TOTAL.
_REQUEST_MODELS = (InvoiceCreate, InvoiceUpdate, InvoiceLineCreate, InvoiceStatusUpdate)


def _emitted(model: type[Any]) -> set[str]:
    """The JSON keys the model emits (serialization_alias wins, like FastAPI)."""
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


def _sql_enum(name: str) -> tuple[str, ...]:
    """The labels of ``create type public.<name> as enum (...)`` in migration 0043."""
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
    assert _emitted(InvoiceResponse) == _INVOICE_KEYS
    assert _emitted(InvoiceDetailResponse) == _DETAIL_KEYS
    assert _emitted(InvoiceLineItemResponse) == _LINE_KEYS
    assert _emitted(BillingStats) == _STATS_KEYS
    assert _emitted(RevenuePeriodResponse) == _REVENUE_KEYS


def test_the_detail_is_the_header_plus_lines_not_a_different_shape() -> None:
    # Subclassing is the contract: a consumer must read number/amount/status
    # identically off a list row and off the detail.
    assert issubclass(InvoiceDetailResponse, InvoiceResponse)
    assert _emitted(InvoiceDetailResponse) - _emitted(InvoiceResponse) == {"lines"}


def test_no_response_model_exposes_the_internal_client_id() -> None:
    # `client` is the snapshotted display name; the tenant id must never be a field.
    for model in (InvoiceResponse, InvoiceDetailResponse, BillingStats, RevenuePeriodResponse):
        assert "client_id" not in _emitted(model)
        assert "clientId" not in _emitted(model)


def test_the_public_number_is_the_id_and_the_uuid_is_not_a_field() -> None:
    # INV-#### is what every route addresses; the internal uuid never ships.
    assert "number" in _emitted(InvoiceResponse)
    assert "id" not in _emitted(InvoiceResponse)


def test_multi_word_wire_keys_are_camel_cased() -> None:
    # snake_case attributes, camelCase on the wire (ruff N815 forbids raw camelCase).
    assert InvoiceResponse.model_fields["period_start"].serialization_alias == "periodStart"
    assert InvoiceResponse.model_fields["period_end"].serialization_alias == "periodEnd"
    assert InvoiceResponse.model_fields["paid_at"].serialization_alias == "paidAt"
    assert InvoiceResponse.model_fields["paid_method"].serialization_alias == "paidMethod"
    assert InvoiceLineItemResponse.model_fields["unit_amount"].serialization_alias == "unitAmount"
    assert InvoiceLineItemResponse.model_fields["line_total"].serialization_alias == "lineTotal"
    assert BillingStats.model_fields["open_invoices"].serialization_alias == "openInvoices"
    assert BillingStats.model_fields["past_due"].serialization_alias == "pastDue"


# --------------------------------------------------------------------------- #
# 2. THE load-bearing negative: a caller cannot express a total.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model", _REQUEST_MODELS, ids=[m.__name__ for m in _REQUEST_MODELS])
def test_no_request_model_can_express_a_total(model: type[Any]) -> None:
    """The server computes every money total; no request model may carry one.

    This is stronger than "a supplied total is ignored": the FIELD DOES NOT EXIST, so
    there is no code path that could start honouring it later. `tax` is the one money
    input a caller legitimately states - it is not derivable from the lines.
    """
    for banned in ("total", "subtotal", "line_total", "lineTotal", "amount"):
        assert banned not in model.model_fields, f"{model.__name__} must not accept {banned}"
        assert banned not in _emitted(model)


def test_invoice_create_has_no_total_field() -> None:
    # Spelled out separately from the sweep above so a regression names itself.
    assert "total" not in InvoiceCreate.model_fields
    assert "lines" in InvoiceCreate.model_fields  # ... the total's only inputs
    assert "tax" in InvoiceCreate.model_fields


def test_a_supplied_total_is_rejected_as_an_unknown_field_not_absorbed() -> None:
    # Pydantic ignores unknown keys by default, so a client that POSTs a total gets a
    # server-computed invoice rather than an error - the important half is that the
    # value never lands anywhere.
    built = InvoiceCreate.model_validate(
        {"clientId": "cl-1", "total": 999_999, "subtotal": 999_999, "lines": []}
    )
    assert not hasattr(built, "total")
    assert not hasattr(built, "subtotal")
    assert "999999" not in built.model_dump_json()


def test_invoice_create_cannot_set_a_status_or_reassign_the_payer() -> None:
    # A new invoice is ALWAYS a draft (status is reached via /finalize); PATCH cannot
    # move the payer (re-billing someone else is a new invoice, not an edit).
    assert "status" not in InvoiceCreate.model_fields
    assert "status" not in InvoiceUpdate.model_fields
    assert "client_id" not in InvoiceUpdate.model_fields
    assert "clientId" not in _emitted(InvoiceUpdate)


def test_invoice_create_requires_a_client() -> None:
    # An invoice always has a payer (0043 declares client_id NOT NULL).
    assert InvoiceCreate.model_fields["client_id"].is_required()
    with pytest.raises(ValueError, match="clientId"):
        InvoiceCreate.model_validate({})


# --------------------------------------------------------------------------- #
# 3. The invoice_status / invoice_kind enums.
# --------------------------------------------------------------------------- #
def test_invoice_status_literal_tuple_is_pinned_verbatim() -> None:
    assert typing.get_args(InvoiceStatus) == _EXPECTED_STATUSES


def test_invoice_kind_literal_tuple_is_pinned_verbatim() -> None:
    assert typing.get_args(InvoiceKind) == _EXPECTED_KINDS


def test_the_literals_match_the_db_enums_in_0043() -> None:
    # The wire Literal and the DB enum are two declarations of the same vocabulary;
    # a drift means Postgres rejects a value the API happily validated.
    assert _sql_enum("invoice_status") == _EXPECTED_STATUSES
    assert _sql_enum("invoice_kind") == _EXPECTED_KINDS
    assert frozenset(_EXPECTED_STATUSES) == _STATUSES
    assert frozenset(_EXPECTED_KINDS) == _KINDS


def test_invoice_create_kind_accepts_only_the_two_labels() -> None:
    assert InvoiceCreate.model_validate({"clientId": "c", "kind": "one_off"}).kind == "one_off"
    with pytest.raises(ValueError, match="kind"):
        InvoiceCreate.model_validate({"clientId": "c", "kind": "subscription"})


def test_invoice_create_defaults_to_a_retainer() -> None:
    # The common case is the recurring monthly bill.
    assert InvoiceCreate.model_validate({"clientId": "c"}).kind == "retainer"
    assert InvoiceCreate.model_validate({"clientId": "c"}).currency == "USD"


# --------------------------------------------------------------------------- #
# 4. from_row coercion: Decimal/None/date off psycopg.
# --------------------------------------------------------------------------- #
def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-00000000beef",
        "number": "INV-0001",
        "client_id": "cl-secret",
        "client_name": "Meridian Wealth",
        "status": "paid",
        "kind": "retainer",
        "currency": "USD",
        "issue_date": date(2026, 7, 27),
        "due_date": date(2026, 8, 27),
        "period_start": date(2026, 7, 1),
        "period_end": date(2026, 7, 31),
        "subtotal": Decimal("1400.00"),
        "tax": Decimal("90.00"),
        "total": Decimal("1490.00"),
        "notes": "July retainer",
        "paid_at": datetime(2026, 8, 20, 9, 14, tzinfo=UTC),
        "paid_method": "bank transfer",
    }
    row.update(over)
    return row


def test_invoice_from_row_coerces_decimals_to_floats_and_dates_to_iso() -> None:
    built = InvoiceResponse.from_row(_row())
    assert built.number == "INV-0001"
    assert built.client == "Meridian Wealth"  # the snapshot, never the id
    assert built.amount == 1490.0 and isinstance(built.amount, float)
    assert built.subtotal == 1400.0 and built.tax == 90.0
    assert built.due == "2026-08-27"  # ISO, not "Aug 27" - humanising is the adapter's job
    assert built.issued == "2026-07-27"
    assert built.paid_at == "2026-08-20T09:14:00+00:00"


def test_invoice_from_row_never_carries_the_client_id_through() -> None:
    dumped = InvoiceResponse.from_row(_row()).model_dump_json(by_alias=True)
    assert "cl-secret" not in dumped  # not the key NOR the value
    assert "client_id" not in dumped and "clientId" not in dumped


def test_unset_dates_become_empty_strings_not_none() -> None:
    # A draft has no issue/due/paid date yet; the wire stays a string everywhere.
    built = InvoiceResponse.from_row(
        _row(issue_date=None, due_date=None, period_start=None, period_end=None, paid_at=None)
    )
    assert built.issued == "" and built.due == ""
    assert built.period_start == "" and built.period_end == "" and built.paid_at == ""


def test_an_off_enum_status_or_kind_degrades_to_empty_rather_than_leaking() -> None:
    # Mirrors the keyword module: an unknown DB label is never echoed as if it were a
    # valid one.
    built = InvoiceResponse.from_row(_row(status="chargeback", kind="crypto"))
    assert built.status == "" and built.kind == ""


def test_detail_from_rows_attaches_the_line_items() -> None:
    detail = InvoiceDetailResponse.from_rows(
        _row(),
        [{
            "id": "li-1", "description": "Growth retainer", "quantity": Decimal("1.00"),
            "unit_amount": Decimal("1400.00"), "line_total": Decimal("1400.00"),
            "sort_order": 0,
        }],
    )
    assert detail.number == "INV-0001" and detail.amount == 1490.0
    assert len(detail.lines) == 1
    assert detail.lines[0].line_total == 1400.0
    assert detail.lines[0].unit_amount == 1400.0


def test_detail_with_no_lines_is_a_legitimate_empty_draft() -> None:
    detail = InvoiceDetailResponse.from_rows(_row(subtotal=0, total=0), [])
    assert detail.lines == [] and detail.amount == 0.0


def test_revenue_from_row_rounds_the_collected_decimal() -> None:
    built = RevenuePeriodResponse.from_row(
        {"period": "2026-07", "invoices": 4, "collected": Decimal("5960.00")}
    )
    assert built.period == "2026-07" and built.invoices == 4
    assert built.collected == 5960.0


def test_billing_stats_mrr_is_an_integer_like_clients_mrr() -> None:
    # clients.mrr is an `integer` column (0003); the tile must not invent precision.
    stats = BillingStats(mrr=28_400, open_invoices=3, past_due=1)
    assert stats.mrr == 28_400 and isinstance(stats.mrr, int)
    assert BillingStats.model_fields["mrr"].annotation is int


def test_status_update_records_a_free_text_method_not_a_gateway_enum() -> None:
    # There is no payment provider in v1 - paid_method is what a human typed.
    body = InvoiceStatusUpdate.model_validate({"paidMethod": "cheque #4021"})
    assert body.paid_method == "cheque #4021"
    assert body.paid_at is None  # defaults to now server-side
    assert InvoiceStatusUpdate.model_fields["paid_method"].annotation is str


def test_line_create_rejects_negative_money() -> None:
    # A negative line would be a credit note - a different document, not an invoice.
    with pytest.raises(ValueError, match=r"greater than or equal"):
        InvoiceLineCreate.model_validate({"unitAmount": -1})
    with pytest.raises(ValueError, match=r"greater than or equal"):
        InvoiceLineCreate.model_validate({"quantity": -1})


def test_invoice_create_rejects_negative_tax() -> None:
    with pytest.raises(ValueError, match=r"greater than or equal"):
        InvoiceCreate.model_validate({"clientId": "c", "tax": -5})
