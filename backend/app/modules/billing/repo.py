"""Data access for the invoice ledger (``invoices`` / ``invoice_line_items``) via the
RLS-scoped ``rls_connection`` seam + the privileged ``ServiceBillingStore`` the
nightly past-due sweep runs through.

Every read + mutation on ``BillingRepo`` is tenant/actor-scoped by Postgres RLS:
staff read the whole ledger, clients are excluded (no base-table select policy), and
only OWNER/ADMIN may write (the ``0043`` insert/update/delete policies + the
``require_role("owner","admin")`` app gate - billing is finance-sensitive, so the
usual owner/admin/manager LEADS set is deliberately NOT used). Methods are
synchronous (psycopg is sync) - the router offloads them with ``asyncio.to_thread``.

THE MRR SEAM: :meth:`BillingRepo.subscription_mrr` reads ``sum(clients.mrr)`` - it is
the ONLY MRR source, and it deliberately does not touch ``invoices`` at all. The
ledger answers "what was issued / collected"; the subscription table answers "what do
we bill per month". Keeping them in separate methods over separate tables makes the
distinction structural rather than a comment someone can drift away from. See
``router.py``'s docstring.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# Invoices newest-issued first; `number` is the stable tiebreak (an unstable sort
# would duplicate/skip rows between pages). `issue_date` is nullable on a draft, so
# NULLS FIRST keeps un-issued drafts at the top where an operator is working.
_INVOICE_ORDER = " order by issue_date desc nulls first, number desc"


class BillingRepo:
    """Thin RLS-scoped repository over the invoice ledger + the subscription MRR read."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- invoice reads --------------------------------------------------------
    def list_invoices(
        self,
        *,
        client_id: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.invoices"
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += _INVOICE_ORDER
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_by_number(self, number: str) -> dict[str, Any] | None:
        """One invoice by its PUBLIC number (INV-####), or ``None`` when unknown or
        RLS-invisible - the router turns both into the same 404, so a caller cannot
        probe for the existence of an invoice it may not see."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.invoices where number = %s limit 1", (number,))
            return cur.fetchone()

    def lines_for(self, invoice_id: str) -> _Rows:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.invoice_line_items where invoice_id = %s "
                "order by sort_order, created_at",
                (invoice_id,),
            )
            return cur.fetchall()

    # --- the MRR read (the SUBSCRIPTION table - never the ledger) -------------
    def subscription_mrr(self) -> int:
        """``sum(clients.mrr)`` over ACTIVE subscriptions - the MRR KPI.

        This is the load-bearing scope rule of the whole module, so it is worth
        spelling out why it is not `sum(invoices)`:

        * summing invoices would DOUBLE-COUNT a one-off (a project invoice is not
          recurring revenue), and
        * it would MISS an active retainer in a month nobody has invoiced yet.

        `status = 'active'` scopes it to subscriptions actually running: a trial pays
        nothing, a paused account has stopped, and a `past_due` client's run-rate is
        not money we can count on. `coalesce` keeps an empty book at 0 rather than
        NULL.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select coalesce(sum(mrr), 0) as mrr from public.clients "
                "where status = 'active'"
            )
            row = cur.fetchone()
            return int(row["mrr"]) if row and row.get("mrr") is not None else 0

    def invoice_counts(self) -> dict[str, int]:
        """The two LEDGER tiles: how many invoices are open, how many are past due.

        Separate from :meth:`subscription_mrr` on purpose - these come from the
        ledger, MRR never does.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "count(*) filter (where status = 'open') as open_invoices, "
                "count(*) filter (where status = 'past_due') as past_due "
                "from public.invoices"
            )
            row = cur.fetchone()
            if not row:
                return {"open_invoices": 0, "past_due": 0}
            return {
                "open_invoices": int(row.get("open_invoices", 0) or 0),
                "past_due": int(row.get("past_due", 0) or 0),
            }

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None``
        - used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    # --- the revenue report (COLLECTED cash - explicitly NOT MRR) -------------
    def revenue_by_period(
        self, *, client_id: str | None = None, limit: int = 12
    ) -> _Rows:
        """COLLECTED revenue per calendar month: paid invoices bucketed by ``paid_at``.

        `status = 'paid'` ONLY. A refunded invoice was collected and then given back,
        so it is not revenue; a void/open/draft one never arrived. Bucketing on
        `paid_at` (not `issue_date`) is what makes this CASH rather than billings - an
        invoice issued in March and paid in May is May's money.

        This is deliberately a different number from MRR and will not agree with it.
        """
        query = (
            "select to_char(date_trunc('month', paid_at), 'YYYY-MM') as period, "
            "count(*) as invoices, coalesce(sum(total), 0) as collected "
            "from public.invoices "
            "where status = 'paid' and paid_at is not null"
        )
        params: list[Any] = []
        if client_id is not None:
            query += " and client_id = %s"
            params.append(client_id)
        query += " group by 1 order by 1 desc limit %s"
        params.append(limit)
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    # --- invoice mutations ----------------------------------------------------
    def create_invoice(self, values: dict[str, Any]) -> dict[str, Any] | None:
        """Insert one DRAFT invoice and return the row (``number`` is DB-assigned off
        ``invoices_number_seq``). Column names are static ``sql.Identifier``s built
        from a server-side dict; values are always bound."""
        columns = sql.SQL(", ").join(sql.Identifier(col) for col in values)
        placeholders = sql.SQL(", ").join(sql.Placeholder() * len(values))
        stmt = sql.SQL(
            "insert into public.invoices ({cols}) values ({vals}) returning *"
        ).format(cols=columns, vals=placeholders)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(values.values()))
            return cur.fetchone()

    def update_invoice(
        self, number: str, changes: dict[str, Any], expected_status: str
    ) -> dict[str, Any] | None:
        """Update one invoice by number, but ONLY while it is still in
        ``expected_status`` - the optimistic-concurrency guard.

        Returns ``None`` when nothing matched: either the number is unknown/invisible
        OR a racing transition already moved the row. The router turns that into a
        409 rather than silently applying a stale edit on top of a status the caller
        never saw. ``0043``'s trigger is the real boundary; this keeps the API honest.
        """
        if not changes:
            return self.get_by_number(number)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.invoices set {sets} where number = %s and status = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), number, expected_status])
            return cur.fetchone()

    # --- line mutations (draft-only; 0043's line guard enforces it at the DB) --
    def add_lines(self, invoice_id: str, lines: list[dict[str, Any]]) -> _Rows:
        """Bulk-insert line items. Each dict MUST already carry its server-computed
        ``line_total`` (``service.compute_line_total``) - this layer does no
        arithmetic. Empty input is a no-op that never opens a connection."""
        if not lines:
            return []
        with rls_connection(self._user_id) as cur:
            for line in lines:
                cur.execute(
                    "insert into public.invoice_line_items "
                    "(invoice_id, description, quantity, unit_amount, line_total, sort_order) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    (
                        invoice_id,
                        line.get("description", ""),
                        line.get("quantity", 1),
                        line.get("unit_amount", 0),
                        line.get("line_total", 0),
                        line.get("sort_order", 0),
                    ),
                )
            cur.execute(
                "select * from public.invoice_line_items where invoice_id = %s "
                "order by sort_order, created_at",
                (invoice_id,),
            )
            return cur.fetchall()

    def delete_line(self, invoice_id: str, line_id: str) -> bool:
        """Delete ONE line, scoped to its invoice so a caller cannot delete a line off
        a different invoice by guessing an id. ``False`` when nothing matched."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "delete from public.invoice_line_items where id = %s and invoice_id = %s "
                "returning id",
                (line_id, invoice_id),
            )
            return cur.fetchone() is not None

    def set_totals(
        self, number: str, *, subtotal: Decimal, tax: Decimal, total: Decimal
    ) -> dict[str, Any] | None:
        """Write the recomputed money fields onto a DRAFT invoice.

        Guarded on ``status = 'draft'`` like every other edit: if the invoice was
        finalized between the line mutation and this write, the ``0043`` freeze would
        reject it anyway - failing here returns a clean 409 instead.
        """
        return self.update_invoice(
            number, {"subtotal": subtotal, "tax": tax, "total": total}, "draft"
        )


