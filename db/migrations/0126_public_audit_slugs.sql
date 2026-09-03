-- 0126_public_audit_slugs.sql - readable public URLs for audit reports.
--
-- BEFORE: the only public audit URL was
--   /api/v1/public/audits/71ac849396d0c4f13124bf07cee448d6133de59cfaa78681
-- a 48-hex capability token, and it existed for FREE audits only. Paid audits had
-- no public identifier at all - `audits` has no token, slug or published column,
-- so "the paid audit's public page" was in fact the free funnel's token URL.
--
-- AFTER: one registry maps a readable slug to exactly one report of either kind,
-- so both are served by ONE route (/leads/<slug>) instead of two implementations
-- that drift.
--
-- WHY A REGISTRY TABLE rather than a `slug` column on each of the two tables: the
-- slug is derived from the brand/domain, and the same domain can have BOTH a free
-- funnel run and a paid client audit. Two independent unique columns cannot see
-- each other, so they would happily mint "spotino" twice and the route could not
-- resolve it. A single table with a single unique key makes that impossible.
--
-- SECURITY - READ BEFORE WIDENING. The 48-hex token is not decoration; the public
-- routes carry NO authenticated user, and app/routers/public.py states the token
-- "IS the capability: knowing it grants read of exactly that one curated report".
-- A guessable slug therefore REMOVES that control, so the two kinds are treated
-- differently and deliberately:
--
--   free -> published by default. The lead magnet is meant to be shareable, the
--           report is derived wholly from a public crawl of a public website, and
--           the curated projection already withholds the lead's email, the row id,
--           the stored error and every artifact path.
--   paid -> published = false by default. A paid audit is client deliverable work.
--           It becomes reachable only when a staff member publishes it, and it
--           carries a short random suffix on top of the brand slug so that even
--           once published it is not enumerable from the client's name alone.
--
-- The token keeps working. It is not replaced, and nothing is migrated off it -
-- every existing link stays valid.

create table if not exists public.public_audit_pages (
  slug             text primary key
                     check (slug ~ '^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$'),
  kind             text not null check (kind in ('free', 'paid')),
  -- exactly ONE of these is set; the check below enforces it.
  public_audit_id  uuid references public.public_audits (id) on delete cascade,
  audit_id         uuid references public.audits (id) on delete cascade,
  published        boolean not null default false,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint public_audit_pages_one_target check (
    (kind = 'free' and public_audit_id is not null and audit_id is null) or
    (kind = 'paid' and audit_id is not null and public_audit_id is null)
  )
);

-- One page per report, in both directions.
create unique index if not exists public_audit_pages_free_uniq
  on public.public_audit_pages (public_audit_id) where public_audit_id is not null;
create unique index if not exists public_audit_pages_paid_uniq
  on public.public_audit_pages (audit_id) where audit_id is not null;
-- The resolve path: slug -> published row. Partial, because an unpublished page
-- must never be reachable and the index should not carry rows the route ignores.
create index if not exists public_audit_pages_published_idx
  on public.public_audit_pages (slug) where published;

drop trigger if exists public_audit_pages_set_updated_at on public.public_audit_pages;
create trigger public_audit_pages_set_updated_at
  before update on public.public_audit_pages
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Every public table must FORCE row-level security (the deploy gate asserts it).
-- Staff read/write it through the normal authenticated pool; the UNAUTHENTICATED
-- public route reaches it on the privileged service_role path, exactly as the
-- existing public_audits reads do - service_role is BYPASSRLS, so it needs no
-- policy of its own and none is granted here.
alter table public.public_audit_pages enable row level security;
alter table public.public_audit_pages force row level security;

drop policy if exists public_audit_pages_select on public.public_audit_pages;
create policy public_audit_pages_select on public.public_audit_pages
  for select using (public.is_staff());

drop policy if exists public_audit_pages_write on public.public_audit_pages;
create policy public_audit_pages_write on public.public_audit_pages
  for all using (public.is_staff()) with check (public.is_staff());

grant select, insert, update, delete on public.public_audit_pages
  to authenticated, service_role;

-- --- slug derivation ---------------------------------------------------------
-- "https://www.Spotino.org/path" -> "spotino". Host only, www. and the public
-- suffix dropped, everything not [a-z0-9-] collapsed to a hyphen. Returns '' when
-- nothing usable survives, and the caller falls back rather than minting junk.
create or replace function public.audit_brand_slug(p_url text)
returns text
language sql
immutable
as $$
  select coalesce(nullif(
    -- 5. collapse repeated hyphens and trim them off both ends
    trim(both '-' from regexp_replace(
      -- 4. SCRUB: anything outside [a-z0-9-] becomes a hyphen. Without this a
      --    malformed url ("://", "http://:8080") leaves stray punctuation in the
      --    slug, which then violates the CHECK on public_audit_pages.slug and
      --    raises instead of falling back to the caller's default.
      regexp_replace(
        regexp_replace(
          lower(split_part(regexp_replace(
            regexp_replace(coalesce(p_url, ''), '^[a-zA-Z]+://', ''),  -- 1. scheme
            '^www\.', ''                                               -- 2. www.
          ), '/', 1)),                                                 -- 3. host only
          '\.[a-z.]+$', ''                                             --    public suffix
        ),
        '[^a-z0-9-]+', '-', 'g'
      ),
      '-{2,}', '-', 'g'
    )
  ), ''), '');
$$;

-- Claim a unique slug for one report. Idempotent: a report that already has a
-- page keeps the slug it was given, because a public URL that changes is a broken
-- link. Collisions get -2, -3, ... rather than failing.
create or replace function public.ensure_public_audit_page(
  p_kind text, p_public_audit_id uuid, p_audit_id uuid, p_url text, p_published boolean
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_base text;
  v_slug text;
  v_n    int := 1;
begin
  select slug into v_slug from public.public_audit_pages
   where (p_kind = 'free' and public_audit_id = p_public_audit_id)
      or (p_kind = 'paid' and audit_id = p_audit_id);
  if v_slug is not null then
    return v_slug;                                   -- never re-slug a live URL
  end if;

  v_base := public.audit_brand_slug(p_url);
  if v_base = '' then
    v_base := 'report';
  end if;
  -- A paid page carries a short random suffix even before it is published, so a
  -- client's audit is not reachable by guessing their brand name. See the header.
  if p_kind = 'paid' then
    v_base := v_base || '-' || encode(gen_random_bytes(4), 'hex');
  end if;

  v_slug := v_base;
  while exists (select 1 from public.public_audit_pages where slug = v_slug) loop
    v_n := v_n + 1;
    v_slug := v_base || '-' || v_n::text;
  end loop;

  insert into public.public_audit_pages (slug, kind, public_audit_id, audit_id, published)
  values (v_slug, p_kind, p_public_audit_id, p_audit_id, coalesce(p_published, p_kind = 'free'))
  on conflict do nothing;

  -- A concurrent claim may have won the race; re-read rather than assume.
  select slug into v_slug from public.public_audit_pages
   where (p_kind = 'free' and public_audit_id = p_public_audit_id)
      or (p_kind = 'paid' and audit_id = p_audit_id);
  return v_slug;
end;
$$;

-- --- backfill every completed report ----------------------------------------
do $$
declare r record;
begin
  for r in select id, url from public.public_audits where status = 'done' loop
    perform public.ensure_public_audit_page('free', r.id, null, r.url, true);
  end loop;
  for r in select id, url from public.audits where status = 'done' loop
    perform public.ensure_public_audit_page('paid', null, r.id, r.url, false);
  end loop;
end $$;
