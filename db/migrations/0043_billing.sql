-- 0043_billing.sql - Part 8 Phase 2H (Billing): the issued/collected INVOICE ledger.
--
-- RECORDS ONLY. There is NO payment gateway in v1: nothing here charges a card,
-- dunns a customer, or reconciles a provider webhook. Every status transition is a
-- MANUAL operator action recorded after the fact (the one exception is the nightly
-- `mark_past_due` sweep, which only flips an already-issued `open` invoice whose
-- due date has passed). `paid_method` is deliberately free text - it records how a
-- human says the money arrived ("bank transfer", "stripe link", "cheque"), it is not
-- a gateway enum.
--
-- THE LOAD-BEARING SCOPE RULE - MRR IS SUBSCRIPTION-DERIVED, NEVER INVOICE-DERIVED:
--   The subscription truth already lives on `public.clients` (0003): `mrr`, `tier`,
--   `status`, `renews_at`. This migration does NOT duplicate it. The MRR KPI is
--   `sum(clients.mrr)` over ACTIVE subscriptions - it is NOT `sum(invoices)`.
--   Deriving MRR from this ledger would double-count one-off invoices and miss every
--   un-invoiced month of an active retainer. `invoices` answers a DIFFERENT question:
--   what has been ISSUED and what has been COLLECTED. `Open invoices` / `Past due` DO
--   come from this ledger; MRR never does.
--
--   * invoices           - one row per issued document. `number` (INV-####) is the
--     PUBLIC id (never a UUID), mirroring the `J-####` task-code pattern in 0011.
--     `client_name` is a display SNAPSHOT so `client_id` never has to be surfaced.
--     `total` is SERVER-COMPUTED (= subtotal + tax) and a client-supplied total is
--     never trusted; `subtotal` is the sum of the line items.
--   * invoice_line_items - the billed lines. `line_total` is SERVER-COMPUTED
--     (= quantity x unit_amount).
--
-- WHY client_id IS `on delete restrict` (and NOT the usual cascade/set null):
--   Every other module lets a client delete cascade (sites) or set null (tasks,
--   keywords) because losing that row costs nothing but history. An invoice is a
--   FINANCIAL PAPER TRAIL: deleting a client must NOT erase what was billed to them,
--   and a set-null orphan would leave money owed by nobody. So a client with any
--   invoice cannot be deleted at all until the ledger is dealt with deliberately.
--   RESTRICT is the point, not an oversight.
--
-- THE THREAT MODEL (mirrors 0011's header): staff hold DB-reachable credentials, so
-- the invoice state machine CANNOT live only in FastAPI - an operator could UPDATE
-- the row directly and rewrite a finalized invoice's amounts, or resurrect a voided
-- one. It is enforced HERE by `invoices_guard_update()` (BEFORE UPDATE) +
-- `invoice_line_items_guard()`; the app-layer 409s are UX on top of that boundary,
-- not the boundary itself.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors the invoice models);
-- the module's schemas.py owns the wire shape and its own shape/enum unit tests.
--
-- RLS: any STAFF may READ (is_staff()); only OWNER/ADMIN may INSERT/UPDATE/DELETE.
-- This deliberately DIFFERS from the usual owner/admin/manager write set used across
-- the other modules: billing is finance-sensitive, so a manager (a delivery lead) is
-- NOT enough. The app gate is `require_role("owner","admin")` and it mirrors these
-- policies exactly - a caller who passed the app gate but failed RLS would get an
-- opaque database error instead of a clean 403. Clients get NO policy at all.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'invoice_status') then
    -- The legal lifecycle; `void` and `refunded` are TERMINAL (see the guard below).
    create type public.invoice_status as enum
      ('draft', 'open', 'paid', 'past_due', 'void', 'refunded');
  end if;
  if not exists (select 1 from pg_type where typname = 'invoice_kind') then
    -- `retainer` = the recurring subscription bill; `one_off` = a project/extra.
    create type public.invoice_kind as enum ('retainer', 'one_off');
  end if;
end $$;

-- The PUBLIC invoice-number sequence (INV-0001 ...), mirroring 0011's tasks_code_seq
-- -> `J-####`. The number is what a human quotes on a bank transfer; the uuid `id`
-- is internal FK plumbing and is never rendered.
create sequence if not exists public.invoices_number_seq;

