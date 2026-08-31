-- 0111_directory_specs.sql - the EARNED spec whitelist.
--
-- WHY. `FORM_SPECS` in backend/integrations/citation_bot.py is a dict of 50 directories
-- the bot is willing to drive. Its own module docstring says every selector in it is a
-- best-effort guess, never hand-verified against a live DOM. Probed on 2026-08-23: 29 of
-- the 50 URLs return 403, 8 return 404, 6 hosts are dead, 7 answer. None has ever
-- produced a proven live listing.
--
-- So the dict is a COVERAGE CLAIM, and every number downstream inherits it - the gap
-- analysis counts those directories as addressable, a campaign queues them, the client
-- report promises them, the cost model prices them. This table makes coverage a FACT
-- instead: a directory reaches the automated route only when (a) a human opened the live
-- form and diffed every selector against the real DOM, signed and dated, and (b) one
-- submission using that exact spec produced a PUBLIC LISTING URL - not a screenshot, not
-- a 200, a URL a stranger can open. Route B therefore starts at ZERO and grows one dated
-- verification at a time.
--
-- ---------------------------------------------------------------------------------
-- THE RULES LIVE IN THE SCHEMA, NOT IN PYTHON, AND HERE IS WHY THAT IS LOAD-BEARING.
-- The Celery worker connects as `service_role`, which is BYPASSRLS - so the policies at
-- the bottom of this file gate the HTTP surface and NOT the worker. CHECK constraints and
-- triggers are different: `service_role` does not bypass either. Every invariant that
-- actually matters is therefore written as a CHECK or a trigger, so it binds the operator
-- over HTTP and the background worker equally.
--
-- ---------------------------------------------------------------------------------
-- FOUR ATTACKS THIS SCHEMA IS SHAPED TO DEFEAT. An adversarial review of the first draft
-- found each of these; they are recorded because the fix only makes sense next to them.
--
-- 1. SSRF THROUGH `spec->>'url'`. That value is a browser navigation target:
--    citation_bot passes it to `page.goto()`, then types spec-controlled text into
--    spec-controlled selectors, submits, and stores a SCREENSHOT of the result which a
--    staff route will serve back. Validating it `like 'https://%'` stops nothing -
--    `https://169.254.169.254/latest/meta-data/` passes. A lead could turn an
--    authenticated headless browser inside our own network into a screenshot-returning
--    request forgery. The fix is `_spec_url_matches_directory`: the spec's host must BE
--    the catalogue row's host, or a subdomain of it. A spec for Brownbook can only ever
--    point at brownbook.net, so there is no URL to smuggle.
--
-- 2. EDIT-WHILE-INACTIVE LAUNDERING. The obvious guard ("editing selectors voids the
--    verification") is defeated by three ordinary updates a manager may already make:
--    deactivate, edit the spec, reactivate - because the guard only fires while the row
--    is active. So `spec` is IMMUTABLE after insert, full stop. A revision is a NEW ROW,
--    which is also what makes the history of a directory's forms readable.
--
-- 3. A WHITELIST THAT CAN NEVER HAVE A MEMBER. Gating the loader on
--    `directories.route = 'B'` looks right and is fatal: measured on this catalogue,
--    route B holds ZERO rows and no code path sets it. Activation therefore SETS
--    route='B' in the same transaction rather than requiring it beforehand - the
--    activation IS the evidence that the row earned route B.
--
-- 4. A CHARGED NON-ATTEMPT. If the bot stops falling back to FORM_SPECS before the worker
--    learns to resolve a spec first, `execute_citation_submit` runs the cost gate, marks
--    the row `submitting`, and only then discovers there is no spec - so the client is
--    charged for a submission that could not physically happen. The worker must resolve
--    the spec BEFORE the gate. Noted here because the schema is only half the fix.

create table if not exists public.directory_specs (
  id           uuid primary key default gen_random_uuid(),
  -- CASCADE, not RESTRICT: a spec is OUR description of somebody else's form, not a
  -- third-party asset that outlives us. If the catalogue row goes, the description of
  -- its form is meaningless.
  directory_id uuid not null references public.directories (id) on delete cascade,

  -- The serialised FormSpec: {"url", "fields":[{"selector","value_key"}...],
  -- "submit_selector", "success_indicator", "captcha": {...}|null}. IMMUTABLE after
  -- insert (attack 2). `directory_name` is deliberately NOT stored - directory_id is the
  -- identity, and a duplicated name is a second thing to keep in step.
  spec         jsonb not null,

  -- (a) the dated human live-DOM verification.
  -- `verified_by` is ON DELETE SET NULL and there is deliberately NO check pairing it
  -- with `verified_at`: a staff member leaving must not retroactively void a real
  -- verification, nor make their own user row undeletable.
  verified_at       timestamptz,
  verified_by       uuid references public.users (id) on delete set null,
  -- What the human actually SAW, so a verification is auditable rather than a click:
  -- {"checked_at":…, "selectors":[{"selector":…, "found":true}…], "notes":…}
  verified_evidence jsonb not null default '{}',

  -- (b) proof this exact spec produced a real listing. A PUBLIC URL only, never a
  -- screenshot key - 0106 split live_url from proof_url for this same reason.
  first_live_url text not null default '',
  first_live_at  timestamptz,

  last_success_at timestamptz,
  last_attempt_at timestamptz,
  success_count   integer not null default 0,
  failure_count   integer not null default 0,

  -- Drift: set when a submit fails because a selector is GONE - the spec no longer
  -- describes the live form. Recording which selector vanished turns "submit failed"
  -- into a two-minute repair.
  drift_detected_at timestamptz,
  drift_selector    text not null default '',
  drift_evidence    jsonb not null default '{}',

  active             boolean not null default false,
  -- Why it is not active, so a zero-coverage directory can explain itself in the client
  -- report rather than just being absent.
  deactivated_reason text not null default '',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- THE RULE. `active` is impossible without BOTH halves of the contract. This single
  -- constraint is what converts a coverage claim into a coverage fact.
  constraint directory_specs_active_is_earned
    check (not active or (verified_at is not null and first_live_url <> '')),

  -- Drift and activity are contradictory states; the database refuses to hold both.
  constraint directory_specs_drift_deactivates
    check (drift_detected_at is null or not active),

  -- The live-URL columns move together: a URL with no date is undated evidence, a date
  -- with no URL is a claim with nothing behind it.
  constraint directory_specs_first_live_pairing
    check ((first_live_url = '') = (first_live_at is null)),

  -- A real absolute http(s) URL, never a filesystem path - the exact defect 0106 fixed
  -- on citations.proof_url, pre-empted here.
  constraint directory_specs_first_live_url_is_a_url
    check (first_live_url = '' or first_live_url ~ '^https?://[^[:space:]]+$'),

  constraint directory_specs_spec_is_an_object
    check (jsonb_typeof(spec) = 'object'
           and spec ? 'url' and spec ? 'fields' and spec ? 'submit_selector'
           and jsonb_typeof(spec -> 'fields') = 'array'),

  constraint directory_specs_deactivated_reason_known
    check (deactivated_reason in (
      '', 'never_verified', 'drift_detected', 'stale_unused',
      'submission_failed', 'operator_disabled', 'terms_changed'))
);

-- At most one ACTIVE spec per directory. Partial, so superseded revisions accumulate as
-- history (attack 2 makes a revision a new row, and this is what keeps that unambiguous).
create unique index if not exists directory_specs_one_active_per_directory
  on public.directory_specs (directory_id) where active;

create index if not exists directory_specs_directory_idx
  on public.directory_specs (directory_id);
-- The loader's own query shape.
create index if not exists directory_specs_active_idx
  on public.directory_specs (directory_id) where active;
-- The staleness sweep: an active spec unused for 90 days.
create index if not exists directory_specs_stale_idx
  on public.directory_specs (last_success_at) where active;

-- --- host binding: the SSRF fix (attack 1) ----------------------------------------
create or replace function public._spec_host_of(u text)
returns text language sql immutable as $$
  -- Lowercased host, port/credentials/leading-www stripped.
  --
  -- Handles BOTH shapes the catalogue holds, which is not cosmetic: `directories.url`
  -- was seeded as a bare domain ("brownbook.net") in 0046 and as a full URL
  -- ("https://www.2findlocal.com/") in 0065/0067. A host extractor that only understood
  -- absolute URLs returned NULL for the 155 bare rows, and the binding check below then
  -- rejected EVERY spec for them - blocking the legitimate case far more thoroughly than
  -- the attack. Measured, not assumed: an insert for Brownbook failed with "no usable
  -- url to bind this spec against" before this was widened.
  --
  -- `www.` is stripped from both sides so a spec at `https://www.brownbook.net/add`
  -- matches a catalogue row of `brownbook.net`. That is not a loosening: `www` is the
  -- same host, and the subdomain rule below still anchors on a dot.
  select nullif(
    regexp_replace(
      lower(regexp_replace(
        regexp_replace(
          coalesce(substring(u from '^https?://([^/?#]+)'), split_part(split_part(u, '/', 1), '?', 1)),
          '^[^@]*@', ''),
        ':[0-9]+$', '')),
      '^www\.', ''),
    '');
$$;

create or replace function public.directory_specs_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  dir_host  text;
  spec_host text;
begin
  if tg_op = 'UPDATE' then
    -- ATTACK 2: `spec` is immutable. A revision is a new row, so a verification can
    -- never be laundered onto selectors it did not cover.
    if new.spec is distinct from old.spec then
      raise exception
        'directory_specs.spec is immutable - insert a new revision instead of editing '
        '(a verification signs the selectors it actually checked)'
        using errcode = 'check_violation';
    end if;
    -- The verification signature is written once, by the verification path.
    if old.verified_at is not null and new.verified_at is distinct from old.verified_at then
      raise exception 'directory_specs.verified_at cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
    -- Proof of a first live listing is likewise write-once.
    if old.first_live_url <> '' and new.first_live_url is distinct from old.first_live_url then
      raise exception 'directory_specs.first_live_url cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
  end if;

  -- ATTACK 1: the spec may only navigate to its OWN directory's host.
  spec_host := public._spec_host_of(new.spec ->> 'url');
  if spec_host is null then
    raise exception 'directory_specs.spec->>url must be an absolute http(s) URL'
      using errcode = 'check_violation';
  end if;
  select public._spec_host_of(d.url) into dir_host
    from public.directories d where d.id = new.directory_id;
  if dir_host is null then
    raise exception 'directory % has no usable url to bind this spec against',
      new.directory_id using errcode = 'check_violation';
  end if;
  -- Equal, or a subdomain of it. Anchored on a leading dot so "evil-brownbook.net"
  -- cannot pass as a subdomain of "brownbook.net".
  if spec_host <> dir_host and spec_host not like ('%.' || dir_host) then
    raise exception
      'spec url host (%) must belong to the directory host (%) - a spec is not a free '
      'navigation target', spec_host, dir_host using errcode = 'check_violation';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists directory_specs_guard_trg on public.directory_specs;
create trigger directory_specs_guard_trg
  before insert or update on public.directory_specs
  for each row execute function public.directory_specs_guard();

alter table public.directory_specs enable row level security;
alter table public.directory_specs force row level security;

-- Dropped first so re-applying this file is a no-op: `create policy` has no
-- IF NOT EXISTS, and a migration that cannot be re-run is a migration that fails the
-- from-zero rebuild check the moment anything replays it (0080 does the same).
drop policy if exists directory_specs_select on public.directory_specs;
create policy directory_specs_select on public.directory_specs
  for select using (public.is_staff());
drop policy if exists directory_specs_insert on public.directory_specs;
create policy directory_specs_insert on public.directory_specs
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
drop policy if exists directory_specs_update on public.directory_specs;
create policy directory_specs_update on public.directory_specs
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

drop trigger if exists directory_specs_set_updated_at on public.directory_specs;
create trigger directory_specs_set_updated_at
  before update on public.directory_specs
  for each row execute function public.set_updated_at();
