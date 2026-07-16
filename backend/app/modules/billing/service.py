"""Billing orchestration - the PURE money core + the tool-workspace adapter.

This module is DB-free and network-free (mirrors ``keyword_research.service``'s pure
core): it owns the three rules that make the ledger trustworthy, all of them
deterministic given the same inputs.

1. **Every total is computed here, never accepted.** ``line_total = quantity x
   unit_amount``; ``subtotal = sum(line_total)``; ``total = subtotal + tax``. The
   request models carry no total field at all, so there is nothing to ignore - but
   :func:`compute_totals` is also the ONLY place any of the three is produced, so a
   caller cannot smuggle one past a code path that forgot to recompute.

   Money is ``Decimal``, quantized to 2dp with ROUND_HALF_UP - never float. 0.1 + 0.2
   is a rounding curiosity in a chart and a wrong invoice in a ledger.

2. **The state machine mirrors the DB.** :data:`LEGAL_TRANSITIONS` is the app-side
   twin of the ``invoices_guard_update`` trigger in ``0043_billing.sql``. The trigger
   is the real boundary (staff hold DB-reachable credentials); this exists so the
   router can fail fast with a clean 409 instead of letting Postgres answer with an
   opaque exception. The two MUST agree - a module test pins the table against the
   migration text.

3. **MRR is subscription-derived, never invoice-derived.** Nothing in this file
   derives MRR from an invoice; :func:`build_workspace` takes it pre-read off
   ``clients.mrr`` (see ``repo.subscription_mrr``). See ``router.py``'s docstring.

``build_workspace`` is the ``GET /billing/workspace`` adapter: it emits the frontend
``lib/tools.ts`` ``billing`` EXTRA shape with table columns pinned EXACTLY to
``["Client", "Amount", "Due", "Status"]`` (the tool-workspace contract test asserts
this byte-for-byte). The money/date DISPLAY strings (``$28.4k``, ``$1,490``,
``Aug 27``) exist ONLY in this adapter - the domain models carry real numerics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, cast

from app.modules.billing.schemas import BillingStats
from app.schemas.tool_workspace import (
    ToolCell,
    ToolCellObj,
    ToolExtraResponse,
    ToolKpi,
    ToolPrimary,
    ToolTable,
)

# The money quantum: numeric(12,2) in the DB, so 2dp everywhere above it too.
_CENTS = Decimal("0.01")

# --- The legal invoice state machine (the app-side twin of 0043's guard) -------
# Kept as data rather than branches so the router, the tests and the migration
# assertion all read the SAME table. `void` / `refunded` map to the empty set: they
# are TERMINAL, and an empty frozenset makes every exit illegal by construction
# rather than by a forgotten `elif`.
#
# ONE DELIBERATE DIVERGENCE FROM THE DB GUARD - the diagonal. No status lists itself
# as a target, so `can_transition(X, X)` is False and re-finalizing an already-open
# invoice is a clean 409. The 0043 trigger, by contrast, lets a no-op
# `set status = <same status>` through, because it only vets a status that actually
# MOVES - which is exactly what lets an ordinary draft edit (a PATCH that never
# mentions status) reach the freeze check. Both are right; they answer different
# questions. Verified against a live database: the two agree on all 8 real edges and
# reject all 22 illegal ones identically, differing only here.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"open", "void"}),
    "open": frozenset({"paid", "past_due", "void"}),
    "past_due": frozenset({"paid", "void"}),
    "paid": frozenset({"refunded"}),
    "void": frozenset(),
    "refunded": frozenset(),
}

# The one status in which an invoice is still a working document: amounts, dates and
# lines are editable ONLY here. Outside it the 0043 trigger freezes the row.
DRAFT_STATUS = "draft"

# --- tool-workspace contract constants (pinned to lib/tools.ts billing) -------
WORKSPACE_TABLE_COLS: list[str] = ["Client", "Amount", "Due", "Status"]
_WORKSPACE_TABLE_TITLE = "Invoices"
_WORKSPACE_TABLE_ICON = "payments"
_WORKSPACE_PRIMARY = ToolPrimary(label="New invoice", icon="payments")
_WORKSPACE_BULLETS = [
    "View plans & invoices",
    "Track payments & renewals",
    "Manage payment settings",
]
_WORKSPACE_ROW_LIMIT = 8

# The display label + tone per status. ok=Paid / info=Open / crit=Past due /
# mut=Draft are pinned by lib/tools.ts; void reads as mut (a dead document) and
# refunded as warn (money that arrived and left again - not a failure, but not
# revenue either).
_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "draft": ("Draft", "mut"),
    "open": ("Open", "info"),
    "paid": ("Paid", "ok"),
    "past_due": ("Past due", "crit"),
    "void": ("Void", "mut"),
    "refunded": ("Refunded", "warn"),
}


@dataclass(frozen=True)
class InvoiceTotals:
    """The three server-computed money fields of an invoice, as exact decimals."""

    subtotal: Decimal
    tax: Decimal
    total: Decimal


def _money(value: Any) -> Decimal:
    """Coerce any inbound number to an exact 2dp ``Decimal``.

    Floats are routed through ``str`` so 1.1 becomes Decimal("1.1") rather than
    Decimal("1.100000000000000088817841970012523233890533447265625"). A junk value
    degrades to 0 rather than raising: the request models already bound the types,
    so this is a belt-and-braces floor, not the validation layer.
    """
    try:
        return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def compute_line_total(quantity: Any, unit_amount: Any) -> Decimal:
    """``quantity x unit_amount``, quantized to 2dp. The ONLY source of a line total.

    Multiplied at full precision and rounded once at the end - rounding the operands
    first would drift on a fractional quantity (e.g. 1.5 hours x $99.99).
    """
    product = Decimal(str(quantity or 0)) * Decimal(str(unit_amount or 0))
    return product.quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_totals(line_totals: list[Any], tax: Any) -> InvoiceTotals:
    """``subtotal = sum(line_totals)``; ``total = subtotal + tax``.

    Call this after EVERY line mutation. An invoice with no lines is a legitimate
    zero-subtotal draft (tax still applies to it, which keeps the arithmetic honest
    rather than special-casing empty).
    """
    subtotal = sum((_money(t) for t in line_totals), Decimal("0.00"))
    tax_amount = _money(tax)
    return InvoiceTotals(
        subtotal=subtotal.quantize(_CENTS, rounding=ROUND_HALF_UP),
        tax=tax_amount,
        total=(subtotal + tax_amount).quantize(_CENTS, rounding=ROUND_HALF_UP),
    )


def totals_for_lines(lines: list[dict[str, Any]], tax: Any) -> InvoiceTotals:
    """:func:`compute_totals` over raw line ROWS (each with a ``line_total``).

    The repo hands back rows straight from Postgres, so this is the shape the
    recompute-after-a-line-mutation path actually holds.
    """
    return compute_totals([line.get("line_total", 0) for line in lines], tax)


# --- The state machine --------------------------------------------------------


def can_transition(current: str, target: str) -> bool:
    """Whether ``current -> target`` is a legal invoice transition.

    An unknown ``current`` yields False (fail closed): a status this table has never
    heard of must not be advanced on a guess.
    """
    return target in LEGAL_TRANSITIONS.get(current, frozenset())


def is_terminal(status: str) -> bool:
    """Whether ``status`` admits NO further transition (``void`` / ``refunded``)."""
    return not LEGAL_TRANSITIONS.get(status, frozenset())


def is_draft(status: str) -> bool:
    """Whether the invoice is still editable (amounts / dates / lines)."""
    return status == DRAFT_STATUS


# --------------------------------------------------------------------------- #
# The /workspace adapter (frontend lib/tools.ts billing EXTRA shape).
# --------------------------------------------------------------------------- #
# Everything below is DISPLAY. It is the only place in the module where a money
# value becomes a string - the domain models and the DB carry real numerics.
def format_money(value: Any) -> str:
    """A money cell as ``lib/tools.ts`` renders it: ``$1,490`` (no cents when whole).

    Cents survive when present (``$1,490.50``) - dropping them would misstate a real
    invoice; a whole amount stays clean because that is what the design shows.
    """
    amount = _money(value)
    whole = amount == amount.to_integral_value()
    return f"${amount:,.0f}" if whole else f"${amount:,.2f}"


def format_compact_money(value: Any) -> str:
    """A KPI money tile as ``lib/tools.ts`` renders it: ``$28.4k`` / ``$1.2m``.

    Only the MRR tile uses this - a run-rate is read at a glance, so the design
    trades exactness for scannability. An invoice amount never goes through here.
    """
    amount = _money(value)
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}m"
    if abs(amount) >= 1_000:
        return f"${amount / 1_000:.1f}k"
    return format_money(amount)


def format_due(value: Any) -> str:
    """A due date as ``lib/tools.ts`` renders it: ``Aug 27`` (em-dash when unset).

    Deliberately year-less: the table shows near-term invoices where the year is
    noise. The real ISO date still ships on ``InvoiceResponse.due``.
    """
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime | date):
        return value.strftime("%b %d")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%b %d")
    except ValueError:
        return "—"


def status_cell(status: str) -> ToolCellObj:
    """The toned Status cell. An unknown status degrades to a muted echo rather than
    a KeyError - a workspace tile must never 500 over a label."""
    label, tone = _STATUS_DISPLAY.get(status, (status or "—", "mut"))
    return ToolCellObj(v=label, tone=cast("Any", tone))


def _invoice_row(row: dict[str, Any]) -> list[ToolCell]:
    """One workspace table row: [Client, Amount, Due, Status]."""
    return [
        str(row.get("client_name", "") or ""),
        format_money(row.get("total")),
        format_due(row.get("due_date")),
        status_cell(str(row.get("status") or "")),
    ]


def build_workspace(stats: BillingStats, invoices: list[dict[str, Any]]) -> ToolExtraResponse:
    """Assemble the billing tool workspace (KPIs + the invoice table + CTA).

    KPI labels + the primary + the table columns are pinned to ``lib/tools.ts``; the
    columns are EXACTLY ``["Client", "Amount", "Due", "Status"]`` (the tool-workspace
    contract test enforces byte-identity).

    The ``MRR`` tile is ``stats.mrr`` - read from ``sum(clients.mrr)``, NOT from this
    module's ledger. ``Open invoices`` / ``Past due`` ARE ledger counts. tools.ts
    shows deltas on two tiles; we emit none, because a delta needs a historical
    baseline the ledger does not keep and an invented one would be a lie on a
    finance screen.
    """
    kpis = [
        ToolKpi(label="MRR", value=format_compact_money(stats.mrr)),
        ToolKpi(label="Open invoices", value=str(stats.open_invoices)),
        ToolKpi(label="Past due", value=str(stats.past_due)),
    ]
    table = ToolTable(
        title=_WORKSPACE_TABLE_TITLE,
        icon=_WORKSPACE_TABLE_ICON,
        cols=list(WORKSPACE_TABLE_COLS),
        rows=[_invoice_row(r) for r in invoices[:_WORKSPACE_ROW_LIMIT]],
    )
    return ToolExtraResponse(
        kpis=kpis, table=table, primary=_WORKSPACE_PRIMARY, bullets=list(_WORKSPACE_BULLETS)
    )
