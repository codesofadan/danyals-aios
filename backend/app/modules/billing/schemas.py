"""Billing request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors the invoice models, so these shapes are owned
here (unlike the contract-locked Part-2/7 responses). The module's own unit tests
freeze the emitted key set + the ``invoice_status`` / ``invoice_kind`` enum tuples,
so a drift is still caught - this is the server-authoritative equivalent of the
contract lock.

Three rules are load-bearing in this file:

1. **The server owns every total.** ``InvoiceCreate`` / ``InvoiceUpdate`` /
   ``InvoiceLineCreate`` carry NO ``total`` / ``subtotal`` / ``line_total`` field at
   all - not "ignored", ABSENT. A caller cannot even express a total, so the only
   number that can reach the ledger is the one the service computed. A unit test
   pins the absence.
2. **``number`` is the id.** ``INV-####`` is what every route addresses and what a
   human quotes on a bank transfer; the internal uuid never appears on the wire.
3. **``client_id`` NEVER leaks.** ``client`` is the snapshotted display name.

Money crosses the wire as a real number (``float``), never a display string -
``$1,490`` / ``$28.4k`` formatting lives ONLY in the tool-workspace adapter
(``service.build_workspace``). Dates cross as ISO ``YYYY-MM-DD`` strings (``""``
when unset), likewise not humanised here.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The invoice lifecycle. Pinned verbatim against the ``public.invoice_status`` DB
# enum + the ``0043`` guard trigger (a module unit test asserts the tuple).
InvoiceStatus = Literal["draft", "open", "paid", "past_due", "void", "refunded"]
# retainer = the recurring subscription bill; one_off = a project/extra.
InvoiceKind = Literal["retainer", "one_off"]

_STATUSES: frozenset[str] = frozenset(
    {"draft", "open", "paid", "past_due", "void", "refunded"}
)
_KINDS: frozenset[str] = frozenset({"retainer", "one_off"})


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``.

    The wire edge is the ONLY place a money value becomes a float: the service
    computes in ``Decimal`` and the DB stores ``numeric(12,2)``, so no arithmetic
    ever happens on the lossy type.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso(value: Any) -> str:
    """A date/datetime column as an ISO string (``""`` when unset).

    Deliberately NOT humanised ("Aug 27" belongs to the workspace adapter): a
    consumer needs the real date to sort/filter on.
    """
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


class InvoiceLineItemResponse(BaseModel):
    """One billed line. ``line_total`` is SERVER-COMPUTED (= quantity x unit_amount)
    and is echoed back so the caller can see what the server actually recorded."""

    id: str
    description: str
    quantity: float
    unit_amount: float = Field(serialization_alias="unitAmount")
    line_total: float = Field(serialization_alias="lineTotal")
    sort_order: int = Field(serialization_alias="sortOrder")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> InvoiceLineItemResponse:
        return cls(
            id=str(row.get("id", "")),
            description=str(row.get("description", "") or ""),
            quantity=_f(row.get("quantity")),
            unit_amount=_f(row.get("unit_amount")),
            line_total=_f(row.get("line_total")),
            sort_order=int(row.get("sort_order", 0) or 0),
        )


class InvoiceResponse(BaseModel):
    """One invoice header. ``number`` is the id; ``client`` is the snapshotted display
    name (the internal ``client_id`` never leaks); ``amount`` is the SERVER-COMPUTED
    total (= subtotal + tax). Dates are ISO strings, ``""`` when unset."""

    number: str
    client: str
    amount: float
    subtotal: float
    tax: float
    currency: str
    status: str
    kind: str
    issued: str
    due: str
    period_start: str = Field(serialization_alias="periodStart")
    period_end: str = Field(serialization_alias="periodEnd")
    notes: str
    paid_at: str = Field(serialization_alias="paidAt")
    paid_method: str = Field(serialization_alias="paidMethod")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> InvoiceResponse:
        status = row.get("status")
        kind = row.get("kind")
        return cls(
            number=str(row.get("number", "")),
            client=str(row.get("client_name", "") or ""),
            amount=_f(row.get("total")),
            subtotal=_f(row.get("subtotal")),
            tax=_f(row.get("tax")),
            currency=str(row.get("currency", "USD") or "USD"),
            status=status if status in _STATUSES else "",
            kind=kind if kind in _KINDS else "",
            issued=_iso(row.get("issue_date")),
            due=_iso(row.get("due_date")),
            period_start=_iso(row.get("period_start")),
            period_end=_iso(row.get("period_end")),
            notes=str(row.get("notes", "") or ""),
            paid_at=_iso(row.get("paid_at")),
            paid_method=str(row.get("paid_method", "") or ""),
        )


class InvoiceDetailResponse(InvoiceResponse):
    """An invoice with its line items - the header shape PLUS ``lines``.

    Subclassing (rather than nesting under an ``invoice`` key) keeps the detail and
    the list rows the same shape, so a consumer reads ``number``/``amount``/``status``
    identically from either.
    """

    lines: list[InvoiceLineItemResponse]

    @classmethod
    def from_rows(
        cls, row: dict[str, Any], lines: list[dict[str, Any]]
    ) -> InvoiceDetailResponse:
        header = InvoiceResponse.from_row(row)
        return cls(
            **header.model_dump(),
            lines=[InvoiceLineItemResponse.from_row(line) for line in lines],
        )


class BillingStats(BaseModel):
    """The billing summary tiles.

    ``mrr`` is SUBSCRIPTION-derived - ``sum(clients.mrr)`` over ACTIVE subscriptions -
    and is NOT ``sum(invoices)``. The other two ARE ledger counts. See the module
    docstring in ``router.py``: this split is the whole point of the module.
    """

    mrr: int
    open_invoices: int = Field(serialization_alias="openInvoices")
    past_due: int = Field(serialization_alias="pastDue")


class RevenuePeriodResponse(BaseModel):
    """One period of COLLECTED revenue (paid invoices only) - explicitly NOT MRR.

    ``period`` is ``YYYY-MM``. Collected revenue is backward-looking cash that
    actually arrived; MRR is a forward-looking run-rate off the subscription table.
    They are different numbers and will not agree - by design.
    """

    period: str
    invoices: int
    collected: float

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RevenuePeriodResponse:
        return cls(
            period=str(row.get("period", "") or ""),
            invoices=int(row.get("invoices", 0) or 0),
            collected=round(_f(row.get("collected")), 2),
        )


# --- Request models -----------------------------------------------------------


class InvoiceLineCreate(BaseModel):
    """One line on an invoice draft.

    NOTE the absence of ``line_total``: it is ``quantity * unit_amount``, computed by
    the service. A caller cannot supply it, so a line can never bill an amount its
    own quantity/rate do not justify.
    """

    model_config = ConfigDict(populate_by_name=True)

    description: str = Field(default="", max_length=500)
    quantity: float = Field(default=1, ge=0)
    unit_amount: float = Field(default=0, ge=0, alias="unitAmount")
    sort_order: int = Field(default=0, ge=0, alias="sortOrder")


class InvoiceCreate(BaseModel):
    """POST /billing/invoices body: open a DRAFT invoice (+ optional initial lines).

    NOTE the absence of ``total`` / ``subtotal``: both are computed from ``lines`` +
    ``tax`` server-side. ``status`` is absent too - a new invoice is always a draft
    and reaches ``open`` only through /finalize. The internal ``client_id`` is
    server-resolved to a display snapshot (404 if the client is unknown/invisible).
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId", min_length=1)
    kind: InvoiceKind = "retainer"
    currency: str = Field(default="USD", min_length=1, max_length=8)
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    period_start: date | None = Field(default=None, alias="periodStart")
    period_end: date | None = Field(default=None, alias="periodEnd")
    tax: float = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=2000)
    lines: list[InvoiceLineCreate] = Field(default_factory=list, max_length=200)


