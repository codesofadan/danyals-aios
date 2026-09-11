-- 0136_web2_placement_specs.sql - the EARNED editor-spec whitelist for
-- extension-assisted Web 2.0 placement (off-page redesign Phase 7, plan §7).
--
-- WHAT THIS IS. 0135 classified ~16 catalogue platforms mechanism='extension': no
-- usable public write API, so the OPERATOR publishes there in their own logged-in
-- browser session and the server verifies the pasted public URL. The extension can
-- help - open the editor, offer the approved draft as copy-blocks, and (only where a
-- spec is EARNED) fill plain form fields - but "help" must never rest on a guessed
-- selector or a guessed URL. This table is 0108's discipline applied to editor UIs:
--
--   * a spec is IMMUTABLE after insert (a revision is a new row),
--   * `active` is EARNED - a dated human verification AND one public live URL that
--     this exact spec produced - never asserted,
--   * the spec's editor_url is HOST-PINNED to its platform's own homepage host, so a
--     spec can never become a free navigation target for the operator's browser,
--   * drift deactivates (a spec that no longer matches the live editor is refused,
--     fail-closed to copy-blocks - the same rule the citation filler lives under).
--
-- THE SPEC SHAPE (serialised in `spec` jsonb):
--   {"editor_url": "https://medium.com/new-story",
--    "copy_blocks": [{"key": "title", "label": "Title"}, ...],      -- ordering/labels
--    "fields": [{"selector": "...", "value_key": "title"}, ...],    -- OPTIONAL
--    "success_indicator": "..."}                                    -- OPTIONAL
-- `copy_blocks` names which draft values the panel offers click-to-copy and in what
-- order. `fields` is the optional autofill half: plain selectors only - without an
-- ACTIVE spec carrying fields, the extension falls back to copy-blocks (fail-closed;
-- it NEVER fills contenteditable on a guess and NEVER submits anything, spec or not).
--
-- WHY THE FK IS web2_platforms(id) AND NOT the platform name/enum. The catalogue row
-- is the identity that carries homepage_url (the host the pin binds against),
-- mechanism (only extension-lane rows meaningfully hold a spec) and the terms
-- columns; `name` is merely unique text and the publishing enum does not cover most
-- extension-lane platforms. CASCADE like 0108: a spec is OUR description of somebody
-- else's editor - if the catalogue row goes, the description is meaningless.
--
-- RULES LIVE IN THE SCHEMA (0108's reasoning, verbatim): the worker connects as
-- `service_role`, which is BYPASSRLS - policies gate the HTTP surface only. CHECKs
-- and triggers bind everyone, so every invariant that matters is written as one.
--
-- HOST PINNING reuses public._spec_host_of + public._host_is_ip_literal from 0114
-- rather than growing a sibling: both are URL-generic (nothing directory-specific in
-- them), both sides of this comparison want EXACTLY 0114's refuse-ambiguity
-- semantics (no backslash/whitespace/userinfo/percent/non-ASCII, no IP literals),
-- and a second copy of a security predicate is a second thing to keep right. They
-- are `create or replace`d by 0114, which precedes this file in every ordered apply.
--
-- Additive + idempotent. Text + CHECK closed vocabularies (0106 pattern - never a
-- new Postgres enum). ENABLE+FORCE RLS with the standard staff-read / lead-write
-- shape.

create table if not exists public.web2_placement_specs (
  id          uuid primary key default gen_random_uuid(),
  platform_id uuid not null references public.web2_platforms (id) on delete cascade,

  -- The serialised placement spec (shape in the header). IMMUTABLE after insert.
  spec jsonb not null,

  -- (a) the dated human live-editor verification. Same asymmetry as 0108:
  -- `verified_by` is SET NULL and deliberately unpaired with `verified_at`, so a
  -- staff member leaving neither voids a real verification nor becomes undeletable.
  verified_at       timestamptz,
  verified_by       uuid references public.users (id) on delete set null,
  verified_evidence jsonb not null default '{}',

  -- (b) proof this exact spec produced a real public post. A PUBLIC URL, never a
  -- screenshot key.
  first_live_url text not null default '',
  first_live_at  timestamptz,

  last_success_at timestamptz,
  last_attempt_at timestamptz,
  success_count   integer not null default 0,
  failure_count   integer not null default 0,

  -- Drift: the editor no longer matches what the spec describes (an operator's
  -- form_changed block, or a fill whose selectors vanished). Drift deactivates.
  drift_detected_at timestamptz,
  drift_selector    text not null default '',
  drift_evidence    jsonb not null default '{}',

  active             boolean not null default false,
  deactivated_reason text not null default '',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- THE RULE: active is impossible without both halves of the earned contract.
  constraint web2_placement_specs_active_is_earned
    check (not active or (verified_at is not null and first_live_url <> '')),

  constraint web2_placement_specs_drift_deactivates
    check (drift_detected_at is null or not active),

  constraint web2_placement_specs_first_live_pairing
    check ((first_live_url = '') = (first_live_at is null)),

  constraint web2_placement_specs_first_live_url_is_a_url
    check (first_live_url = '' or first_live_url ~ '^https?://[^[:space:]]+$'),

  -- editor_url + copy_blocks are the mandatory halves; `fields` (autofill) and
  -- `success_indicator` are optional but must be well-typed when present.
  constraint web2_placement_specs_spec_is_an_object
    check (jsonb_typeof(spec) = 'object'
           and spec ? 'editor_url' and spec ? 'copy_blocks'
           and jsonb_typeof(spec -> 'copy_blocks') = 'array'
           and (not (spec ? 'fields') or jsonb_typeof(spec -> 'fields') = 'array')),

  -- 0108/0114's vocabulary, with the one sibling rename: the catalogue-url-change
  -- voider here watches web2_platforms.homepage_url, so its receipt says so.
  constraint web2_placement_specs_deactivated_reason_known
    check (deactivated_reason in (
      '', 'never_verified', 'drift_detected', 'stale_unused',
      'submission_failed', 'operator_disabled', 'terms_changed',
      'platform_url_changed'))
);

-- At most one ACTIVE spec per platform; superseded revisions accumulate as history.
create unique index if not exists web2_placement_specs_one_active_per_platform
  on public.web2_placement_specs (platform_id) where active;

create index if not exists web2_placement_specs_platform_idx
  on public.web2_placement_specs (platform_id);
create index if not exists web2_placement_specs_active_idx
  on public.web2_placement_specs (platform_id) where active;
create index if not exists web2_placement_specs_stale_idx
  on public.web2_placement_specs (last_success_at) where active;

-- --- the guard: immutability + earned writes + host pinning ---------------------
create or replace function public.web2_placement_specs_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  platform_host text;
  spec_host     text;
begin
  if tg_op = 'UPDATE' then
    -- Immutable after insert: a verification signs the exact editor URL, selectors
    -- and copy-blocks it actually covered. A revision is a NEW ROW (0108 attack 2).
    if new.spec is distinct from old.spec then
      raise exception
        'web2_placement_specs.spec is immutable - insert a new revision instead of '
        'editing (a verification signs the spec it actually checked)'
        using errcode = 'check_violation';
    end if;
    -- A verification is earned on ONE platform (0114's rule): moving the row would
    -- serve a spec on a platform that never earned it.
    if new.platform_id is distinct from old.platform_id then
      raise exception
        'web2_placement_specs.platform_id is immutable - a verification is earned on '
        'one platform and cannot be moved to another'
        using errcode = 'check_violation';
    end if;
    if old.verified_at is not null and new.verified_at is distinct from old.verified_at then
      raise exception 'web2_placement_specs.verified_at cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
    -- The evidence IS the audit trail (0114): a verification whose record of what was
    -- checked can be replaced is the same as no verification.
    if old.verified_at is not null
       and (new.verified_evidence is distinct from old.verified_evidence
            or new.verified_by is distinct from old.verified_by) then
      raise exception
        'a verification''s evidence and signer are fixed once it is recorded'
        using errcode = 'check_violation';
    end if;
    if old.first_live_url <> '' and new.first_live_url is distinct from old.first_live_url then
      raise exception 'web2_placement_specs.first_live_url cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
    if old.first_live_at is not null and new.first_live_at is distinct from old.first_live_at then
      raise exception 'web2_placement_specs.first_live_at cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
  end if;

  -- Host binding is checked at INSERT and at ACTIVATION - 0114's rule, same
  -- reasoning: the immutable pair cannot drift on its own, always-revalidating would
  -- refuse the deactivating UPDATE the url-change voider below must apply, and
  -- never-revalidating measurably re-armed a stale binding via a plain
  -- `set active = true`. Activation is the moment the spec starts being served.
  if tg_op = 'UPDATE' and not (new.active and not old.active) then
    new.updated_at := now();
    return new;
  end if;

  spec_host := public._spec_host_of(new.spec ->> 'editor_url');
  if spec_host is null then
    raise exception
      'spec editor_url must be a plain absolute http(s) URL - no backslashes, '
      'whitespace, userinfo, percent-encoding or non-ASCII. Anything a second URL '
      'parser could read differently is refused rather than interpreted.'
      using errcode = 'check_violation';
  end if;
  if public._host_is_ip_literal(spec_host) then
    raise exception
      'spec editor_url host may not be an IP literal (%) - a platform is a domain',
      spec_host using errcode = 'check_violation';
  end if;

  select public._spec_host_of(p.homepage_url) into platform_host
    from public.web2_platforms p where p.id = new.platform_id;
  if platform_host is null then
    raise exception
      'platform % has no usable homepage_url to bind this spec against',
      new.platform_id using errcode = 'check_violation';
  end if;
  if public._host_is_ip_literal(platform_host) then
    raise exception
      'platform % has an IP-literal homepage_url; refusing to bind a spec to it',
      new.platform_id using errcode = 'check_violation';
  end if;
  -- Equal, or a DOT-ANCHORED subdomain, so "evil-medium.com" can never pass as a
  -- subdomain of "medium.com".
  if spec_host <> platform_host and spec_host not like ('%.' || platform_host) then
    raise exception
      'spec editor_url host (%) must belong to the platform host (%) - a spec is not '
      'a free navigation target', spec_host, platform_host
      using errcode = 'check_violation';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists web2_placement_specs_guard_trg on public.web2_placement_specs;
create trigger web2_placement_specs_guard_trg
  before insert or update on public.web2_placement_specs
  for each row execute function public.web2_placement_specs_guard();

-- --- the parser-free bypass, closed the way 0114 closed it -----------------------
-- The guard only ever validates against the CURRENT homepage_url, so editing the
-- catalogue row after earning a spec would leave an active spec pointing at a host
-- the catalogue no longer admits to. A homepage_url change DEACTIVATES that
-- platform's specs; the spec is immutable, so the earned state is simply void and
-- the editor must be re-verified - the honest outcome for a platform that moved.
create or replace function public.web2_platforms_url_change_voids_specs()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.homepage_url is distinct from old.homepage_url then
    update public.web2_placement_specs
       set active = false,
           deactivated_reason = 'platform_url_changed'
     where platform_id = new.id and active;
  end if;
  return new;
end;
$$;

drop trigger if exists web2_platforms_url_change_voids_specs_trg on public.web2_platforms;
create trigger web2_platforms_url_change_voids_specs_trg
  after update of homepage_url on public.web2_platforms
  for each row execute function public.web2_platforms_url_change_voids_specs();

-- --- RLS: standard shape ---------------------------------------------------------
alter table public.web2_placement_specs enable row level security;
alter table public.web2_placement_specs force row level security;

drop policy if exists web2_placement_specs_select on public.web2_placement_specs;
create policy web2_placement_specs_select on public.web2_placement_specs
  for select using (public.is_staff());
drop policy if exists web2_placement_specs_insert on public.web2_placement_specs;
create policy web2_placement_specs_insert on public.web2_placement_specs
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
drop policy if exists web2_placement_specs_update on public.web2_placement_specs;
create policy web2_placement_specs_update on public.web2_placement_specs
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
-- No delete policy: a superseded/deactivated spec is the history of a platform's
-- editor; under FORCE RLS a policy-less DELETE matches zero rows.

drop trigger if exists web2_placement_specs_set_updated_at on public.web2_placement_specs;
create trigger web2_placement_specs_set_updated_at
  before update on public.web2_placement_specs
  for each row execute function public.set_updated_at();

comment on table public.web2_placement_specs is
  'Earned editor specs for extension-assisted Web 2.0 placement (0136, Phase 7): '
  'immutable spec jsonb (editor_url + copy_blocks + optional fields), active only '
  'after a dated human verification AND a first public live URL, editor_url '
  'host-pinned to the platform''s homepage host, drift deactivates. Without an '
  'ACTIVE spec the extension falls back to copy-blocks - it never fills on a guess '
  'and never submits.';
