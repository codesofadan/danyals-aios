-- 0115_citation_invariants.sql - five rules that were Python's word, or nobody's.
--
-- The adversarial review of 0106-0114 confirmed three blocking defects (fixed in 0114 and
-- its commit) and left a tail of findings that share one shape: a rule the code STATES
-- and the database does not hold. `service_role` is BYPASSRLS, so a policy is not a
-- backstop for any of them - a CHECK or a trigger is. Each section below closes one.
--
--   1. `submit_method` had two vocabularies for one concept, and 65 rows spoke the one
--      no dispatcher understands.
--   2. A route-F directory "cannot be queued" was enforced in Python only.
--   3. `operator_tokens.scopes` was called a CLOSED vocabulary and was a free jsonb array.
--   4. `directory_specs`' shape CHECK was weaker than the loader that trusts it.
--   5. `citation_accounts`' failed-seal rollback deleted nothing, silently.
--
-- Idempotent throughout (`if not exists` / `drop ... if exists`), per the house rule that
-- a migration re-applied against a partially-migrated database must not fail.

begin;

-- --------------------------------------------------------------------------- --
-- 1. ONE VOCABULARY FOR submit_method.
--
-- MEASURED before this migration:
--
--   bot:playwright          bot_fillable      95     dispatched
--   bot:playwright+captcha  captcha_assisted  32     dispatched
--   playwright              bot_fillable      41     NO ENGINE
--   playwright              captcha_assisted  18     NO ENGINE
--   playwright              manual_only       11     NO ENGINE
--   manual                  manual_only       19     NO ENGINE
--
-- `submitter_for` dispatches on the `bot:` / `api:` / `aggregator:` prefix, so the 70
-- bare-`playwright` rows fell through to "no automatable engine" - not blocked for a
-- reason anyone chose, but because the catalogue was seeded across several migrations
-- with two names for one thing. It has been invisible only because 0108 made the earned
-- whitelist empty, so every bot row blocks anyway; the day the first spec is earned, 59
-- of these would have stayed dark with a misleading reason.
--
-- 0106 §8 met this same species and fixed ONE row: it re-pointed Google Business Profile
-- off a bare 'playwright' and wrote that the value "matches no dispatch prefix and so
-- blocked only by accident". That was true of 69 other rows too, and the phrase names the
-- danger exactly - a row blocked by accident looks identical to a row blocked on purpose,
-- right up until the accident stops happening.
--
-- `tier` is the authority for which prefix each row should carry - it is the column the
-- cost estimator and the campaign planner already read - so the rewrite is derived, not
-- guessed. A `manual_only` row keeps NO bot prefix: it is genuinely manual, and giving it
-- one would queue a bot against a directory nobody verified can be botted.
update public.directories
   set submit_method = 'bot:playwright'
 where submit_method = 'playwright' and tier = 'bot_fillable';

update public.directories
   set submit_method = 'bot:playwright+captcha'
 where submit_method = 'playwright' and tier = 'captcha_assisted';

update public.directories
   set submit_method = 'manual'
 where submit_method = 'playwright' and tier = 'manual_only';

-- And the structural half, so a third vocabulary cannot appear. Every value must either
-- carry a dispatcher's prefix or be one of the two terminal words that mean "no engine,
-- by intent". A future seed with `submit_method = 'selenium'` now fails loudly at write
-- time instead of producing a directory that silently never submits.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'directories_submit_method_dispatchable'
  ) then
    alter table public.directories
      add constraint directories_submit_method_dispatchable check (
        submit_method = ''
        or submit_method in ('manual', 'closed')
        or submit_method like 'api:%'
        or submit_method like 'bot:%'
        or submit_method like 'aggregator:%'
      );
  end if;
end $$;

-- --------------------------------------------------------------------------- --
-- 2. A ROUTE-F DIRECTORY CANNOT BE QUEUED - IN THE DATABASE.
--
-- Route F is the hand-verified "terms prohibit automated access" set (0106 seeds 16 from
-- R1 §3.7: Yelp's ToS §7.2(j) plus its blanket robots.txt, Trustpilot's definition of
-- "you" as including automated technologies, Houzz §4). `is_prohibited()` blocks it in
-- the planner and `submitter_for` never dispatches it - but both are Python, and the one
-- rule in this module with a legal consequence should not depend on every future caller
-- remembering to ask.
--
-- The trigger reads the DIRECTORY's route, not the citation's. The citation's own `route`
-- column defaults to 'C' and is set by the planner - so trusting it would let a row that
-- never went through the planner queue itself against Yelp. The directory's route is the
-- hand-verified fact; the citation's is a derived copy.
--
-- `not_started` and the terminal states stay legal: an F row may EXIST (it is how the
-- client report says "not attempted - terms prohibit automated submission" instead of
-- quietly omitting it). What it may never do is enter a state that means a machine is
-- about to act on it.
create or replace function public.citations_block_prohibited_route()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  dir_route char(1);
begin
  if new.submit_status not in ('queued', 'submitting', 'ready_for_human') then
    return new;
  end if;
  -- Unchanged status on an UPDATE is not a re-entry, so an F row already parked in a
  -- state (however it got there) can still be corrected or cleared.
  if tg_op = 'UPDATE' and old.submit_status = new.submit_status then
    return new;
  end if;

  select d.route into dir_route
    from public.directories d
   where d.id = new.directory_id;

  if dir_route = 'F' then
    raise exception
      'directory % is route F (terms prohibit automated submission); it cannot be queued',
      new.directory_id
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

drop trigger if exists citations_prohibited_route_guard on public.citations;
create trigger citations_prohibited_route_guard
  before insert or update on public.citations
  for each row execute function public.citations_block_prohibited_route();

