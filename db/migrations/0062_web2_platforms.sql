-- 0062_web2_platforms.sql - the WEB 2.0 PLATFORM CATALOG: a curated target list of
-- the web2 backlink properties the off-page automation works through, EXACTLY like
-- public.directories (0045/0046) catalogs the citation directories (155 rows) that
-- run alongside the 36 bot form-specs. Seeded in 0063 (mirrors the 0045/0046 split).
--
-- WHY a catalog table (not just the enum): today the off-page module knows 17 web2
-- platforms - the public.web2_platform ENUM (0018/0045) plus a real Web2Publisher
-- class each in integrations/web2_publishers.py. That set is what the pipeline can
-- actually PUBLISH to. The STRATEGY surface, though, wants a broader, HONEST inventory
-- of real web2 properties to build - most of which we do not (yet) automate. This
-- table is that inventory: 50 real platforms, each classified by auth_type +
-- authority_tier + market, with automation_ready=true on exactly the 17 the pipeline
-- already drives (the WEB2_PLATFORMS frozenset). It is the web2 analogue of the
-- directory catalog: the 17 automation_ready rows are the "36 form-specs" equivalent
-- (work the automation completes today), the other 33 are the catalogued build target.
--
-- DECOUPLED FROM THE ENUM (deliberate): `name` is FREE TEXT, not the web2_platform
-- enum. The enum still gates actual PUBLISHING (a web2_properties row's platform column
-- IS the enum type, and a Web2Publisher must exist) - so publishing to a catalog row
-- whose name is NOT yet an enum value requires, LATER, two steps: (1) ALTER TYPE
-- public.web2_platform ADD VALUE '<name>' (its own standalone migration - Postgres
-- forbids using a new enum value in the txn that adds it, see 0045's header) and (2) a
-- Web2Publisher class + credential shape for it (integrations/web2_publishers.py). The
-- catalog lists the TARGET; the enum + publisher gate the ACT. Keeping name free-text
-- lets the catalog grow to 50 (and beyond) without forcing 33 half-built publishers.
--
-- REFERENCE DATA, not tenant data: like public.directories, every tenant shares one
-- catalog of "what web2 properties exist and how automatable are they". Still ENABLE +
-- FORCE RLS - the coverage gate (app/db/rls_check.py) has no allowlist, so a shared
-- reference table is protected exactly like a tenant table: any staff READS
-- (is_staff()), only leads (owner/admin/manager) MAINTAIN it. This is the identical
-- ENABLE/FORCE + policy shape public.directories uses (0045), so the gate stays green.

-- --- Enum ----------------------------------------------------------------------
-- Creating a new enum TYPE and using it in the same file's `create table` is allowed
-- (the txn-forbidden construct is only ALTER TYPE ... ADD VALUE then using that NEW
-- value in the same txn - 0045's web2_platform growth). Guarded so a re-apply is a
-- no-op, mirroring 0045's `business_market`/`directory_tier` guards.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_auth_type') then
    -- How the automation AUTHENTICATES to publish (honest per platform):
    --   api        - a static API key / token / PAT in a header, or a documented
    --                key-authed REST/GraphQL/XML-RPC write (dev.to, Ghost, Hashnode,
    --                the GitHub/GitLab PATs, the LiveJournal-protocol user+password).
    --   oauth      - an OAuth flow issues the token (WordPress.com, Blogger, Tumblr,
    --                Mastodon, Micro.blog/IndieAuth, Plurk OAuth1, Disqus OAuth2).
    --   automation - NO public write API; a browser/editor publish drives it (most
    --                hosted site builders + curation/portfolio properties; Medium,
    --                whose publish API is retired, is prepared as a manual draft).
    --   anonymous  - no account needed at all to publish (Telegra.ph).
    create type public.web2_auth_type as enum ('api', 'oauth', 'automation', 'anonymous');
  end if;
end $$;

-- --- web2_platforms: the catalog (reference data) ------------------------------
create table if not exists public.web2_platforms (
  id                    uuid primary key default gen_random_uuid(),
  name                  text not null,
  homepage_url          text not null default '',
  signup_url            text not null default '',
  -- The write path: an API endpoint + credential model, or the human/automation action
  -- ("automation: editor publish ..."). Operational shorthand, not a client-facing doc.
  publish_url_or_method text not null default '',
  auth_type             public.web2_auth_type not null default 'automation',
  -- Directional link/authority value of a placement here (high/medium/low) - NOT a DA
  -- number (which conflicts across tools; re-pull before it drives a paid decision).
  authority_tier        text not null default 'medium'
    check (authority_tier in ('high', 'medium', 'low')),
  -- Lower-case market label; 'global' for the (majority) non-geo publishing platforms,
  -- else a country code (Hatena Blog = 'jp'). Kept text - NOT public.business_market,
  -- which is US/UK/CA/AU/GLOBAL only - so a JP-market platform is honestly labelled.
  market                text not null default 'global'
    check (market in ('global', 'us', 'uk', 'ca', 'au', 'jp')),
  -- true IFF a real Web2Publisher client + the web2_platform enum value BOTH exist for
  -- this platform (integrations/web2_publishers.py) - i.e. the pipeline can publish here
  -- now. The 17 automation_ready rows are precisely the WEB2_PLATFORMS frozenset.
  automation_ready      boolean not null default false,
  notes                 text not null default '',
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (name)
);

create index if not exists web2_platforms_auth_type_idx
  on public.web2_platforms (auth_type);
create index if not exists web2_platforms_automation_ready_idx
  on public.web2_platforms (automation_ready);
create index if not exists web2_platforms_authority_tier_idx
  on public.web2_platforms (authority_tier);

create trigger web2_platforms_set_updated_at
  before update on public.web2_platforms
  for each row execute function public.set_updated_at();

alter table public.web2_platforms enable row level security;
alter table public.web2_platforms force row level security;

create policy web2_platforms_select on public.web2_platforms
  for select using (public.is_staff());
create policy web2_platforms_insert on public.web2_platforms
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy web2_platforms_update on public.web2_platforms
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
