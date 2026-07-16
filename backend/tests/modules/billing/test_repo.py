"""Billing repo SQL: the RLS seam, the SQL-safety rules, and the MRR provenance.

NO DB. ``rls_connection`` / ``privileged_connection`` are replaced with a fake context
manager yielding a capturing cursor, so every test asserts on the SQL the repo
actually composes and the identity it binds it under - the two things that decide
whether a tenant boundary holds.

Three invariants are load-bearing here (see ``backend/CLAUDE.md`` invariants #3/#10):

1. **The RLS seam is the boundary.** ``BillingRepo`` must open ``rls_connection`` with
   the caller's VERIFIED user id (never a client-supplied string), so Postgres applies
   the ``0043`` policies. A read that slipped onto ``privileged_connection`` would
   silently BYPASS RLS and hand every tenant's invoices to anyone.
2. **Never string-format a value or an identifier.** Every value must arrive as a
   bound ``%s`` param; the only dynamic identifiers (the INSERT/UPDATE column lists)
   must be quoted via ``psycopg.sql.Identifier``.
3. **MRR reads ``clients``, never ``invoices``.** Asserted at the SQL level - the
   strongest form of the module's scope rule, because it holds no matter what the
   service or the router later do with the number.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from app.modules.billing import repo as repo_mod
from app.modules.billing.repo import (
    BillingRepo,
    ServiceBillingStore,
    get_billing_repo,
    service_billing_store,
)

pytestmark = pytest.mark.unit

_CALLER = "00000000-0000-0000-0000-0000000000a1"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION = _REPO_ROOT / "db" / "migrations" / "0043_billing.sql"


class _FakeCursor:
    """Captures every ``execute(query, params)`` and replays canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[Any, Any]] = []
        self.row_queue: list[list[dict[str, Any]]] | None = None

    def execute(self, query: Any, params: Any = None) -> None:
        self.calls.append((query, params))
        if self.row_queue is not None:
            self.rows = self.row_queue.pop(0) if self.row_queue else []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    @property
    def queries(self) -> list[str]:
        return [_as_text(q) for q, _p in self.calls]

    @property
    def last_query(self) -> str:
        return _as_text(self.calls[-1][0])

    @property
    def last_params(self) -> Any:
        return self.calls[-1][1]


def _as_text(query: Any) -> str:
    """Render a str or a ``psycopg.sql.Composable`` to comparable text."""
    if isinstance(query, sql.Composable):
        return str(query.as_string(None))  # type: ignore[arg-type]
    return str(query)


class _Seam:
    """Records which connection seam was opened, and under which identity."""

    def __init__(self, cur: _FakeCursor) -> None:
        self.cur = cur
        self.rls_ids: list[str] = []
        self.privileged_opens = 0

    @contextlib.contextmanager
    def rls(self, user_id: str, **_kw: Any) -> Iterator[_FakeCursor]:
        self.rls_ids.append(user_id)
        yield self.cur

    @contextlib.contextmanager
    def privileged(self, **_kw: Any) -> Iterator[_FakeCursor]:
        self.privileged_opens += 1
        yield self.cur


@pytest.fixture
def cur() -> _FakeCursor:
    return _FakeCursor()


@pytest.fixture
def seam(cur: _FakeCursor, monkeypatch: pytest.MonkeyPatch) -> _Seam:
    """Replace BOTH connection seams so a test can prove which one a method used."""
    s = _Seam(cur)
    monkeypatch.setattr(repo_mod, "rls_connection", s.rls)
    monkeypatch.setattr(repo_mod, "privileged_connection", s.privileged)
    return s


@pytest.fixture
def repo() -> BillingRepo:
    return BillingRepo(_CALLER)


