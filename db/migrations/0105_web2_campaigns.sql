-- 0105_web2_campaigns.sql - the CAMPAIGN: one operator action, many properties.
--
-- WHAT WAS MISSING. Everything below this table already worked - 53 publisher clients, a
-- grounded article generator, a similarity gate, pacing - but there was no way to ask for
-- WORK. A property was one API call, so "thirty blog posts for this client" meant thirty
-- separate requests with no shared budget, no shared schedule, no shared approval, and
-- nothing that could answer "how is that job going?". This table is that missing noun.
--
-- WHY A ROW AND NOT JUST A TAG ON THE PROPERTIES. Three facts belong to the campaign and
-- to nothing else, and each of them is a real defect in its absence:
--   * a COST CEILING. Thirty properties is thirty metered Claude drafting runs. The
--     per-call gate cannot see the batch, so without a campaign-level ceiling the only
--     protection against a mistyped "300" is the client's monthly budget.
--   * a PACING ANCHOR. The schedule is a property of the set: each slot depends on the
--     ones already placed, so the layout has to be owned somewhere.
--   * an HONEST STATUS. `degraded` exists here for the same reason the content
--     dispatcher has it: a campaign where some properties were claimed and never
--     published is NOT complete, and reporting it complete is the exact defect P0-4
--     removed elsewhere in this codebase.
--
-- SCALE IS THE OPERATOR'S CHOICE; SAFETY IS NOT. `platforms` records whatever subset was
-- selected and `pacing` records how aggressively to publish. What the operator cannot
-- opt out of is the unique-article rule, the similarity gate, anchor variation, or the
-- pacing caps - those run whatever the campaign asks for.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_campaign_status') then
    --   draft         - being configured; nothing queued, nothing spent.
    --   planning      - properties created, the write workers are drafting.
    --   needs_approval- every draft has settled; waiting on ONE operator decision.
    --   scheduled     - approved; properties are waiting for their pacing slots.
    --   running       - at least one property has published, others still due.
    --   completed     - EVERY property published. Nothing else earns this label.
    --   degraded      - finished, but not everything went out (see the header).
    --   cancelled     - stopped by an operator; remaining properties never publish.
    create type public.web2_campaign_status as enum (
      'draft', 'planning', 'needs_approval', 'scheduled', 'running',
      'completed', 'degraded', 'cancelled'
    );
  end if;
end $$;

do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_pacing_mode') then
    --   immediate - pack the schedule as tightly as the caps allow. NOT "all at once":
    --               the caps still apply, and the operator is shown the real completion
    --               date before committing rather than discovering it afterwards.
    --   drip      - spread deliberately across a chosen window.
    create type public.web2_pacing_mode as enum ('immediate', 'drip');
  end if;
end $$;

create table if not exists public.web2_campaigns (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references public.clients (id) on delete cascade,
  -- Display SNAPSHOT, so a campaign can be listed without ever surfacing client_id -
  -- the same discipline every other client-facing table in this schema uses.
  client_name    text not null default '',
  title          text not null default '',

  -- What was asked for. `article_count` is the operator's request; the planner may
  -- create fewer properties (the per-client campaign cap), and the difference is
  -- exactly the kind of thing the UI must show rather than quietly absorb.
  article_count  int not null check (article_count > 0),
  -- The selected subset, as publishing-enum names. text[] rather than an enum array so
  -- a platform later removed from the enum does not break historic campaign rows.
  platforms      text[] not null default '{}',
  pacing         public.web2_pacing_mode not null default 'drip',
  drip_window_days int not null default 30 check (drip_window_days >= 0),
  target_url     text not null default '',

  status         public.web2_campaign_status not null default 'draft',
  -- The batch ceiling the per-call cost gate cannot see. 0 = no campaign ceiling (the
  -- client budget and the money-dial still apply).
  cost_ceiling_usd numeric(10, 4) not null default 0,
  spent_usd        numeric(10, 4) not null default 0,

  approved_by    uuid references public.users (id) on delete set null,
  approved_at    timestamptz,
  -- When the self-rescheduling release tick should next look at this campaign.
  next_tick_at   timestamptz,
  created_by     uuid references public.users (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists web2_campaigns_client_id_idx on public.web2_campaigns (client_id);
create index if not exists web2_campaigns_status_idx on public.web2_campaigns (status);
-- The scheduler's claim query: campaigns with work due. Partial, because the vast
-- majority of rows are finished and should never be scanned.
create index if not exists web2_campaigns_next_tick_idx
  on public.web2_campaigns (next_tick_at)
  where next_tick_at is not null and status in ('scheduled', 'running');

create trigger web2_campaigns_set_updated_at
  before update on public.web2_campaigns
  for each row execute function public.set_updated_at();

alter table public.web2_campaigns enable row level security;
alter table public.web2_campaigns force row level security;

create policy web2_campaigns_select on public.web2_campaigns
  for select using (public.is_staff());
create policy web2_campaigns_insert on public.web2_campaigns
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy web2_campaigns_update on public.web2_campaigns
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

comment on table public.web2_campaigns is
  'One operator request for N Web 2.0 properties: the selected platform subset, the '
  'pacing choice, the batch cost ceiling, and an honest status (a campaign that did '
  'not publish everything is degraded, never completed).';

-- --- The link from property to campaign -------------------------------------------
-- ON DELETE SET NULL, not CASCADE: deleting a campaign record must never delete the
-- ledger of what was actually published under a client's name. The properties outlive
-- the request that created them.
alter table public.web2_properties
  add column if not exists campaign_id uuid references public.web2_campaigns (id) on delete set null;

create index if not exists web2_properties_campaign_id_idx
  on public.web2_properties (campaign_id) where campaign_id is not null;

comment on column public.web2_properties.campaign_id is
  'The campaign that requested this property, if any. SET NULL on campaign delete - the '
  'published article outlives the request.';
