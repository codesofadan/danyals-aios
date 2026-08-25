-- 0093_audit_depth.sql - give an audit run a recorded BREADTH, and record what
-- the operator was told it would cost.
--
-- WHAT WAS MISSING. `audits` recorded which client, which URL, which types and
-- which spend tier - but never how much of the site the run covered. Breadth came
-- from ONE process-wide setting (`audit_max_pages`, default 100) read at run
-- time. Two consequences, both live:
--
--   1. No row says what breadth it ran at. Change the setting and every past
--      row silently re-describes itself; nothing in the ledger disagrees.
--   2. The operator could not ASK for a breadth. The recovery plan (§3.2)
--      specifies four tiers - free lead magnet, Standard, Deep, type-scoped -
--      and the platform served two, because `tier` (free|paid) is a SPEND
--      authorisation and was carrying the weight of a depth choice it cannot
--      express.
--
-- `depth` is that missing axis, and it is deliberately NOT folded into `tier`:
-- one says whether a paid provider may fire at all, the other says how much of
-- the site to look at, and a Standard and a Deep run are both `paid`.
--
-- NO BACKFILL, ON PURPOSE. Every existing row keeps `depth = null`, which reads
-- as *this run predates the depth axis* - a true statement. The alternative is to
-- infer breadth from `tier`, and that inference is not sound: the breadth those
-- runs used came from an env-overridable global whose value AT THE TIME OF EACH
-- RUN is not recoverable from anything in this database. Writing a plausible 15
-- or 100 into a column that reads as measured would put a number nobody measured
-- into the job ledger. A null that means "unknown" is worth more than a figure
-- that means "guessed".
--
-- `estimated_cost` is likewise recorded per row rather than inferred. It is what
-- the pre-flight gate was told - and, for a deep run, the number a human
-- confirmed. Keeping it next to the committed `cost` is what makes an
-- estimate-vs-actual comparison possible at all; today the estimate is a flat
-- constant that leaves no trace, so nobody can tell whether the platform's cost
-- model is any good.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'audit_depth') then
    create type public.audit_depth as enum ('free', 'standard', 'deep');
  end if;
end $$;

alter table public.audits
  -- Nullable WITHOUT a default: see "NO BACKFILL, ON PURPOSE" above. The
  -- application always writes a value on insert, so null can only ever mean
  -- "written before 0084", never "the app forgot".
  add column if not exists depth public.audit_depth,
  -- The breadth actually handed to the engine as --max-pages, snapshotted at
  -- enqueue so a later settings change cannot rewrite what this run did.
  add column if not exists max_pages integer,
  -- The pre-flight estimate in USD. numeric(12,6) matches the precision the cost
  -- ledger moved to in 0083 - an estimate rounded coarser than the bill it is
  -- compared against is not comparable.
  add column if not exists estimated_cost numeric(12, 6),
  -- Set only for a depth that requires confirmation (deep). Its presence is the
  -- durable evidence that a human was shown a number and accepted it, which is
  -- the whole point of "estimated and confirmed before running".
  add column if not exists estimate_confirmed_at timestamptz;

-- A recorded breadth must be a positive page count if it is recorded at all.
-- NOT VALID so the constraint binds every future write without forcing a scan
-- that would fail on the deliberately-null legacy rows.
do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'audits_max_pages_positive'
  ) then
    alter table public.audits
      add constraint audits_max_pages_positive
      check (max_pages is null or max_pages > 0) not valid;
  end if;
end $$;

comment on column public.audits.depth is
  'Crawl breadth tier (free|standard|deep). NULL = row predates migration 0084; '
  'the breadth it ran at came from a process-wide setting and is not recoverable.';
comment on column public.audits.estimated_cost is
  'USD pre-flight estimate shown to the cost gate (and, for deep, to a human). '
  'Compare against `cost`, which is the runtime-derived committed figure.';
