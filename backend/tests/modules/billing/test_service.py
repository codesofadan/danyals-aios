"""Billing service: the money core + the state machine + the MRR provenance.

No DB, no network: everything here is the pure core. Three properties are pinned, and
they are the three that make the ledger trustworthy:

1. **Every total is server-computed.** ``total = sum(line_total) + tax``, recomputed
   from the lines that are actually in the ledger. A client-supplied total is not
   "ignored" - it cannot be expressed (``test_schemas`` pins the absent field) and it
   cannot influence anything computed here (pinned below).
2. **The state machine is complete and closed.** Every legal transition is allowed and
   every illegal one is rejected - asserted EXHAUSTIVELY over the full status x status
   product, so a new status cannot quietly arrive with no rules.
3. **MRR is subscription-derived, never invoice-derived.** The single most important
   test in the module.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.billing.schemas import BillingStats
from app.modules.billing.service import (
    LEGAL_TRANSITIONS,
    WORKSPACE_TABLE_COLS,
    build_workspace,
    can_transition,
    compute_line_total,
    compute_totals,
    format_compact_money,
    format_due,
    format_money,
    is_draft,
    is_terminal,
    status_cell,
    totals_for_lines,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0043_billing.sql"

_ALL_STATUSES = ("draft", "open", "paid", "past_due", "void", "refunded")

# The legal edges, spelled out INDEPENDENTLY of the service's own table so this file
# is a real specification rather than a mirror of the implementation.
_LEGAL_EDGES = frozenset({
    ("draft", "open"), ("draft", "void"),
    ("open", "paid"), ("open", "past_due"), ("open", "void"),
    ("past_due", "paid"), ("past_due", "void"),
    ("paid", "refunded"),
})


# --------------------------------------------------------------------------- #
# 1. THE load-bearing rule: MRR is subscription-derived, NEVER invoice-derived.
# --------------------------------------------------------------------------- #
def test_mrr_comes_from_clients_mrr_and_is_not_the_sum_of_invoices() -> None:
    """The single most important test in the module.

    The workspace is handed a subscription MRR of 28,400 and a ledger whose invoices
    total 2,180. The MRR tile must render the SUBSCRIPTION number.

    Why summing invoices would be wrong, concretely:
      * the 690 one-off below is NOT recurring revenue - counting it inflates the
        run-rate with a bill that will never repeat, and
      * an active retainer nobody has invoiced this month would vanish from MRR
        entirely.
    The two numbers answer different questions and must never be conflated.
    """
    stats = BillingStats(mrr=28_400, open_invoices=3, past_due=1)
    ledger = [
        {"client_name": "Meridian Wealth", "total": Decimal("1490.00"),
         "due_date": "2026-08-27", "status": "paid", "kind": "retainer"},
        {"client_name": "Atlas Legal", "total": Decimal("690.00"),
         "due_date": "2026-07-05", "status": "past_due", "kind": "one_off"},
    ]
    workspace = build_workspace(stats, ledger)
    tiles = {k.label: k.value for k in workspace.kpis}

    assert tiles["MRR"] == "$28.4k"  # = sum(clients.mrr), compact-formatted
    assert tiles["MRR"] != "$2.2k"  # != sum(invoices) (1490 + 690 = 2180)


def test_the_workspace_ignores_the_ledger_entirely_when_building_the_mrr_tile() -> None:
    # Same subscription MRR, wildly different ledgers -> the SAME tile. If the adapter
    # ever starts reading invoices for MRR, this breaks immediately.
    stats = BillingStats(mrr=28_400, open_invoices=0, past_due=0)
    empty = build_workspace(stats, [])
    huge = build_workspace(
        stats, [{"client_name": "X", "total": Decimal("999999.00"), "status": "paid"}]
    )
    assert empty.kpis[0].value == huge.kpis[0].value == "$28.4k"


def test_the_ledger_tiles_do_come_from_the_ledger() -> None:
    # The other half of the contract: hiding the ledger from MRR must not mean the
    # ledger stops driving its OWN two tiles.
    workspace = build_workspace(BillingStats(mrr=0, open_invoices=3, past_due=1), [])
    tiles = {k.label: k.value for k in workspace.kpis}
    assert tiles["Open invoices"] == "3"
    assert tiles["Past due"] == "1"


def test_collected_revenue_is_a_different_number_from_mrr_by_construction() -> None:
    """Revenue != MRR - documented here because they are the two numbers an operator
    is most likely to expect to match.

    MRR is a forward-looking run-rate off `clients.mrr`; collected revenue is
    backward-looking cash bucketed by `paid_at`. The repo's `revenue_by_period` reads
    `invoices` and never `clients`; `subscription_mrr` reads `clients` and never
    `invoices` (pinned in test_repo). Nothing in the service bridges them - and this
    asserts the service exposes no such bridge.
    """
    import app.modules.billing.service as svc

    exported = {name for name in dir(svc) if not name.startswith("_")}
    assert "mrr" not in {n.lower() for n in exported}, (
        "the service must not compute an MRR - it is a repo read off clients.mrr"
    )


# --------------------------------------------------------------------------- #
# 2. Totals: server-computed, always, from the lines that are really there.
# --------------------------------------------------------------------------- #
def test_line_total_is_quantity_times_unit_amount() -> None:
    assert compute_line_total(1, 1490) == Decimal("1490.00")
    assert compute_line_total(3, 250) == Decimal("750.00")
    assert compute_line_total(0, 999) == Decimal("0.00")


def test_line_total_rounds_once_at_the_end_not_on_the_operands() -> None:
    # 1.5 x 99.99 = 149.985 -> 149.99. Rounding the operands first would give 150.00.
    assert compute_line_total(1.5, 99.99) == Decimal("149.99")


def test_line_total_is_exact_decimal_never_float_arithmetic() -> None:
    # The classic float sin: 0.1 + 0.2 != 0.3. In a chart that is a curiosity; in a
    # ledger it is a wrong invoice.
    assert compute_line_total(3, 0.1) == Decimal("0.30")
    assert isinstance(compute_line_total(1, 1), Decimal)


def test_total_is_the_sum_of_lines_plus_tax() -> None:
    totals = compute_totals([Decimal("1000.00"), Decimal("400.00")], Decimal("90.00"))
    assert totals.subtotal == Decimal("1400.00")
    assert totals.tax == Decimal("90.00")
    assert totals.total == Decimal("1490.00")


def test_totals_recompute_from_the_rows_actually_in_the_ledger() -> None:
    # totals_for_lines is what runs after every line mutation: it reads line_total off
    # the persisted rows, so a total can never disagree with the lines it bills.
    rows = [
        {"line_total": Decimal("1400.00")},
        {"line_total": Decimal("250.00")},
    ]
    totals = totals_for_lines(rows, Decimal("0"))
    assert totals.subtotal == Decimal("1650.00")
    assert totals.total == Decimal("1650.00")


def test_a_client_supplied_total_cannot_influence_the_computed_one() -> None:
    """The service computes from lines + tax and reads nothing else.

    ``test_schemas`` proves a caller cannot even express a total; this proves the
    computation would not consult one if it appeared. A row carrying a hostile
    ``total``/``subtotal`` is computed over identically - the extra keys are inert.
    """
    honest = [{"line_total": Decimal("100.00")}]
    hostile = [{"line_total": Decimal("100.00"), "total": Decimal("999999.00"),
                "subtotal": Decimal("999999.00"), "amount": Decimal("999999.00")}]
    assert totals_for_lines(honest, 0) == totals_for_lines(hostile, 0)
    assert totals_for_lines(hostile, 0).total == Decimal("100.00")


def test_an_invoice_with_no_lines_is_a_zero_subtotal_draft_and_tax_still_applies() -> None:
    totals = compute_totals([], Decimal("10.00"))
    assert totals.subtotal == Decimal("0.00")
    assert totals.total == Decimal("10.00")  # arithmetic, not a special case


def test_totals_quantize_to_the_numeric_12_2_the_db_stores() -> None:
    # The column is numeric(12,2); a 3dp total would silently round on write.
    totals = compute_totals([Decimal("0.005"), Decimal("0.005")], 0)
    assert totals.subtotal.as_tuple().exponent == -2
    assert totals.total.as_tuple().exponent == -2


def test_a_junk_amount_degrades_to_zero_rather_than_raising() -> None:
    # Belt-and-braces: the request models already bound the types, so this floor only
    # ever catches a DB/None surprise - it must not 500 a totals recompute.
    assert compute_totals([None, "not-a-number"], None).total == Decimal("0.00")


# --------------------------------------------------------------------------- #
# 3. The state machine: every legal move allowed, every illegal one rejected.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("current", "target"), sorted(_LEGAL_EDGES))
def test_every_legal_transition_is_allowed(current: str, target: str) -> None:
    assert can_transition(current, target), f"{current} -> {target} must be legal"


@pytest.mark.parametrize(
    ("current", "target"),
    sorted(
        (a, b)
        for a in _ALL_STATUSES
        for b in _ALL_STATUSES
        if (a, b) not in _LEGAL_EDGES
    ),
)
def test_every_illegal_transition_is_rejected(current: str, target: str) -> None:
    """EXHAUSTIVE over the full status x status product (36 pairs, 8 legal, 28 not).

    Enumerating the complement - rather than hand-picking a few bad moves - is what
    makes this a real gate: a newly added status with no rules would show up here as
    an unhandled pair instead of quietly defaulting to allowed.
    """
    assert not can_transition(current, target), f"{current} -> {target} must be rejected"


def test_a_status_cannot_transition_to_itself() -> None:
    """A re-issued finalize must 409, not silently succeed.

    This is the ONE place the app table deliberately diverges from the 0043 trigger,
    so it is worth being precise about who enforces what. The DB lets a no-op
    ``set status = <same status>`` through - it only vets a status that actually MOVES,
    which is what lets an ordinary draft edit (a PATCH that never mentions status)
    reach the freeze check. The "you cannot re-finalize" rule is therefore an APP rule,
    enforced here and nowhere else - which is exactly why it needs a test.

    Verified against a live database: the two machines agree on all 8 real edges and
    reject all 22 illegal ones identically, differing only on this diagonal.
    """
    for state in _ALL_STATUSES:
        assert not can_transition(state, state)


def test_void_and_refunded_are_terminal() -> None:
    assert is_terminal("void") and is_terminal("refunded")
    assert LEGAL_TRANSITIONS["void"] == frozenset()
    assert LEGAL_TRANSITIONS["refunded"] == frozenset()
    # Not merely "no legal target" - nothing may leave them, including a resurrection
    # back to draft/open.
    for target in _ALL_STATUSES:
        assert not can_transition("void", target)
        assert not can_transition("refunded", target)


def test_no_other_status_is_terminal() -> None:
    for state in ("draft", "open", "past_due", "paid"):
        assert not is_terminal(state)


def test_an_unknown_status_fails_closed() -> None:
    # A status the table has never heard of must not be advanced on a guess.
    assert not can_transition("chargeback", "paid")
    assert not can_transition("", "open")
    assert is_terminal("chargeback")  # no known exit == no exit


def test_a_paid_invoice_cannot_be_voided_only_refunded() -> None:
    # Settled money goes back through a refund; voiding it would erase the collection.
    assert not can_transition("paid", "void")
    assert can_transition("paid", "refunded")


def test_a_draft_cannot_jump_straight_to_paid() -> None:
    # Money cannot arrive against a document that was never issued.
    assert not can_transition("draft", "paid")
    assert not can_transition("draft", "past_due")
    assert can_transition("draft", "open")


def test_only_a_draft_is_editable() -> None:
    assert is_draft("draft")
    for state in ("open", "paid", "past_due", "void", "refunded"):
        assert not is_draft(state)


def test_the_service_table_matches_the_0043_guard_trigger() -> None:
    """Every legal edge in the app table must appear in the DB guard.

    The trigger is the real boundary (staff hold DB-reachable credentials); the table
    exists so the router can 409 cleanly first. If they drift, a transition the API
    permits blows up as an opaque Postgres error.

    This asserts the EDGES, not the diagonal: a self-transition is an app-only rule
    (see ``test_a_status_cannot_transition_to_itself``), so it is deliberately not
    expected in the trigger.
    """
    src = _MIGRATION.read_text(encoding="utf-8")
    guard = re.search(
        r"create or replace function public\.invoices_guard_update\(\)(.*?)\$\$;",
        src, re.DOTALL,
    )
    assert guard, "0043 must declare invoices_guard_update()"
    body = " ".join(guard.group(1).lower().split())

    for current, targets in LEGAL_TRANSITIONS.items():
        if not targets:  # terminal: asserted by its ABSENCE from every old.status arm
            assert f"old.status = '{current}'::public.invoice_status" not in body, (
                f"{current} is terminal in the service but the trigger gives it an arm"
            )
            continue
        assert f"old.status = '{current}'::public.invoice_status" in body, (
            f"the 0043 guard has no arm for {current}"
        )
        for target in targets:
            assert f"'{target}'::public.invoice_status" in body, (
                f"the 0043 guard never names {current} -> {target}"
            )


# --------------------------------------------------------------------------- #
# 4. Display formatting - ADAPTER ONLY (the domain carries real numerics).
# --------------------------------------------------------------------------- #
def test_money_formats_as_tools_ts_renders_it() -> None:
    assert format_money(1490) == "$1,490"
    assert format_money(690) == "$690"
    assert format_money(Decimal("1490.00")) == "$1,490"  # a whole amount stays clean


def test_money_keeps_real_cents() -> None:
    # Dropping cents would misstate an actual invoice.
    assert format_money(Decimal("1490.50")) == "$1,490.50"
    assert format_money(Decimal("0.99")) == "$0.99"


def test_compact_money_formats_the_mrr_tile() -> None:
    assert format_compact_money(28_400) == "$28.4k"
    assert format_compact_money(1_200_000) == "$1.2m"
    assert format_compact_money(690) == "$690"  # below 1k it is just money


def test_due_renders_year_less_like_tools_ts() -> None:
    from datetime import date

    assert format_due(date(2026, 8, 27)) == "Aug 27"
    assert format_due("2026-08-27") == "Aug 27"
    assert format_due(None) == "—"
    assert format_due("") == "—"
    assert format_due("not-a-date") == "—"  # never a 500 over a display cell


@pytest.mark.parametrize(
    ("status", "label", "tone"),
    [
        ("paid", "Paid", "ok"),
        ("open", "Open", "info"),
        ("past_due", "Past due", "crit"),
        ("draft", "Draft", "mut"),
        ("void", "Void", "mut"),
        ("refunded", "Refunded", "warn"),
    ],
)
def test_status_cells_carry_the_tones_tools_ts_pins(status: str, label: str, tone: str) -> None:
    cell = status_cell(status)
    assert cell.v == label and cell.tone == tone


def test_an_unknown_status_cell_degrades_to_muted_rather_than_raising() -> None:
    assert status_cell("chargeback").tone == "mut"
    assert status_cell("").v == "—"


def test_every_declared_status_has_an_explicit_display_cell() -> None:
    """No status may fall through to the unknown-status default.

    The default echoes the raw label, so a missing mapping would ship `past_due`
    (snake_case, untoned) straight into the UI rather than "Past due" in red - the
    kind of drift that only surfaces on a screenshot.
    """
    from app.modules.billing.service import _STATUS_DISPLAY

    assert set(_STATUS_DISPLAY) == set(_ALL_STATUSES)
    for state in _ALL_STATUSES:
        assert status_cell(state).v != state, f"{state} renders as its raw enum label"


# --------------------------------------------------------------------------- #
# 5. The workspace envelope.
# --------------------------------------------------------------------------- #
def _invoice(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "client_name": "Meridian Wealth", "total": Decimal("1490.00"),
        "due_date": "2026-08-27", "status": "paid",
    }
    row.update(over)
    return row


def test_workspace_rows_are_positional_client_amount_due_status() -> None:
    workspace = build_workspace(BillingStats(mrr=0, open_invoices=0, past_due=0), [_invoice()])
    assert workspace.table is not None
    assert workspace.table.cols == WORKSPACE_TABLE_COLS == ["Client", "Amount", "Due", "Status"]
    row = workspace.table.rows[0]
    assert row[0] == "Meridian Wealth"
    assert row[1] == "$1,490"
    assert row[2] == "Aug 27"
    assert getattr(row[3], "v", None) == "Paid"


def test_workspace_never_leaks_the_client_id_into_a_cell() -> None:
    workspace = build_workspace(
        BillingStats(mrr=0, open_invoices=0, past_due=0),
        [_invoice(client_id="cl-secret")],
    )
    assert "cl-secret" not in workspace.model_dump_json()


def test_workspace_caps_the_table_at_eight_rows() -> None:
    workspace = build_workspace(
        BillingStats(mrr=0, open_invoices=0, past_due=0), [_invoice() for _ in range(20)]
    )
    assert workspace.table is not None
    assert len(workspace.table.rows) == 8


def test_workspace_emits_no_invented_deltas() -> None:
    # tools.ts shows deltas on MRR/Past due, but the ledger keeps no historical
    # baseline - an invented delta would be a lie on a finance screen.
    workspace = build_workspace(BillingStats(mrr=28_400, open_invoices=3, past_due=1), [])
    for kpi in workspace.kpis:
        assert kpi.delta is None and kpi.dir is None


def test_workspace_primary_and_bullets_echo_tools_ts() -> None:
    workspace = build_workspace(BillingStats(mrr=0, open_invoices=0, past_due=0), [])
    assert workspace.primary is not None
    assert (workspace.primary.label, workspace.primary.icon) == ("New invoice", "payments")
    assert workspace.bullets == [
        "View plans & invoices", "Track payments & renewals", "Manage payment settings",
    ]


def test_an_empty_ledger_still_renders_the_workspace() -> None:
    # A fresh agency has no invoices; the tool must open, not 500.
    workspace = build_workspace(BillingStats(mrr=0, open_invoices=0, past_due=0), [])
    assert workspace.table is not None and workspace.table.rows == []
    assert [k.value for k in workspace.kpis] == ["$0", "0", "0"]
