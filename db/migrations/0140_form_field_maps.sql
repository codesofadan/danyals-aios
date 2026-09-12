-- 0140_form_field_maps.sql - the SEMANTIC form-mapping cache.
--
-- WHAT THIS IS FOR. The extension's autofill has always been driven by
-- `public.directory_specs` (0108): immutable, human-verified, "earned" specs. There
-- are none active, so on essentially every directory the panel falls back to copy
-- buttons and an operator pastes eight fields by hand. `app/services/
-- form_intelligence.py` is the fallback lane - it sends a PII-free structural digest
-- of the open form and gets back a `{selector -> canonical key}` plan.
--
-- This table is what stops that lane being billed per click.
--
-- THE COST MODEL IS THE WHOLE REASON IT EXISTS. A directory's add-listing form changes
-- rarely, but it is filled repeatedly - once per client, by whoever is on shift. Without
-- a cache, the same inference is paid for every time, by every operator, forever. With
-- one, the FIRST operator to meet a form pays; everyone after reads a row.
--
-- KEYED ON A STRUCTURAL FINGERPRINT, NOT A URL. `form_intelligence.fingerprint()`
-- hashes host + each field's (kind, name, id, label, placeholder). Deliberately NOT the
-- selectors - a site that emits generated class names (`.css-1a2b3c`) would miss the
-- cache on every page load - and deliberately NOT the URL, because the same add-listing
-- form is reached at `/add`, `/add?ref=x` and `/business/create`. A form that GAINS a
-- field fingerprints differently and correctly misses, which is exactly when the stored
-- mapping is stale and would fill the wrong boxes.
--
-- WHAT IT IS NOT. This is a CACHE, not evidence, and it must never be confused with an
-- earned spec:
--   * an earned spec is activated by a dated human DOM check plus a real listing URL,
--     is immutable, and is host-pinned by a trigger (0108/0114);
--   * a row here is a model's proposal, carries its own confidence, and may be wrong.
-- So the resolver always prefers an active earned spec, and a row here can be deleted
-- and recomputed at any time without losing anything that was verified. That is why
-- this table has a DELETE policy and `directory_specs` does not.
--
-- RLS: staff read (is_staff()); leads insert/update/delete. The API writes the row on
-- the caller's own identity, so an operator-token request writes as the staff user the
-- token belongs to - no service_role path, and no way for a cache write to escape the
-- tenant boundary.

create table if not exists public.form_field_maps (
  id            uuid primary key default gen_random_uuid(),

  -- The structural fingerprint (sha256 hex). One row per distinct form.
  fingerprint   text not null unique check (fingerprint ~ '^[0-9a-f]{64}$'),
  -- The host the form was seen on, for operator-facing listings and for cache
  -- invalidation by site. Already inside the fingerprint; stored again because you
  -- cannot read a host back out of a hash.
  host          text not null default '',
  -- The catalogue row this form belongs to, when the caller knew it. Nullable: the
  -- web2 lane and ad-hoc pages have no directory.
  directory_id  uuid references public.directories (id) on delete set null,

  -- The mapping itself: [{"index": int, "selector": str, "key": str, "confidence": num}].
  -- `selector` is stored because it is what the filler consumes; it is NOT part of the
  -- fingerprint (see the header) and may legitimately differ between page loads, which
  -- is why a stale selector is a MISS at fill time, not a corrupt cache.
  mappings      jsonb not null default '[]',

  -- Provenance. `model` is which model produced it, so a bad batch can be found and
  -- purged by model rather than wholesale.
  model         text not null default '',
  -- The number of fields the mapper was confident enough to fill, and the total it
  -- mapped. Surfaced so an operator can see "6 of 11 auto-filled" before pressing.
  fields_fillable integer not null default 0 check (fields_fillable >= 0),
  fields_total    integer not null default 0 check (fields_total >= 0),

  -- Cache accounting, so "is this worth keeping" is answerable with data.
  use_count     integer not null default 0 check (use_count >= 0),
  last_used_at  timestamptz,
  created_by    uuid references public.users (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  -- A row that maps nothing is not a cache hit worth serving - it would suppress a
  -- retry that might succeed. The service refuses to store one; this makes it true
  -- for any writer.
  constraint form_field_maps_not_empty_ck check (jsonb_array_length(mappings) > 0)
);

create index if not exists form_field_maps_host_idx on public.form_field_maps (host);
create index if not exists form_field_maps_directory_idx
  on public.form_field_maps (directory_id);

create trigger form_field_maps_set_updated_at
  before update on public.form_field_maps
  for each row execute function public.set_updated_at();

alter table public.form_field_maps enable row level security;
alter table public.form_field_maps force row level security;

create policy form_field_maps_select on public.form_field_maps
  for select using (public.is_staff());
create policy form_field_maps_insert on public.form_field_maps
  for insert with check (public.is_staff());
-- Update is how `use_count` / `last_used_at` advance on a hit, so any staff member on
-- shift must be able to do it - it is cache accounting, not a privileged act.
create policy form_field_maps_update on public.form_field_maps
  for update using (public.is_staff()) with check (public.is_staff());
-- DELETE exists here and deliberately does NOT on `directory_specs`: a cache row is a
-- proposal that can be recomputed, an earned spec is evidence that cannot. Leads only.
create policy form_field_maps_delete on public.form_field_maps
  for delete using (public.current_app_role() in ('owner', 'admin', 'manager'));