comment on function public.citations_block_prohibited_route() is
  'Route F (terms prohibit automated access) cannot enter queued/submitting/'
  'ready_for_human. Reads directories.route - the hand-verified fact - not the '
  'citation''s own derived copy, so a row that bypassed the planner is still refused.';

-- --------------------------------------------------------------------------- --
-- 3. THE SCOPE VOCABULARY IS CLOSED - IN THE DATABASE.
--
-- `operator_tokens`' own header calls the vocabulary CLOSED and says containment is
-- "structural, not a matter of which routes remember to check". It was neither: `scopes`
-- was a bare `jsonb not null default '[]'`, and `cap_scopes` - the only thing enforcing
-- it - runs in Python, on the app tier, which `service_role` bypasses entirely.
--
-- Now the sentence is true. A token granting 'vault' or 'admin' cannot be stored, so no
-- future route can be reached by presenting one, however it was written.
--
-- Written with jsonb containment rather than a scan: Postgres refuses a subquery in a
-- CHECK expression, and `<@` says exactly the intended thing - every element of `scopes`
-- appears in the vocabulary. It also rejects non-strings for free (`[1]` is not contained
-- by an array of two strings), and still admits `[]`, which is a token that grants
-- nothing. `jsonb_typeof` stays because containment treats a bare scalar as contained.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'operator_tokens_scopes_closed'
  ) then
    alter table public.operator_tokens
      add constraint operator_tokens_scopes_closed check (
        jsonb_typeof(scopes) = 'array'
        and scopes <@ '["citation_queue", "citation_credential"]'::jsonb
      );
  end if;
end $$;

-- --------------------------------------------------------------------------- --
-- 4. THE SPEC SHAPE CHECK NOW MATCHES WHAT THE LOADER ASSUMES.
--
-- `form_spec_from_json` documents itself as not re-validating because "the DB already
-- enforced the shape (https url, >=1 field, a submit selector, a success indicator)".
-- 0108's CHECK enforced four of those seven words: object, has url, has fields, fields is
-- an array. It did NOT require `success_indicator`, a non-empty `fields`, or a `selector`
-- and `value_key` on each field.
--
-- The consequence was not a crash - the loader catches and logs - it was worse: a spec
-- that had been EARNED (verified against a real submission, `first_live_url` on file)
-- would vanish from the loader with one log line, and the directory would report "no
-- verified spec" forever. An empty `fields` array was quieter still: it loads fine and
-- fills nothing, so the operator watches a form stay blank with no error anywhere.
--
-- Every element is now required to be what the reader dereferences.
alter table public.directory_specs
  drop constraint if exists directory_specs_spec_is_an_object;

--
-- The per-field scan lives in an IMMUTABLE helper because a CHECK expression may not
-- contain a subquery, and validating each element of an array needs one. A function call
-- is permitted, and the body may contain whatever it likes.
create or replace function public.citation_spec_fields_ok(spec jsonb)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select jsonb_typeof(spec -> 'fields') = 'array'
     and jsonb_array_length(spec -> 'fields') > 0
     and not exists (
       select 1 from jsonb_array_elements(spec -> 'fields') f(v)
       where jsonb_typeof(f.v) <> 'object'
          -- `->>` returns NULL for both a missing key and a JSON null, so one coalesce
          -- covers absent, null and empty - all three of which break the loader.
          or coalesce(f.v ->> 'selector', '') = ''
          or coalesce(f.v ->> 'value_key', '') = ''
     )
$$;

comment on function public.citation_spec_fields_ok(jsonb) is
  'Every element of spec->fields is an object carrying a non-empty selector and '
  'value_key, and there is at least one. Exactly what form_spec_from_json dereferences.';

alter table public.directory_specs
  add constraint directory_specs_spec_is_an_object check (
    jsonb_typeof(spec) = 'object'
    and spec ? 'url'
    and spec ? 'submit_selector'
    and spec ? 'success_indicator'
    and public.citation_spec_fields_ok(spec)
  );

-- --------------------------------------------------------------------------- --
-- 5. THE FAILED-SEAL ROLLBACK ACTUALLY DELETES.
--
-- `create_account_with_credential` inserts the row, seals the password into the vault
-- under coordinates derived from the row's own id, and - if sealing raises - deletes the
-- row, because (its words) "a citation_account with no credential is worse than no row at
-- all: it looks like an account we hold, and the unique constraint on
-- (client_id, directory_id) would then block the retry".
--
-- 0111 gave the table SELECT, INSERT and UPDATE policies and no DELETE policy. Under
-- FORCE ROW LEVEL SECURITY a DELETE with no policy is not an error - it matches zero rows
-- and reports success. So the rollback did nothing, the row survived without a
-- credential, and the retry it was written to enable was blocked by the very constraint
-- the comment names.
--
-- The policy is deliberately NARROWER than the others: only a row whose credential was
-- never sealed may be deleted. That is exactly the rollback case and nothing else - a
-- sealed account is an auditable record of a login that exists in the world, and deleting
-- it would orphan the vault entry it points at. Rotation and disablement are UPDATEs.
drop policy if exists citation_accounts_delete on public.citation_accounts;
create policy citation_accounts_delete on public.citation_accounts
  for delete
  using (
    public.current_app_role() in ('owner', 'admin', 'manager')
    and credential_sealed_at is null
  );

comment on policy citation_accounts_delete on public.citation_accounts is
  'Rollback only. A row whose credential never sealed may be removed so the unique '
  '(client_id, directory_id) constraint does not block the retry; a SEALED account is '
  'a record of a real login and is not deletable.';

commit;