-- --- Invoices: the issued ledger ---------------------------------------------
create table if not exists public.invoices (
  id           uuid primary key default gen_random_uuid(),   -- internal FK target
  -- The PUBLIC id every route addresses (INV-####); never a UUID.
  number       text not null unique
                 default ('INV-' || lpad(nextval('public.invoices_number_seq')::text, 4, '0')),
  -- NOT NULL + RESTRICT: an invoice always has a payer, and the paper trail
  -- outlives the client record (see the header). client_name is a display SNAPSHOT
  -- so client_id never leaks onto the wire.
  client_id    uuid not null references public.clients (id) on delete restrict,
  client_name  text not null default '',
  status       public.invoice_status not null default 'draft',
  kind         public.invoice_kind not null default 'retainer',
  currency     text not null default 'USD',
  issue_date   date,
  due_date     date,
  -- The service window this invoice bills for (a retainer's month).
  period_start date,
  period_end   date,
  subtotal     numeric(12,2) not null default 0,   -- = sum(line_items.line_total)
  tax          numeric(12,2) not null default 0,
  -- SERVER-COMPUTED = subtotal + tax. A client-supplied total is never trusted:
  -- the API has no `total` input field at all (see schemas.InvoiceCreate).
  total        numeric(12,2) not null default 0,
  notes        text not null default '',
  paid_at      timestamptz,
  -- Free text - how a human recorded the money arriving. NOT a gateway enum;
  -- there is no payment provider in v1.
  paid_method  text not null default '',
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists invoices_client_id_idx on public.invoices (client_id);
create index if not exists invoices_status_idx    on public.invoices (status);
create index if not exists invoices_due_date_idx  on public.invoices (due_date);

create trigger invoices_set_updated_at
  before update on public.invoices
  for each row execute function public.set_updated_at();

-- --- Line items ---------------------------------------------------------------
create table if not exists public.invoice_line_items (
  id          uuid primary key default gen_random_uuid(),
  -- CASCADE (unlike invoices.client_id): a line item has no meaning without its
  -- invoice, and deleting an invoice is already gated by the guard + RLS.
  invoice_id  uuid not null references public.invoices (id) on delete cascade,
  description text not null default '',
  quantity    numeric(12,2) not null default 1,
  unit_amount numeric(12,2) not null default 0,
  -- SERVER-COMPUTED = quantity x unit_amount (never taken from the request).
  line_total  numeric(12,2) not null default 0,
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now()
);

create index if not exists invoice_line_items_invoice_id_idx
  on public.invoice_line_items (invoice_id);

-- --- DB-level invoice state machine + the finalize freeze ---------------------
-- SECURITY DEFINER + empty search_path (schema-qualified everywhere) so it cannot
-- be tricked by a caller's search_path and never recurses. NOTE service_role does
-- NOT bypass triggers, so the nightly past-due sweep is guarded by this too - and
-- `open -> past_due` is legal, so it passes.
--
-- The legal transitions:
--     draft    -> open | void
--     open     -> paid | past_due | void
--     past_due -> paid | void
--     paid     -> refunded
--     void, refunded -> TERMINAL (nothing may leave them)
--
-- The FREEZE: once an invoice leaves `draft` it is issued - a real document a client
-- has seen. Its amounts, dates, payer and notes become immutable; only `status` and
-- the `paid_*` stamps may move (plus `updated_at`, which the set_updated_at trigger
-- stamps). Correcting an issued invoice means voiding it and issuing a new one -
-- that is the whole point of an auditable ledger.
create or replace function public.invoices_guard_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- (1) Identity is immutable forever: the number is the public id a client quotes
  -- on a payment, and re-pointing it at another row would rewrite history.
  if new.id is distinct from old.id
     or new.number is distinct from old.number
     or new.created_at is distinct from old.created_at
  then
    raise exception 'invoice id / number / created_at are immutable';
  end if;

  -- (2) The state machine.
  --
  -- An UNCHANGED status falls straight through, deliberately: that is how an
  -- ordinary draft edit (a PATCH that touches notes/tax and never mentions status)
  -- reaches the freeze check below. It also means the DB permits a no-op
  -- `set status = <the same status>` write, which changes nothing by definition.
  --
  -- So "you cannot finalize an already-open invoice" is an APP-layer rule (the
  -- router's can_transition + its 409), NOT a database one - the DB only refuses
  -- transitions that would actually MOVE an invoice somewhere illegal. The two
  -- agree on every real edge and differ only on the diagonal; service.py's
  -- LEGAL_TRANSITIONS documents the same split from the other side.
  if new.status is distinct from old.status then
    if not (
      (old.status = 'draft'::public.invoice_status
        and new.status in ('open'::public.invoice_status, 'void'::public.invoice_status))
      or (old.status = 'open'::public.invoice_status
        and new.status in ('paid'::public.invoice_status,
                           'past_due'::public.invoice_status,
                           'void'::public.invoice_status))
      or (old.status = 'past_due'::public.invoice_status
        and new.status in ('paid'::public.invoice_status, 'void'::public.invoice_status))
      or (old.status = 'paid'::public.invoice_status
        and new.status = 'refunded'::public.invoice_status)
    ) then
      raise exception 'illegal invoice status transition % -> %', old.status, new.status;
    end if;
  end if;

  -- (3) The finalize freeze: outside `draft`, only status + the paid_* stamps move.
  if old.status <> 'draft'::public.invoice_status then
    if new.client_id    is distinct from old.client_id
       or new.client_name  is distinct from old.client_name
       or new.kind         is distinct from old.kind
       or new.currency     is distinct from old.currency
       or new.issue_date   is distinct from old.issue_date
       or new.due_date     is distinct from old.due_date
       or new.period_start is distinct from old.period_start
       or new.period_end   is distinct from old.period_end
       or new.subtotal     is distinct from old.subtotal
       or new.tax          is distinct from old.tax
       or new.total        is distinct from old.total
       or new.notes        is distinct from old.notes
       or new.created_by   is distinct from old.created_by
    then
      raise exception
        'invoice % is % - its amounts, dates and payer are frozen; only status and '
        'the paid_* stamps may change', old.number, old.status;
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists invoices_guard_update_trg on public.invoices;
create trigger invoices_guard_update_trg
  before update on public.invoices
  for each row execute function public.invoices_guard_update();

-- The OTHER half of the freeze. `invoices_guard_update` can only see the invoices
-- row, so on its own it would leave a hole the size of the whole billed amount:
-- the line items live in a DIFFERENT table, and inserting/editing/deleting a line
-- on an issued invoice would change what was billed without ever updating
-- `invoices`. This guard closes that: lines are writable ONLY while the parent is a
-- draft.
create or replace function public.invoice_line_items_guard()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_status public.invoice_status;
begin
  -- The row being vacated (UPDATE moving a line off an invoice, or a DELETE).
  if tg_op in ('UPDATE', 'DELETE') then
    select status into v_status from public.invoices where id = old.invoice_id;
    -- No parent row found: this is the ON DELETE CASCADE from invoices (Postgres
    -- removes the parent first, THEN cascades), so there is nothing left to
    -- protect and the delete is allowed through.
    if found and v_status <> 'draft'::public.invoice_status then
      raise exception 'invoice line items are frozen once the invoice leaves draft (is %)',
        v_status;
    end if;
  end if;

  -- The row being written to (INSERT, or an UPDATE's destination invoice).
  if tg_op in ('INSERT', 'UPDATE') then
    select status into v_status from public.invoices where id = new.invoice_id;
    if found and v_status <> 'draft'::public.invoice_status then
      raise exception 'invoice line items are frozen once the invoice leaves draft (is %)',
        v_status;
    end if;
  end if;

  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;

drop trigger if exists invoice_line_items_guard_trg on public.invoice_line_items;
create trigger invoice_line_items_guard_trg
  before insert or update or delete on public.invoice_line_items
  for each row execute function public.invoice_line_items_guard();

-- --- RLS ---------------------------------------------------------------------
-- Any staff may READ; only OWNER/ADMIN may write. Billing is finance-sensitive, so
-- unlike every other module the LEADS set (owner/admin/manager) is deliberately NOT
-- used here - a manager may run delivery but may not issue or settle money. Clients
-- are excluded by is_staff() and get no policy at all. The DELETE policy exists for
-- an owner's deliberate cleanup of a mistaken DRAFT; the router publishes no delete
-- route (an issued invoice is voided, never erased).
alter table public.invoices enable row level security;
alter table public.invoices force row level security;
alter table public.invoice_line_items enable row level security;
alter table public.invoice_line_items force row level security;

create policy invoices_select on public.invoices
  for select using (public.is_staff());
create policy invoices_insert on public.invoices
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy invoices_update on public.invoices
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
create policy invoices_delete on public.invoices
  for delete using (public.current_app_role() in ('owner', 'admin'));

create policy invoice_line_items_select on public.invoice_line_items
  for select using (public.is_staff());
create policy invoice_line_items_insert on public.invoice_line_items
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy invoice_line_items_update on public.invoice_line_items
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
create policy invoice_line_items_delete on public.invoice_line_items
  for delete using (public.current_app_role() in ('owner', 'admin'));