def get_billing_repo(user: CurrentUserDep) -> BillingRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return BillingRepo(user.id)


BillingRepoDep = Annotated[BillingRepo, Depends(get_billing_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the PAST-DUE sweep.
# --------------------------------------------------------------------------- #
# The beat sweep has no user JWT, so - exactly like the audit / context / keyword
# workers - it writes on the privileged connection. service_role bypasses the RLS
# policies but NOT the triggers, so `invoices_guard_update` still vets the flip;
# `open -> past_due` is a legal transition, so it passes.
class ServiceBillingStore:
    """Concrete invoice store over ``privileged_connection`` (BYPASSRLS)."""

    def flip_overdue_open_invoices(self, *, grace_days: int = 0) -> int:
        """Flip every OPEN invoice past its due date (plus grace) to ``past_due``.

        Idempotent by construction, in two ways that matter:

        * ``where status = 'open'`` means a second run finds nothing left to flip -
          it never re-touches a row, so a Celery redelivery is a no-op.
        * it is a SINGLE statement, so Postgres's own row locks serialise two
          concurrent beat ticks: the loser's UPDATE simply re-evaluates the predicate
          against the committed row and matches zero. That is why this task needs no
          advisory/overlap lock (the codebase has none; the context dispatcher uses
          FOR UPDATE SKIP LOCKED claims for the same reason).

        Returns the number of invoices flipped.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.invoices set status = 'past_due' "
                "where status = 'open' and due_date is not null "
                "and due_date < (current_date - make_interval(days => %s)) "
                "returning id",
                (grace_days,),
            )
            return len(cur.fetchall())


def service_billing_store() -> ServiceBillingStore:
    """The privileged invoice store the past-due sweep uses (service_role, BYPASSRLS)."""
    return ServiceBillingStore()
