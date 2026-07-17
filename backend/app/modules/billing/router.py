"""Billing module endpoints (Part 8 Phase 2H): the staff-only INVOICE ledger.

RECORDS ONLY - THERE IS NO PAYMENT GATEWAY IN v1. Nothing here charges a card, dunns
a customer, or reconciles a provider webhook. Every status transition is a MANUAL
operator action recorded after the fact (the sole exception is the nightly
``mark_past_due`` sweep, which only flips an already-issued ``open`` invoice whose due
date has passed). ``paid_method`` is free text - it records how a human says the money
arrived, it is not a gateway enum. Do not add charging, dunning or reconciliation to
this module.

THE LOAD-BEARING SCOPE RULE - MRR IS SUBSCRIPTION-DERIVED, NEVER INVOICE-DERIVED:

    The ``MRR`` KPI is ``sum(clients.mrr)`` over ACTIVE subscriptions (``0003``
    already owns the subscription truth: ``mrr`` / ``tier`` / ``status`` /
    ``renews_at``). It is **NOT** ``sum(invoices)``. Deriving MRR from the ledger
    would DOUBLE-COUNT one-off invoices - a project bill is not recurring revenue -
    and MISS every un-invoiced month of an active retainer. This module does not
    duplicate the subscription columns; it answers a different question.

    ``Open invoices`` / ``Past due`` DO come from the ledger. ``GET /billing/revenue``
    is COLLECTED cash (paid invoices bucketed by ``paid_at``) - a third, backward-
    looking number that is likewise NOT MRR and will not agree with it.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /billing/workspace`` adapter emits the ``lib/tools.ts`` ``billing`` EXTRA shape
(KPIs + the invoice table + the CTA), with table columns pinned to
``tests/test_tool_workspace_contract.py``.

Tables owned: ``invoices`` / ``invoice_line_items`` (migration ``0043_billing``).
Cost-gate dial: NONE - this module makes no paid external call (there is no provider
to call), so there is nothing to gate.

Access: every route requires the ``billing`` FEATURE grant. Reads add ``view_reports``;
every MUTATION requires the OWNER/ADMIN role. That deliberately differs from the usual
owner/admin/manager LEADS set the other modules write with: billing is finance-
sensitive, and a delivery manager may run the work without being able to issue or
settle money. It mirrors the ``0043`` RLS insert/update/delete policies
(``current_app_role() in ('owner','admin')``) byte-for-byte - a caller who passed the
app gate but failed RLS would get an opaque database error instead of a clean 403.

The invoice is addressed by its PUBLIC ``number`` (INV-####), never its uuid, and the
internal ``client_id`` never leaks (``client`` is the snapshotted name). Every mutation
offloads the blocking psycopg call with ``asyncio.to_thread`` and records an activity
entry (kind=client, entity=client) so the money movement keeps each client's context
fresh.

The lifecycle is enforced TWICE, deliberately: ``0043``'s ``invoices_guard_update``
trigger is the real boundary (staff hold DB-reachable credentials), and these routes
fail fast with a 409 so the API answers cleanly instead of surfacing a Postgres
exception. Editing an issued invoice is impossible by design - void it and issue a new
one; that is what makes the ledger auditable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_feature, require_perm, require_role
from app.core.pagination import PageDep
from app.modules.billing.repo import BillingRepo, BillingRepoDep
from app.modules.billing.schemas import (
    BillingStats,
    InvoiceCreate,
    InvoiceDetailResponse,
    InvoiceKind,
    InvoiceLineCreate,
    InvoiceResponse,
    InvoiceStatus,
    InvoiceStatusUpdate,
    InvoiceUpdate,
    RevenuePeriodResponse,
)
from app.modules.billing.service import (
    build_workspace,
    can_transition,
    compute_line_total,
    is_draft,
    totals_for_lines,
)
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

router = APIRouter(tags=["billing"])

# Every route requires the fine-grained billing feature grant (owner is all-on).
# Reads additionally require view_reports; EVERY mutation requires owner/admin -
# mirroring the 0043 RLS write policies exactly (see the module docstring: a manager
# is deliberately NOT enough for finance).
Feature = Annotated[CurrentUser, Depends(require_feature("billing"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
Finance = Annotated[CurrentUser, Depends(require_role("owner", "admin"))]

_INVOICE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
)
_LINE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Invoice line not found"
)
_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
_NOTHING_TO_UPDATE = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
)
_CHANGED_CONCURRENTLY = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Invoice changed concurrently"
)


def _not_draft(current: str) -> HTTPException:
    """409: an issued invoice is frozen - amounts/dates/lines are immutable."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Invoice is {current}, not a draft - issued invoices cannot be edited",
    )