class InvoiceUpdate(BaseModel):
    """PATCH /billing/invoices/{number} body: edit a DRAFT (409 on anything else).

    Every field is optional; only the provided ones change. ``total``/``subtotal`` are
    absent (server-computed) and so are ``status`` (moved only by the lifecycle routes)
    and ``client_id`` (an issued invoice's payer is fixed at creation - re-billing
    someone else means a new invoice, not an edit).
    """

    model_config = ConfigDict(populate_by_name=True)

    kind: InvoiceKind | None = None
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    period_start: date | None = Field(default=None, alias="periodStart")
    period_end: date | None = Field(default=None, alias="periodEnd")
    tax: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class InvoiceStatusUpdate(BaseModel):
    """POST /billing/invoices/{number}/mark-paid body: how the money arrived.

    ``paid_method`` is FREE TEXT ("bank transfer", "cheque", "stripe link") - there is
    no payment provider in v1, so this records an operator's statement, it does not
    reconcile anything. ``paid_at`` defaults to now server-side; it is settable so a
    payment noticed on Monday can be recorded against the Friday it landed.
    """

    model_config = ConfigDict(populate_by_name=True)

    paid_method: str = Field(default="", max_length=120, alias="paidMethod")
    paid_at: datetime | None = Field(default=None, alias="paidAt")
