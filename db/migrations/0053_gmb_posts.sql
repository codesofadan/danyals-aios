-- 0053_gmb_posts.sql - Wave 5 (GMB / Google Business Profile posts): the AI-drafted,
-- policy-checked GBP post ledger with a human review gate.
--
-- Scope: a lead prompts the AI to draft a Google Business Profile post; the draft is
-- dash-stripped + GBP-policy-scored + stored at the review gate; a lead approves or
-- rejects. ACTUAL posting to Google is DORMANT (the OAuth publish path is unwired) - a
-- post never leaves 'approved' here; 'posted' is defined for when publishing lands.
--
-- Cost dial: generation is metered on the 'gmb' money-dial (a new DialFeatureMeta in
-- app/schemas/cost.py is required for ops to switch it on; until then dial_mode('gmb')
-- resolves to 'off' and generation degrades honestly).
--
-- RLS mirrors 0039_local_seo: staff read (is_staff), leads write (owner/admin/manager),
-- ENABLE + FORCE (the CI RLS gate fails otherwise). No client base-table policy, so a
-- portal client can never read the surface.

-- --- the public code sequence (GMB-####, never a UUID on the wire) --------------
create sequence if not exists public.gmb_posts_code_seq;

-- --- enums (new types used in-migration is safe; only ADDING a value to an existing
--     enum in the same txn is forbidden - 55P04) ---------------------------------
do $$ begin
  create type public.gmb_post_type as enum ('update', 'offer', 'event', 'product');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.gmb_post_status as enum ('draft', 'needs_review', 'approved', 'posted', 'rejected');
exception when duplicate_object then null; end $$;

-- --- the GBP post ledger --------------------------------------------------------
create table if not exists public.gmb_posts (
  id           uuid primary key default gen_random_uuid(),
  code         text not null unique
               default ('GMB-' || to_char(nextval('public.gmb_posts_code_seq'), 'FM0000')),
  client_id    uuid not null references public.clients (id) on delete cascade,
  client_name  text not null default '',
  color        text not null default '',
  topic        text not null,
  post_type    public.gmb_post_type not null default 'update',
  cta_type     text not null default 'learn_more'
               check (cta_type in ('book', 'order', 'shop', 'learn_more', 'sign_up', 'call', 'none')),
  cta_url      text not null default '',
  title        text not null default '',
  body         text not null default '',
  char_count   integer not null default 0,
  status       public.gmb_post_status not null default 'draft',
  policy       jsonb not null default '{}',
  cost         numeric(10,2) not null default 0,
  provider     text not null default '',
  stage        text not null default '',
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists gmb_posts_client_id_idx on public.gmb_posts (client_id);
create index if not exists gmb_posts_status_idx on public.gmb_posts (status, created_at desc);

create trigger gmb_posts_set_updated_at
  before update on public.gmb_posts
  for each row execute function public.set_updated_at();

-- --- RLS ------------------------------------------------------------------------
alter table public.gmb_posts enable row level security;
alter table public.gmb_posts force row level security;

create policy gmb_posts_select on public.gmb_posts
  for select using (public.is_staff());
create policy gmb_posts_insert on public.gmb_posts
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy gmb_posts_update on public.gmb_posts
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