def _illegal_transition(current: str, target: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Illegal invoice transition: {current} -> {target}",
    )


async def _load(repo: BillingRepo, number: str) -> dict[str, Any]:
    """The invoice, or a 404 (unknown and RLS-invisible are indistinguishable)."""
    row = await asyncio.to_thread(repo.get_by_number, number)
    if row is None:
        raise _INVOICE_NOT_FOUND
    return row


async def _detail(repo: BillingRepo, row: dict[str, Any]) -> InvoiceDetailResponse:
    lines = await asyncio.to_thread(repo.lines_for, str(row["id"]))
    return InvoiceDetailResponse.from_rows(row, lines)


async def _recompute(repo: BillingRepo, row: dict[str, Any]) -> dict[str, Any]:
    """Re-derive subtotal/total from the invoice's CURRENT lines and persist them.

    Called after EVERY line mutation. The totals are never carried forward from the
    request - they are recomputed from what is actually in the ledger, so a line
    added/removed and a total can never disagree.
    """
    lines = await asyncio.to_thread(repo.lines_for, str(row["id"]))
    totals = totals_for_lines(lines, row.get("tax", 0))
    updated = await asyncio.to_thread(
        repo.set_totals, str(row["number"]),
        subtotal=totals.subtotal, tax=totals.tax, total=totals.total,
    )
    if updated is None:
        raise _CHANGED_CONCURRENTLY
    return updated


async def _record(actor: CurrentUser, row: dict[str, Any], action: str) -> None:
    """One activity entry against the CLIENT the invoice bills (kind=client)."""
    await record_activity(
        actor, kind="client", action=action,
        target=str(row.get("client_name", "") or ""),
        entity_type="client", entity_id=str(row["client_id"]),
    )


async def _transition(
    repo: BillingRepo, actor: CurrentUser, number: str, target: str,
    *, extra: dict[str, Any] | None = None, action: str,
) -> InvoiceResponse:
    """The shared lifecycle move: load -> vet the transition -> guarded update -> log.

    The app-side check (``can_transition``) fires BEFORE the DB trigger has to, so an
    illegal move is a clean 409 rather than a Postgres exception; the guarded update
    (``where status = <the status we just read>``) then closes the race between the
    two.
    """
    row = await _load(repo, number)
    current = str(row.get("status", ""))
    if not can_transition(current, target):
        raise _illegal_transition(current, target)
    changes: dict[str, Any] = {"status": target, **(extra or {})}
    updated = await asyncio.to_thread(repo.update_invoice, number, changes, current)
    if updated is None:
        raise _CHANGED_CONCURRENTLY
    await _record(actor, updated, action)
    return InvoiceResponse.from_row(updated)


# --- reads --------------------------------------------------------------------


@router.get("/billing/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    repo: BillingRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    invoice_status: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    kind: Annotated[InvoiceKind | None, Query()] = None,
) -> list[InvoiceResponse]:
    """The invoice ledger (newest issued first). Filters narrow it by client, status
    or kind. ``client_id`` never leaks - each row carries the client's display name."""
    rows = await asyncio.to_thread(
        repo.list_invoices,
        client_id=client_id, status=invoice_status, kind=kind,
        limit=page.limit, offset=page.offset,
    )
    return [InvoiceResponse.from_row(r) for r in rows]


@router.get("/billing/stats", response_model=BillingStats)
async def billing_stats(repo: BillingRepoDep, _feat: Feature, _user: ViewReports) -> BillingStats:
    """The billing tiles. ``mrr`` is ``sum(clients.mrr)`` over ACTIVE subscriptions -
    NOT ``sum(invoices)`` (see the module docstring); ``open_invoices`` / ``past_due``
    ARE ledger counts. Two reads over two tables, on purpose."""
    mrr = await asyncio.to_thread(repo.subscription_mrr)
    counts = await asyncio.to_thread(repo.invoice_counts)
    return BillingStats(
        mrr=mrr,
        open_invoices=counts["open_invoices"],
        past_due=counts["past_due"],
    )


