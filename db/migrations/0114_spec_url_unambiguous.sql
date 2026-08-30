-- 0114_spec_url_unambiguous.sql - stop trying to out-parse the browser.
--
-- 0108 bound a spec's URL host to its directory's host, and an adversarial review broke
-- it. Two payloads passed the check and navigated somewhere else entirely, MEASURED
-- against the real Chromium that Playwright drives:
--
--   https://evil.com\@brownbook.net                     regex host: brownbook.net
--                                                       Chromium host: evil.com
--   https://169.254.169.254\.brownbook.net/latest/...   regex host: the whole authority,
--                                                         which matches '%.brownbook.net'
--                                                       Chromium host: 169.254.169.254
--
-- THE ROOT CAUSE IS NOT A MISSING CASE. `_spec_host_of` is an RFC-3986-shaped regex; the
-- consumer is a WHATWG parser, which treats `\` as `/` inside a special scheme's
-- authority. Two parsers, two answers, and the check believes the wrong one. Adding a
-- backslash case would fix these two payloads and leave the class open - every future
-- divergence between RFC 3986 and the WHATWG URL Standard is another bypass, and there
-- are several (tabs and newlines are stripped, some code points are ignored, `%2e` may
-- normalise).
--
-- SO THE FIX IS NOT A BETTER PARSER, IT IS REFUSING AMBIGUITY. A URL is accepted only if
-- it is written in the narrow, boring form where every parser agrees:
--
--   * scheme is exactly http:// or https://
--   * the host is [a-z0-9.-] only - no userinfo, so no `@` and nothing to strip; no
--     backslash; no whitespace, tabs or newlines; no percent-encoding; no non-ASCII, which
--     also closes IDN homographs (`brownbοok.net` with a Greek omicron)
--   * the rest of the URL carries no backslash and no whitespace
--
-- A directory's real add-listing form is always expressible this way. Anything that is
-- not is refused rather than interpreted, which is the only defensible answer when the
-- consequence of guessing wrong is our own authenticated browser fetching an internal
-- address and returning a screenshot of it.
--
-- AND A HOST THAT IS AN IP LITERAL IS REFUSED OUTRIGHT. A directory is a domain name. IPs
-- are how every SSRF payload names its target (169.254.169.254, 127.0.0.1, 10.x), and no
-- legitimate catalogue row needs one - so the whole shape is closed rather than
-- enumerated as a blocklist of ranges.

create or replace function public._spec_host_of(u text)
returns text language sql immutable as $$
  -- The host, ONLY when the URL is unambiguous. NULL means "refuse", never "unknown".
  --
  -- Handles the two shapes the catalogue holds - `directories.url` is a bare domain in
  -- 155 rows (0046) and a full URL in 71 (0065/0067) - because this same function
  -- normalises both sides of the comparison.
  select case
    -- Reject outright anything a second parser could read differently.
    when u ~ '[\\[:space:]]' then null
    when u ~ '[^\x20-\x7e]' then null          -- non-ASCII: IDN homographs
    when u ~ '%' then null                      -- percent-encoding in the authority
    -- Absolute form: scheme, then a host of letters/digits/dots/hyphens only. No `@`,
    -- so there is no userinfo to strip and no disagreement about where the host starts.
    when u ~* '^https?://[a-z0-9.-]+(:[0-9]{1,5})?([/?#].*)?$' then
      regexp_replace(lower(substring(u from '^https?://([a-z0-9.-]+)')), '^www\.', '')
    -- Bare-domain form, as the 0046 seed rows are written.
    when u ~* '^[a-z0-9.-]+(:[0-9]{1,5})?(/.*)?$' then
      regexp_replace(lower(substring(u from '^([a-z0-9.-]+)')), '^www\.', '')
    else null
  end;
$$;

create or replace function public._host_is_ip_literal(h text)
returns boolean language sql immutable as $$
  -- Dotted-quad, or anything that is only digits and dots. A directory is a domain.
  select h ~ '^[0-9.]+$';
$$;

-- Re-assert the guard so it also refuses an IP-literal host, and so an existing row
-- cannot keep an ambiguous URL it was granted before this migration.
create or replace function public.directory_specs_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  dir_host  text;
  spec_host text;
begin
  if tg_op = 'UPDATE' then
    if new.spec is distinct from old.spec then
      raise exception
        'directory_specs.spec is immutable - insert a new revision instead of editing '
        '(a verification signs the selectors it actually checked)'
        using errcode = 'check_violation';
    end if;
    -- 0114: a verification is earned on ONE directory. Moving the row afterwards would
    -- serve a spec for a directory that never earned it - and the catalogue is full of
    -- shared hosts (4 rows on brownbook.net, 3 on bbb.org, 3 on n49.com), plus the
    -- subdomain rule would let a `lawyers.justia.com` spec move onto the `justia.com`
    -- row. The whitelist is keyed by directory NAME, so the bot would serve it.
    if new.directory_id is distinct from old.directory_id then
      raise exception
        'directory_specs.directory_id is immutable - a verification is earned on one '
        'directory and cannot be moved to another'
        using errcode = 'check_violation';
    end if;
    if old.verified_at is not null and new.verified_at is distinct from old.verified_at then
      raise exception 'directory_specs.verified_at cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
    -- 0114: the EVIDENCE is the audit trail. Leaving it rewritable meant a verification
    -- could keep its date while its record of what was actually checked was replaced -
    -- which is the same as not having one.
    if old.verified_at is not null
       and (new.verified_evidence is distinct from old.verified_evidence
            or new.verified_by is distinct from old.verified_by) then
      raise exception
        'a verification''s evidence and signer are fixed once it is recorded'
        using errcode = 'check_violation';
    end if;
    if old.first_live_url <> '' and new.first_live_url is distinct from old.first_live_url then
      raise exception 'directory_specs.first_live_url cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
    if old.first_live_at is not null and new.first_live_at is distinct from old.first_live_at then
      raise exception 'directory_specs.first_live_at cannot be rewritten once set'
        using errcode = 'check_violation';
    end if;
  end if;

  -- WHEN the host binding is checked, and why it is not simply "always".
  --
  -- `spec` and `directory_id` are immutable, so the pair established at INSERT cannot
  -- drift on its own. Re-validating every UPDATE therefore re-checks something that
  -- cannot have changed - and it BREAKS the url-change trigger below, whose job is to
  -- DEACTIVATE a spec once the catalogue url moves: that deactivating UPDATE would be
  -- refused rather than applied, so a directory holding any spec could never be renamed.
  --
  -- But skipping every UPDATE is worse, and this was measured: deactivate-by-url-change
  -- followed by a plain `set active = true` re-armed a spec whose directory had become
  -- 169.254.169.254. So the rule is neither "always" nor "never" - it is ACTIVATION.
  -- That is the only transition where a stale binding becomes dangerous, because it is
  -- the moment the row starts being served to the browser.
  if tg_op = 'UPDATE' and not (new.active and not old.active) then
    new.updated_at := now();
    return new;
  end if;

  spec_host := public._spec_host_of(new.spec ->> 'url');
  if spec_host is null then
    raise exception
      'spec url must be a plain absolute http(s) URL - no backslashes, whitespace, '
      'userinfo, percent-encoding or non-ASCII. Anything a second URL parser could read '
      'differently is refused rather than interpreted.'
      using errcode = 'check_violation';
  end if;
  if public._host_is_ip_literal(spec_host) then
    raise exception 'spec url host may not be an IP literal (%) - a directory is a domain',
      spec_host using errcode = 'check_violation';
  end if;

  select public._spec_host_of(d.url) into dir_host
    from public.directories d where d.id = new.directory_id;
  if dir_host is null then
    raise exception 'directory % has no usable url to bind this spec against',
      new.directory_id using errcode = 'check_violation';
  end if;
  if public._host_is_ip_literal(dir_host) then
    raise exception 'directory % has an IP-literal url; refusing to bind a spec to it',
      new.directory_id using errcode = 'check_violation';
  end if;
  if spec_host <> dir_host and spec_host not like ('%.' || dir_host) then
    raise exception
      'spec url host (%) must belong to the directory host (%) - a spec is not a free '
      'navigation target', spec_host, dir_host using errcode = 'check_violation';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

-- --- the parser-free bypass: editing the catalogue url after the fact ---------------
-- The spec guard only ever validates against the CURRENT catalogue url, so a lead could
-- point a directory at an internal host, earn a spec against it, and restore the url -
-- leaving an active spec that navigates somewhere the catalogue no longer admits to.
--
-- A url change now DEACTIVATES that directory's specs. It cannot re-validate them: the
-- spec is immutable, so a url change means the pair no longer agrees and the earned
-- state is void. That is also the honest outcome - a directory that moved domain needs
-- its form re-verified anyway (3 of the 50 seeded specs point at directories that were
-- acquired, renamed or absorbed).
create or replace function public.directories_url_change_voids_specs()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.url is distinct from old.url then
    update public.directory_specs
       set active = false,
           deactivated_reason = 'directory_url_changed'
     where directory_id = new.id and active;
  end if;
  return new;
end;
$$;

drop trigger if exists directories_url_change_voids_specs_trg on public.directories;
create trigger directories_url_change_voids_specs_trg
  after update of url on public.directories
  for each row execute function public.directories_url_change_voids_specs();

alter table public.directory_specs drop constraint if exists directory_specs_deactivated_reason_known;
alter table public.directory_specs add constraint directory_specs_deactivated_reason_known
  check (deactivated_reason in (
    '', 'never_verified', 'drift_detected', 'stale_unused',
    'submission_failed', 'operator_disabled', 'terms_changed',
    'directory_url_changed'));
