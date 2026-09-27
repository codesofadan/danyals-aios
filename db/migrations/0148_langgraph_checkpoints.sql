-- 0148_langgraph_checkpoints.sql - durable graph state for the LangGraph runtime
-- (06-AI-STACK.md §1/§2: "checkpointed to the same Postgres", "in the same schema
-- family as jobs").
--
-- WHY THIS IS A MIGRATION AND NOT `PostgresSaver.setup()`.
-- LangGraph ships its own DDL and expects the application to run it at startup. That
-- cannot work here, and the way it fails is the reason this file exists: `setup()`
-- issues CREATE TABLE, and NEITHER runtime role may create a table in `public`.
-- `0000_local_platform.sql:45` grants only USAGE on the schema to `anon`,
-- `authenticated` and `service_role` - DDL belongs to the migration runner, which is
-- the whole point of having ordered migrations.
--
-- So `setup()` raised `InsufficientPrivilege: permission denied for schema public`, the
-- runtime caught it, fell back to an in-memory saver, and logged a warning. Everything
-- kept working. Nothing could resume. A deployment would have believed it had durable
-- graph state right up to the first worker restart that needed it - which is to say,
-- until the exact moment the feature was supposed to earn its place.
--
-- THE SEED IS LOAD-BEARING. `setup()` reads `max(v)` from `checkpoint_migrations` and
-- runs only the migrations after it. Seeding v=0..9 (LangGraph 1.2's full set) makes
-- `setup()` a no-op: it creates nothing, alters nothing, and needs no privilege it does
-- not have. `tests/test_langgraph_checkpoint_schema.py` asserts this seed still covers
-- `len(PostgresSaver.MIGRATIONS)`, so a LangGraph upgrade that adds DDL FAILS THE GATE
-- and asks for the next migration rather than failing silently in production.
--
-- RLS. These four tables are INFRASTRUCTURE, like the job ledger - they hold graph
-- execution state, carry no `client_id`, and have exactly one writer: `service_role`,
-- which is BYPASSRLS. So they are ENABLE + FORCE with NO POLICY AT ALL, which is a
-- default-deny for `authenticated`: a leaked portal or staff DB credential reads
-- nothing here. That satisfies invariant #10 and the `app/db/rls_check.py` gate, which
-- requires enabled+forced on every base table in `public`.
--
-- A NOTE ON WHAT LANDS IN `checkpoints.checkpoint`. Graph state includes drafted article
-- bodies. That is client content at rest in our own database, under the same RLS posture
-- as the rest of the platform - it is NOT sent anywhere, and `langsmith_redact_content`
-- (default true) governs the separate question of what reaches a trace store.

begin;

-- LangGraph's own schema, byte-for-byte what `PostgresSaver.MIGRATIONS` creates. Kept
-- verbatim rather than "improved": the library's SELECTs name these columns, and a
-- helpfully-renamed column or an added NOT NULL is a runtime failure at read time.
create table if not exists public.checkpoint_migrations (
  v integer primary key
);

create table if not exists public.checkpoints (
  thread_id            text not null,
  checkpoint_ns        text not null default '',
  checkpoint_id        text not null,
  parent_checkpoint_id text,
  type                 text,
  checkpoint           jsonb not null,
  metadata             jsonb not null default '{}',
  primary key (thread_id, checkpoint_ns, checkpoint_id)
);

create table if not exists public.checkpoint_blobs (
  thread_id     text not null,
  checkpoint_ns text not null default '',
  channel       text not null,
  version       text not null,
  type          text not null,
  blob          bytea,
  primary key (thread_id, checkpoint_ns, channel, version)
);

create table if not exists public.checkpoint_writes (
  thread_id     text not null,
  checkpoint_ns text not null default '',
  checkpoint_id text not null,
  task_id       text not null,
  idx           integer not null,
  channel       text not null,
  type          text,
  blob          bytea not null,
  task_path     text not null default '',
  primary key (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- LangGraph creates these CONCURRENTLY (it runs outside a transaction). Inside a
-- migration transaction the plain form is correct and cheaper - the tables are empty.
create index if not exists checkpoints_thread_id_idx        on public.checkpoints (thread_id);
create index if not exists checkpoint_blobs_thread_id_idx   on public.checkpoint_blobs (thread_id);
create index if not exists checkpoint_writes_thread_id_idx  on public.checkpoint_writes (thread_id);

-- Mark LangGraph 1.2's migrations 0..9 as applied, so `setup()` finds nothing to do.
insert into public.checkpoint_migrations (v)
select generate_series(0, 9)
on conflict (v) do nothing;

-- The runtime roles need DML (0000's default privileges cover future tables, but these
-- are created here and now, so grant explicitly rather than rely on ordering).
grant select, insert, update, delete on
  public.checkpoint_migrations,
  public.checkpoints,
  public.checkpoint_blobs,
  public.checkpoint_writes
to service_role;

-- --- RLS: enabled + FORCED, and deliberately NO policy (default deny). ------------
alter table public.checkpoint_migrations enable row level security;
alter table public.checkpoint_migrations force row level security;
alter table public.checkpoints           enable row level security;
alter table public.checkpoints           force row level security;
alter table public.checkpoint_blobs      enable row level security;
alter table public.checkpoint_blobs      force row level security;
alter table public.checkpoint_writes     enable row level security;
alter table public.checkpoint_writes     force row level security;

comment on table public.checkpoints is
  'LangGraph durable graph state (06-AI-STACK.md §2). Infrastructure, not tenant data: '
  'written only by service_role (BYPASSRLS); ENABLE+FORCE RLS with no policy means '
  'authenticated is default-denied. DDL is owned by this migration, never by '
  'PostgresSaver.setup() - neither runtime role may CREATE in schema public.';

commit;
