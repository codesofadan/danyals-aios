-- 0014_entity_context.sql - the CANONICAL CONTEXT STORE + Pinecone ledger (P6B-2).
--
-- Postgres = source of truth; Pinecone = a DERIVED index, fully reconstructable
-- from context_vectors. Two tables:
--
--   entity_context  - ONE living-context row per (entity_type, entity_id): the
--     bounded LLM `summary` prose + structured `facts jsonb` (folded
--     last-writer-wins by seq -> provable supersession) + `event_watermark`
--     (the highest activity.seq folded in; the freshness invariant keys off it).
--   context_vectors - the append/GC LEDGER of what is embedded in Pinecone: one
--     row per (entity, chunk_key) with the pinecone_id, content_checksum, version
--     and dim/model, so staleness/GC + the Pinecone<->Postgres consistency check
--     are pure Postgres reads.
--
-- THE THREAT MODEL (mirrors 0010/0011/0013): any authenticated principal could
-- query the data plane DIRECTLY as role `authenticated`, so RLS - not the FastAPI
-- responses - is the boundary. Both tables ENABLE + FORCE RLS with a staff-only
-- SELECT policy and NO write policy: the compaction worker (P6B-7) writes via
-- service_role (BYPASSRLS), and a portal client reads ONLY its own client-level
-- summary+facts through the portal_context SECURITY-BARRIER VIEW (mirrors 0010's
-- portal_* views) - never the base tables, never the vectors, never a foreign
-- tenant. Idempotent; safe to re-run.

-- --- Status enum (idempotent; enums have no "create ... if not exists") --------
-- pending    : dirtied, not yet compacted.
-- summarized : freshly folded; the invariant event_watermark >= latest_seq holds.
-- degraded   : folded WITHOUT provider keys (raw events appended, watermark HELD
--              so lag stays visible); catches up when keys land.
-- error      : the last compaction attempt failed (surfaced by /context/health).
do $$ begin
  if not exists (select 1 from pg_type where typname = 'context_status') then
    create type public.context_status as enum ('pending', 'summarized', 'degraded', 'error');
  end if;
end $$;

-- --- The canonical living-context row (source of truth) ------------------------
-- unique (entity_type, entity_id): exactly one context per entity; the worker
-- upserts on that key and bumps version/event_watermark/status.
create table if not exists public.entity_context (
  id              uuid primary key default gen_random_uuid(),
  entity_type     public.context_entity not null,
  entity_id       uuid not null,
  summary         text not null default '',
  facts           jsonb not null default '{}'::jsonb,
  token_budget    int  not null default 1200,
  token_count     int  not null default 0,
  version         int  not null default 0,
  event_watermark bigint not null default 0,       -- highest activity.seq folded in
  status          public.context_status not null default 'pending',
  model           text not null default '',
  checksum        text not null default '',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (entity_type, entity_id)
);
create trigger entity_context_set_updated_at
  before update on public.entity_context
  for each row execute function public.set_updated_at();

-- --- The Pinecone vector-sync ledger ------------------------------------------
-- chunk_key is the STABLE per-chunk id ('summary', 'facts:seo', ...); pinecone_id
-- is the id within the entity's namespace. content_checksum (sha256 of the
-- embedded text) drives dedupe + supersession GC. unique (entity, chunk_key) so a
-- chunk maps to at most one live vector.
create table if not exists public.context_vectors (
  id               uuid primary key default gen_random_uuid(),
  entity_type      public.context_entity not null,
  entity_id        uuid not null,
  chunk_key        text not null,
  pinecone_id      text not null,
  content_checksum text not null,
  version          int  not null,
  dim              int  not null,
  model            text not null,
  embedded_at      timestamptz not null default now(),
  unique (entity_type, entity_id, chunk_key)
);
-- Drives "all live vectors for this entity" (reconcile + GC + namespace sweeps).
create index if not exists context_vectors_entity_idx
  on public.context_vectors(entity_type, entity_id);

-- --- RLS: staff read; writes are service_role-only -----------------------------
alter table public.entity_context  enable row level security;
alter table public.entity_context  force  row level security;
alter table public.context_vectors enable row level security;
alter table public.context_vectors force  row level security;
create policy entity_context_select  on public.entity_context
  for select using (public.is_staff());
create policy context_vectors_select on public.context_vectors
  for select using (public.is_staff());              -- writes: compaction worker (service_role)

-- --- Client-facing exposure: a SECURITY-BARRIER VIEW (mirrors 0010 portal_*) ---
-- A portal client reads ONLY its OWN client-level summary+facts+updated_at;
-- never the vectors, never another tenant, never the base table. The view is
-- owned by the migration role (BYPASSRLS) and self-filters by current_client_id(),
-- so a staff caller simply gets zero rows (harmless) and a client cannot widen it.
create or replace view public.portal_context
  with (security_barrier = true) as
  select
    ec.summary,
    ec.facts,
    ec.updated_at
  from public.entity_context ec
  where ec.entity_type = 'client' and ec.entity_id = public.current_client_id();

comment on view public.portal_context is
  'Client-safe view of the caller''s own client-level entity_context (summary/facts/updated_at only), self-filtered to current_client_id(). No vectors, no watermark, no foreign tenant.';

grant select on public.portal_context to authenticated, anon;
