-- 0120 · A campaign is a THING, not a response body that evaporates.
--
-- 2026-09-01, measured: an operator pressed "Queue campaign", the API inserted 45
-- citation rows, refused every one of them within 0.9 seconds (43 no_verified_spec,
-- 1 no_engine, 1 price_unknown), returned 201 "queued 45 directories" — and then the
-- batch CEASED TO EXIST as a unit. No id to poll, no rollup to render, the skip
-- ledger discarded with the HTTP response. The operator's only view was a 50-row
-- global table where the 45 might not even appear. "Nothing came back" was the
-- literal truth.
--
-- This table is the campaign's identity: who it was for, who queued it, what was
-- asked vs what was actually queued, the estimate a lead saw, and the full skip
-- ledger (the "45 promised, 43 skipped, here is why" answer, persisted). Per-row
-- truth stays on `citations` — one row, one story (0045's rule); `campaign_id` merely
-- groups them, and the rollup endpoint computes live from the rows so the two can
-- never disagree.
--
-- Additive + idempotent. New table -> RLS below keeps app/db/rls_check.py green.

create table if not exists public.citation_campaigns (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references public.clients (id) on delete cascade,
  -- Snapshotted display name, same rule as citations.client_name: responses carry
  -- the name, never the internal id.
  client_name    text not null default '',
  created_by     uuid references public.users (id) on delete set null,
  created_at     timestamptz not null default now(),
  -- The selection size BEFORE dedupe against existing rows; `queued` is what was
  -- actually inserted/requeued. The difference is "already in flight".
  requested      int not null default 0,
  queued         int not null default 0,
  estimated_cost numeric(10, 4) not null default 0,
  -- What the operator asked for (markets/tiers/cap/vertical/directoryIds) — the
  -- reproducibility record, not a source of truth for any row.
  params         jsonb not null default '{}'::jsonb,
  -- [{directory, reason, detail}]: every catalog row NOT queued, and why. This used
  -- to live only in the HTTP response.
  skipped        jsonb not null default '[]'::jsonb
);

alter table public.citation_campaigns enable row level security;
alter table public.citation_campaigns force row level security;

-- Staff read; leads write. No client policy at all — a portal client never sees the
-- machinery, only the outcomes surfaced through their own views.
create policy citation_campaigns_read on public.citation_campaigns
  for select using (public.is_staff());
create policy citation_campaigns_insert on public.citation_campaigns
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- The grouping edge. `on delete set null`: deleting a campaign record must never
-- delete the listings it queued — the citation row remains the durable truth.
alter table public.citations
  add column if not exists campaign_id uuid
    references public.citation_campaigns (id) on delete set null;

create index if not exists citations_campaign_idx
  on public.citations (campaign_id)
  where campaign_id is not null;

create index if not exists citation_campaigns_client_idx
  on public.citation_campaigns (client_id, created_at desc);

comment on table public.citation_campaigns is
  'One "Queue campaign" press (0120): who/when/what-was-asked, the estimate shown, '
  'and the persisted skip ledger. Per-row truth lives on citations.campaign_id — '
  'rollups are computed from the rows so the two cannot disagree.';