# --------------------------------------------------------------------------- #
# 1. THE scope rule at the SQL level: MRR reads clients, never invoices.
# --------------------------------------------------------------------------- #
def test_subscription_mrr_reads_clients_mrr_and_never_touches_invoices(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The strongest statement of the module's scope rule.

    Asserted on the emitted SQL rather than on a return value, because THIS is what
    cannot be worked around: whatever the service or the router later do, the MRR
    number is produced by a query over ``public.clients``. If someone ever "optimises"
    it into a sum over the ledger, the statement changes and this fails.
    """
    cur.rows = [{"mrr": 28_400}]
    assert repo.subscription_mrr() == 28_400
    query = cur.last_query.lower()
    assert "from public.clients" in query
    assert "sum(mrr)" in query
    assert "invoice" not in query, "MRR must never be derived from the invoice ledger"


def test_subscription_mrr_counts_only_active_subscriptions(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A trial pays nothing, a paused account has stopped, and a past_due client's
    # run-rate is not money we can count on - none of them belong in the run-rate.
    repo.subscription_mrr()
    assert "where status = 'active'" in cur.last_query.lower()


def test_subscription_mrr_coalesces_an_empty_book_to_zero_not_null(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # sum() over zero rows is NULL in SQL; the tile must read 0.
    cur.rows = []
    assert repo.subscription_mrr() == 0
    assert "coalesce(sum(mrr), 0)" in cur.last_query


def test_invoice_counts_read_the_ledger_and_never_the_subscription_table(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The other half: Open invoices / Past due ARE ledger counts.
    cur.rows = [{"open_invoices": 3, "past_due": 1}]
    assert repo.invoice_counts() == {"open_invoices": 3, "past_due": 1}
    query = cur.last_query.lower()
    assert "from public.invoices" in query
    assert "public.clients" not in query


def test_the_mrr_and_the_ledger_counts_are_separate_statements(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Kept apart on purpose: one query joining both tables would make it far too easy
    # for a later edit to start summing invoices into the MRR tile.
    repo.subscription_mrr()
    repo.invoice_counts()
    assert len(cur.calls) == 2
    assert "public.clients" in cur.queries[0] and "public.invoices" not in cur.queries[0]
    assert "public.invoices" in cur.queries[1] and "public.clients" not in cur.queries[1]


# --------------------------------------------------------------------------- #
# 2. The RLS seam IS the tenant boundary.
# --------------------------------------------------------------------------- #
def test_every_read_binds_the_callers_verified_id_on_the_rls_seam(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Each read must go through ``rls_connection(<caller>)``. On the privileged seam
    the same SQL would bypass every ``0043`` policy and return every tenant's ledger."""
    repo.list_invoices()
    repo.get_by_number("INV-0001")
    repo.lines_for("inv-1")
    repo.subscription_mrr()
    repo.invoice_counts()
    repo.client_name_for("cl-1")
    repo.revenue_by_period()

    assert seam.rls_ids == [_CALLER] * 7  # every call, same verified identity
    assert seam.privileged_opens == 0  # nothing leaked onto the BYPASSRLS seam


def test_every_mutation_stays_on_the_rls_seam(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Writes are RLS-scoped too: the 0043 insert/update policies (owner/admin only)
    # are what actually enforce the write boundary, and they only apply on this seam.
    cur.rows = [{"id": "inv-1", "number": "INV-0001"}]
    repo.create_invoice({"client_id": "cl-1", "client_name": "Acme"})
    repo.update_invoice("INV-0001", {"status": "open"}, "draft")
    repo.add_lines("inv-1", [{"description": "x", "line_total": Decimal("1.00")}])
    repo.delete_line("inv-1", "li-1")
    repo.set_totals(
        "INV-0001", subtotal=Decimal("1.00"), tax=Decimal("0.00"), total=Decimal("1.00")
    )

    assert seam.privileged_opens == 0
    assert set(seam.rls_ids) == {_CALLER}


def test_the_repo_dependency_binds_the_identity_from_the_verified_user(seam: _Seam) -> None:
    """``get_billing_repo`` must take the id off the server-verified ``CurrentUser``.

    This is the join between auth and RLS: bind anything client-supplied here and the
    whole boundary is impersonatable.
    """
    from app.core.auth import CurrentUser

    user = CurrentUser(
        id="00000000-0000-0000-0000-0000000000b2", email="op@aios.dev", role="admin",
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )
    built = get_billing_repo(user)
    built.invoice_counts()
    assert seam.rls_ids == ["00000000-0000-0000-0000-0000000000b2"]


def test_repo_reads_are_not_client_scoped_in_sql_so_rls_decides(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An unfiltered read emits NO client predicate - visibility is Postgres's call.

    Staff see the whole ledger (``is_staff()``); clients have no select policy at all.
    Hard-coding a client filter here would be a second, divergent boundary.
    """
    repo.list_invoices()
    assert "where" not in cur.last_query.lower()
    assert "client_id" not in cur.last_query


# --------------------------------------------------------------------------- #
# 3. INV-#### is the public id (a sequence default, never a UUID).
# --------------------------------------------------------------------------- #
def test_the_repo_addresses_invoices_by_number_not_by_uuid(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # Every caller-facing lookup/mutation keys off `number`; the uuid is internal
    # plumbing (the line-items FK) and never appears in a route.
    repo.get_by_number("INV-0001")
    assert "where number = %s" in cur.last_query
    assert cur.last_params == ("INV-0001",)

    cur.rows = [{"id": "inv-1"}]
    repo.update_invoice("INV-0001", {"status": "open"}, "draft")
    assert "where number = %s" in cur.last_query


def test_the_insert_never_supplies_a_number_so_the_db_sequence_assigns_it(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """``number`` is a DB DEFAULT off ``invoices_number_seq`` - the app must not invent
    one. Two racing creates picking their own "next" number would collide on the
    unique index (or worse, silently reuse an invoice number).
    """
    cur.rows = [{"id": "inv-1", "number": "INV-0001"}]
    repo.create_invoice({"client_id": "cl-1", "client_name": "Acme"})
    text = cur.last_query
    assert "number" not in text
    assert "INV-" not in text


def test_0043_declares_the_number_as_an_inv_sequence_default_not_a_uuid() -> None:
    """The other half of the contract: the DB must actually mint ``INV-####``.

    Mirrors the ``J-####`` task-code pattern in 0011. A uuid here would leak internal
    plumbing onto every invoice a client sees and be unquotable on a bank transfer.
    """
    src = _MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(src.lower().split())
    assert "create sequence if not exists public.invoices_number_seq" in normalized
    assert "'inv-' || lpad(nextval('public.invoices_number_seq')::text, 4, '0')" in normalized
    assert "number text not null unique" in normalized
    # ... and the number is emphatically NOT the uuid default.
    assert "number text not null unique default gen_random_uuid()" not in normalized


def test_0043_keeps_the_financial_paper_trail_with_on_delete_restrict() -> None:
    """``invoices.client_id`` must be ``on delete restrict``, unlike every other
    module's cascade/set-null.

    A cascade would ERASE what a departing client was billed; a set-null would leave
    money owed by nobody. RESTRICT means a client with invoices cannot be deleted at
    all until the ledger is dealt with deliberately - that is the point of a financial
    record, and it is why this one FK differs from the house default.
    """
    src = _MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(src.lower().split())
    assert "client_id uuid not null references public.clients (id) on delete restrict" in normalized
    # The line items DO cascade - they have no meaning without their invoice.
    assert "invoice_id uuid not null references public.invoices (id) on delete cascade" in normalized


def test_0043_declares_the_guard_trigger_with_the_freeze_and_the_transitions() -> None:
    """The DB is the real boundary (staff hold DB-reachable credentials), so the guard
    must exist, be SECURITY DEFINER with an empty search_path, and be wired as a BEFORE
    UPDATE trigger - not merely defined."""
    src = _MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(src.lower().split())

    assert "create or replace function public.invoices_guard_update()" in normalized
    assert "security definer" in normalized
    assert "set search_path = ''" in normalized
    assert "before update on public.invoices for each row execute function " \
           "public.invoices_guard_update()" in normalized

    guard = re.search(
        r"create or replace function public\.invoices_guard_update\(\)(.*?)\$\$;",
        src, re.DOTALL,
    )
    assert guard
    body = " ".join(guard.group(1).lower().split())
    # The state machine + its terminal states.
    assert "illegal invoice status transition" in body
    # The finalize freeze: the money/date columns are named in the immutability check.
    assert "old.status <> 'draft'::public.invoice_status" in body
    for column in ("subtotal", "tax", "total", "issue_date", "due_date", "client_id"):
        assert f"new.{column} is distinct from old.{column}" in body, (
            f"the freeze does not lock {column} - it could be rewritten after issue"
        )
    # ... and the identity columns are locked forever, not just outside draft.
    assert "new.number is distinct from old.number" in body


def test_0043_freezes_the_line_items_too() -> None:
    """The invoices guard cannot see the line items, so a SECOND trigger closes the
    hole: without it, an operator could edit the billed lines of an issued invoice
    directly, changing what was billed while `invoices` sat frozen."""
    src = _MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(src.lower().split())
    assert "create or replace function public.invoice_line_items_guard()" in normalized
    assert "before insert or update or delete on public.invoice_line_items" in normalized


# --------------------------------------------------------------------------- #
# 4. SQL safety: values bound, identifiers quoted, nothing interpolated.
# --------------------------------------------------------------------------- #
_INJECTION = "'; drop table public.invoices; --"


@pytest.mark.parametrize(
    ("kwarg", "column"),
    [
        ("client_id", "client_id = %s"),
        ("status", "status = %s"),
        ("kind", "kind = %s"),
    ],
)
def test_every_list_filter_is_a_bound_param_never_interpolated(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam, kwarg: str, column: str
) -> None:
    """Drive an injection payload through each filter: the SQL must carry a ``%s``
    placeholder and the payload must appear ONLY in the params."""
    repo.list_invoices(**{kwarg: _INJECTION})
    query, params = cur.calls[-1]
    text = _as_text(query)
    assert column in text
    assert _INJECTION not in text  # never spliced into the statement
    assert _INJECTION in params  # ... it stays inert data


def test_pagination_is_bound_too(repo: BillingRepo, cur: _FakeCursor, seam: _Seam) -> None:
    repo.list_invoices(limit=5, offset=10)
    assert "limit %s offset %s" in cur.last_query
    assert cur.last_params == [5, 10]


def test_omitted_filters_add_no_clause_at_all(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # A None filter must not become "= NULL" (which matches nothing) nor a literal.
    repo.list_invoices(client_id=None, status=None, kind=None)
    assert "where" not in cur.last_query.lower()
    assert cur.last_params == []


def test_list_orders_newest_first_with_a_stable_tiebreak(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # `number` keeps paging deterministic across same-day invoices; NULLS FIRST keeps
    # un-issued drafts (issue_date NULL) at the top where an operator is working.
    repo.list_invoices()
    assert "order by issue_date desc nulls first, number desc" in cur.last_query


def test_create_quotes_column_identifiers_and_binds_values(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The INSERT's column list is a dynamic identifier: it must be composed with
    ``sql.Identifier`` (double-quoted), never f-stringed."""
    cur.rows = [{"id": "inv-1"}]
    repo.create_invoice({"client_id": "cl-1", "client_name": _INJECTION})
    text = cur.last_query
    assert '"client_id"' in text and '"client_name"' in text  # quoted identifiers
    assert _INJECTION not in text  # the value is not spliced
    assert cur.last_params == ["cl-1", _INJECTION]


def test_update_quotes_column_identifiers_and_binds_values(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"id": "inv-1"}]
    repo.update_invoice("INV-0001", {"status": "open", "notes": _INJECTION}, "draft")
    text = cur.last_query
    assert '"status" = %s' in text and '"notes" = %s' in text
    assert _INJECTION not in text
    assert cur.last_params == ["open", _INJECTION, "INV-0001", "draft"]


def test_the_number_is_bound_rather_than_formatted(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The number comes straight off the URL path - the one caller-controlled string.
    repo.get_by_number(_INJECTION)
    assert _INJECTION not in cur.last_query
    assert _INJECTION in cur.last_params


# --------------------------------------------------------------------------- #
# 5. Optimistic concurrency + the draft guard.
# --------------------------------------------------------------------------- #
def test_the_update_is_guarded_on_the_status_we_read(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """The optimistic-concurrency guard: ``where number = %s and status = %s``.

    Without the status predicate, a stale edit would land on top of a transition the
    caller never saw (e.g. a PATCH written against a draft that another operator has
    since finalized).
    """
    cur.rows = [{"id": "inv-1"}]
    repo.update_invoice("INV-0001", {"notes": "x"}, "draft")
    assert "where number = %s and status = %s" in cur.last_query
    assert cur.last_params[-2:] == ["INV-0001", "draft"]


def test_an_update_that_matches_nothing_returns_none(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """RLS invisibility, an unknown number and a racing transition are indistinguish-
    able here - all three match zero rows. The router turns that into a clean 409/404."""
    cur.rows = []
    assert repo.update_invoice("INV-0001", {"status": "open"}, "draft") is None


def test_set_totals_is_guarded_on_draft(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # If the invoice was finalized between the line mutation and this write, 0043's
    # freeze would reject it anyway - failing here returns a clean 409 instead.
    cur.rows = [{"id": "inv-1"}]
    repo.set_totals(
        "INV-0001", subtotal=Decimal("1400.00"), tax=Decimal("90.00"), total=Decimal("1490.00")
    )
    assert cur.last_params == [
        Decimal("1400.00"), Decimal("90.00"), Decimal("1490.00"), "INV-0001", "draft"
    ]


def test_update_with_no_changes_degrades_to_a_plain_read(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"number": "INV-0001"}]
    assert repo.update_invoice("INV-0001", {}, "draft") == {"number": "INV-0001"}
    assert len(cur.calls) == 1
    assert "update" not in cur.last_query.lower()  # never an empty SET clause


# --------------------------------------------------------------------------- #
# 6. Lines.
# --------------------------------------------------------------------------- #
def test_add_lines_binds_the_precomputed_line_total(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # The repo does NO arithmetic: the service computed line_total, the repo persists
    # it. One source of truth for money.
    repo.add_lines("inv-1", [{
        "description": "Retainer", "quantity": Decimal("2"),
        "unit_amount": Decimal("250.00"), "line_total": Decimal("500.00"), "sort_order": 0,
    }])
    insert = cur.calls[0]
    assert "insert into public.invoice_line_items" in _as_text(insert[0])
    assert insert[1] == ("inv-1", "Retainer", Decimal("2"), Decimal("250.00"),
                         Decimal("500.00"), 0)


def test_add_lines_with_nothing_never_opens_a_connection(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    # An empty batch must be a no-op, not an INSERT with an empty VALUES list.
    assert repo.add_lines("inv-1", []) == []
    assert cur.calls == [] and seam.rls_ids == []


def test_delete_line_is_scoped_to_its_invoice(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Scoping the delete to the invoice stops a caller deleting a line off a
    DIFFERENT invoice by guessing an id - RLS would happily allow it (an owner may
    write any invoice), so the scope has to be in the statement."""
    cur.rows = [{"id": "li-1"}]
    assert repo.delete_line("inv-1", "li-1") is True
    assert "where id = %s and invoice_id = %s" in cur.last_query
    assert cur.last_params == ("li-1", "inv-1")


def test_delete_line_reports_false_when_nothing_matched(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = []
    assert repo.delete_line("inv-1", "li-nope") is False


def test_lines_are_read_in_a_stable_display_order(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.lines_for("inv-1")
    assert "order by sort_order, created_at" in cur.last_query


# --------------------------------------------------------------------------- #
# 7. The revenue report: COLLECTED cash, not billings and not MRR.
# --------------------------------------------------------------------------- #
def test_revenue_counts_only_paid_invoices_bucketed_by_paid_at(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """Collected revenue is CASH: only `paid`, bucketed on `paid_at`.

    * `status = 'paid'` excludes refunded (collected then given back), void, open and
      draft - none of that is money we have.
    * bucketing on `paid_at` (not `issue_date`) is what makes it cash rather than
      billings: an invoice issued in March and paid in May is May's money.
    """
    repo.revenue_by_period()
    query = cur.last_query.lower()
    assert "where status = 'paid' and paid_at is not null" in query
    assert "date_trunc('month', paid_at)" in query
    assert "refunded" not in query  # a refund is not revenue
    assert "public.clients" not in query  # ... and this is not MRR


def test_revenue_binds_its_client_filter_and_window(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.revenue_by_period(client_id=_INJECTION, limit=6)
    assert _INJECTION not in cur.last_query
    assert cur.last_params == [_INJECTION, 6]


def test_revenue_orders_newest_period_first(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    repo.revenue_by_period()
    assert "group by 1 order by 1 desc limit %s" in cur.last_query


def test_client_name_for_returns_none_when_rls_hides_the_client(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    """An invisible client is indistinguishable from a missing one - the router turns
    both into 404, so a caller cannot probe for the existence of another tenant."""
    cur.rows = []
    assert repo.client_name_for("cl-someone-elses") is None
    assert cur.last_params == ("cl-someone-elses",)


def test_client_name_for_returns_the_display_snapshot(
    repo: BillingRepo, cur: _FakeCursor, seam: _Seam
) -> None:
    cur.rows = [{"name": "Meridian Wealth"}]
    assert repo.client_name_for("cl-1") == "Meridian Wealth"


# --------------------------------------------------------------------------- #
# 8. The privileged sweep store (BYPASSRLS) - idempotent by construction.
# --------------------------------------------------------------------------- #
def test_the_sweep_store_uses_the_privileged_seam_only(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The beat sweep holds no user JWT, so it MUST run on ``privileged_connection``
    (service_role). It must never open an RLS connection - there is no identity to
    bind. service_role bypasses RLS but NOT the 0043 trigger, so the flip is still
    vetted (open -> past_due is legal)."""
    cur.rows = []
    ServiceBillingStore().flip_overdue_open_invoices()
    assert seam.rls_ids == []
    assert seam.privileged_opens == 1


def test_the_sweep_only_ever_touches_open_invoices(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """The idempotency that makes a Celery redelivery safe.

    ``where status = 'open'`` means a second run matches nothing - a paid/void/already-
    past_due invoice is never re-touched. Without this predicate the sweep could drag a
    settled invoice back to past_due.
    """
    cur.rows = []
    ServiceBillingStore().flip_overdue_open_invoices()
    query = cur.last_query.lower()
    assert "set status = 'past_due'" in query
    assert "where status = 'open'" in query
    assert "due_date is not null" in query  # an invoice with no due date can't be late


def test_the_sweep_binds_the_grace_window(cur: _FakeCursor, seam: _Seam) -> None:
    cur.rows = []
    ServiceBillingStore().flip_overdue_open_invoices(grace_days=3)
    assert "make_interval(days => %s)" in cur.last_query
    assert cur.last_params == (3,)


def test_the_sweep_reports_how_many_it_flipped(cur: _FakeCursor, seam: _Seam) -> None:
    cur.rows = [{"id": "inv-1"}, {"id": "inv-2"}]
    assert ServiceBillingStore().flip_overdue_open_invoices() == 2


def test_the_sweep_is_a_single_statement_so_it_needs_no_overlap_lock(
    cur: _FakeCursor, seam: _Seam
) -> None:
    """One UPDATE, so Postgres's row locks serialise two overlapping beat ticks by
    themselves: the loser re-evaluates ``status = 'open'`` against the committed row
    and matches zero. A read-then-write pair would need a lock; this does not."""
    cur.rows = []
    ServiceBillingStore().flip_overdue_open_invoices()
    assert len(cur.calls) == 1
    assert "select" not in cur.last_query.lower().split("returning")[0]


def test_the_sweep_store_factory_is_stateless(seam: _Seam) -> None:
    # Each method opens its own connection, so instances hold no handle and are safe
    # to build per call from the task.
    assert isinstance(service_billing_store(), ServiceBillingStore)
    assert service_billing_store() is not service_billing_store()