@router.get("/billing/workspace", response_model=ToolExtraResponse)
async def billing_workspace(
    repo: BillingRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``billing`` shape): KPI tiles, the invoice
    table (cols ``Client|Amount|Due|Status``), and the CTA. The MRR tile reads the
    SUBSCRIPTION table; the table + the other two tiles read the ledger."""
    mrr = await asyncio.to_thread(repo.subscription_mrr)
    counts = await asyncio.to_thread(repo.invoice_counts)
    invoices = await asyncio.to_thread(repo.list_invoices, limit=8, offset=0)
    stats = BillingStats(
        mrr=mrr, open_invoices=counts["open_invoices"], past_due=counts["past_due"]
    )
    return build_workspace(stats, invoices)


@router.get("/billing/revenue", response_model=list[RevenuePeriodResponse])
async def revenue(
    repo: BillingRepoDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    months: Annotated[int, Query(ge=1, le=60)] = 12,
) -> list[RevenuePeriodResponse]:
    """COLLECTED revenue by month: PAID invoices bucketed by ``paid_at``, newest first.

    This is NOT MRR and is not expected to match it. MRR is a forward-looking run-rate
    off ``clients.mrr``; this is backward-looking cash that actually arrived. A
    refunded invoice is excluded (the money went back); an issued-but-unpaid one has
    not arrived yet.
    """
    rows = await asyncio.to_thread(repo.revenue_by_period, client_id=client_id, limit=months)
    return [RevenuePeriodResponse.from_row(r) for r in rows]


@router.get("/billing/invoices/{number}", response_model=InvoiceDetailResponse)
async def get_invoice(
    number: str, repo: BillingRepoDep, _feat: Feature, _user: ViewReports
) -> InvoiceDetailResponse:
    """One invoice by its public number (INV-####): the header + its line items."""
    row = await _load(repo, number)
    return await _detail(repo, row)


# --- mutations (owner/admin only) ---------------------------------------------


@router.post(
    "/billing/invoices",
    response_model=InvoiceDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    body: InvoiceCreate, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceDetailResponse:
    """Open a DRAFT invoice (+ optional initial lines). Owner/admin only.

    The client name is snapshotted server-side (404 if the client is unknown or
    invisible); ``number`` is assigned by the DB sequence (INV-####). Every total is
    computed here from the lines + tax - the request has no total field to trust. A
    new invoice is ALWAYS a draft; it reaches ``open`` only through /finalize.
    """
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND

    row = await asyncio.to_thread(
        repo.create_invoice,
        {
            "client_id": body.client_id,
            "client_name": client_name,
            "status": "draft",
            "kind": body.kind,
            "currency": body.currency,
            "issue_date": body.issue_date,
            "due_date": body.due_date,
            "period_start": body.period_start,
            "period_end": body.period_end,
            "tax": body.tax,
            "notes": body.notes,
            "created_by": actor.id,
        },
    )
    if row is None:  # pragma: no cover - RLS would have raised, not returned empty
        raise _CHANGED_CONCURRENTLY

    if body.lines:
        await asyncio.to_thread(
            repo.add_lines, str(row["id"]),
            [
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_amount": line.unit_amount,
                    "line_total": compute_line_total(line.quantity, line.unit_amount),
                    "sort_order": line.sort_order,
                }
                for line in body.lines
            ],
        )
    row = await _recompute(repo, row)
    await _record(actor, row, f"drafted invoice {row['number']}")
    return await _detail(repo, row)


@router.patch("/billing/invoices/{number}", response_model=InvoiceDetailResponse)
async def patch_invoice(
    number: str, body: InvoiceUpdate, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceDetailResponse:
    """Edit a DRAFT invoice's dates / kind / currency / tax / notes. Owner/admin only.

    409 on anything that is not a draft: an issued invoice is a document a client has
    seen, so it is frozen (``0043`` enforces the same freeze at the DB). Changing
    ``tax`` re-derives the total from the current lines. 400 if nothing was provided.
    """
    row = await _load(repo, number)
    current = str(row.get("status", ""))
    if not is_draft(current):
        raise _not_draft(current)

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise _NOTHING_TO_UPDATE

    updated = await asyncio.to_thread(repo.update_invoice, number, changes, "draft")
    if updated is None:
        raise _CHANGED_CONCURRENTLY
    if "tax" in changes:
        updated = await _recompute(repo, updated)
    await _record(actor, updated, f"updated draft invoice {number}")
    return await _detail(repo, updated)


@router.post(
    "/billing/invoices/{number}/lines",
    response_model=InvoiceDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_line(
    number: str, body: InvoiceLineCreate, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceDetailResponse:
    """Add ONE line to a DRAFT invoice, then recompute the totals. Owner/admin only.

    ``line_total`` is computed here (quantity x unit_amount) - the request cannot
    supply one. 409 if the invoice has been issued.
    """
    row = await _load(repo, number)
    current = str(row.get("status", ""))
    if not is_draft(current):
        raise _not_draft(current)

    await asyncio.to_thread(
        repo.add_lines, str(row["id"]),
        [{
            "description": body.description,
            "quantity": body.quantity,
            "unit_amount": body.unit_amount,
            "line_total": compute_line_total(body.quantity, body.unit_amount),
            "sort_order": body.sort_order,
        }],
    )
    updated = await _recompute(repo, row)
    await _record(actor, updated, f"added a line to invoice {number}")
    return await _detail(repo, updated)


@router.delete("/billing/invoices/{number}/lines/{line_id}", response_model=InvoiceDetailResponse)
async def delete_line(
    number: str, line_id: str, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceDetailResponse:
    """Remove ONE line from a DRAFT invoice, then recompute the totals. Owner/admin
    only. 409 if the invoice has been issued; 404 if the line is not on it.

    Returns the refreshed detail rather than a bare 204 precisely BECAUSE the totals
    moved - the caller must not have to guess the new amount.
    """
    row = await _load(repo, number)
    current = str(row.get("status", ""))
    if not is_draft(current):
        raise _not_draft(current)

    deleted = await asyncio.to_thread(repo.delete_line, str(row["id"]), line_id)
    if not deleted:
        raise _LINE_NOT_FOUND
    updated = await _recompute(repo, row)
    await _record(actor, updated, f"removed a line from invoice {number}")
    return await _detail(repo, updated)


@router.post("/billing/invoices/{number}/finalize", response_model=InvoiceResponse)
async def finalize_invoice(
    number: str, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceResponse:
    """Issue a draft: ``draft -> open``. Owner/admin only.

    This is the point of no return - from here the amounts, dates and payer are frozen
    (``0043``'s trigger). A mistake is corrected by voiding and re-issuing, never by
    editing. 409 from any other status.
    """
    return await _transition(
        repo, actor, number, "open", action=f"issued invoice {number}"
    )


@router.post("/billing/invoices/{number}/mark-paid", response_model=InvoiceResponse)
async def mark_paid(
    number: str, body: InvoiceStatusUpdate, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceResponse:
    """Record that an ``open``/``past_due`` invoice was PAID. Owner/admin only.

    A MANUAL operator statement - there is no gateway to confirm it against.
    ``paid_at`` defaults to now; ``paid_method`` is free text. 409 from any other
    status (a draft must be issued first; a void/refunded one is terminal).
    """
    return await _transition(
        repo, actor, number, "paid",
        extra={
            "paid_at": body.paid_at or datetime.now(UTC),
            "paid_method": body.paid_method,
        },
        action=f"marked invoice {number} paid",
    )


@router.post("/billing/invoices/{number}/void", response_model=InvoiceResponse)
async def void_invoice(
    number: str, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceResponse:
    """Void an invoice (``draft``/``open``/``past_due`` -> ``void``). Owner/admin only.

    TERMINAL: a voided invoice can never be revived - re-issue a new one. This is how
    an issued invoice is corrected, since editing it is impossible by design. 409 from
    ``paid`` (settled money is refunded, not voided) or from a terminal status.
    """
    return await _transition(
        repo, actor, number, "void", action=f"voided invoice {number}"
    )


@router.post("/billing/invoices/{number}/refund", response_model=InvoiceResponse)
async def refund_invoice(
    number: str, repo: BillingRepoDep, _feat: Feature, actor: Finance
) -> InvoiceResponse:
    """Record a refund of a PAID invoice (``paid -> refunded``). Owner/admin only.

    Records only: no money moves from here - an operator refunds through their bank
    and records it. TERMINAL. The refunded invoice drops out of COLLECTED revenue
    (``GET /billing/revenue`` counts ``paid`` only). 409 from any other status.
    """
    return await _transition(
        repo, actor, number, "refunded", action=f"refunded invoice {number}"
    )
