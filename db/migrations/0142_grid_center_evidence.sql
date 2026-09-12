-- 0142_grid_center_evidence.sql - record WHICH listing a resolved centre came from.
--
-- THE DEFECT THIS CLOSES, measured on the live dev stack. A grid was created for a
-- client called "Alligator Pools" at a location labelled "Karachi" with the address
-- "Main Boulevard, Karachi, Pakistan". The centre resolved to 25.649387, -80.33907 -
-- Miami, Florida. Places had matched the BUSINESS NAME against the real Alligator
-- Pools in the United States and disregarded the address entirely.
--
-- Everything downstream was then correct and worthless: 17 probes, a clean heat map,
-- honest `ranked`/`absent` states - all measuring a city 14,000 km from the one the
-- operator named. `center_source='places'` said the centre was resolved; it could not
-- say resolved TO WHAT.
--
-- So the resolver now returns the matched listing's own name and address and they are
-- stored here beside the coordinates. The operator sees "centre resolved from: Alligator
-- Pools, 1234 SW 8th St, Miami FL" and the mistake is obvious in the second before any
-- money is spent, instead of invisible forever afterwards.
--
-- Deliberately NOT a refusal. The platform cannot geocode the stated address without a
-- second paid call, and a heuristic string comparison between two addresses written by
-- different parties rejects correct matches as readily as wrong ones ("Main Blvd" vs
-- "Main Boulevard", a listing under a district name). The honest move is to show the
-- evidence and let the person who typed the address judge it - the same reasoning as
-- the citation module's earned evidence, where a human confirms what a probe found.
--
-- Additive and nullable: every existing row keeps its coordinates and simply has no
-- evidence recorded, which is the truth about rows created before this.

alter table public.grid_definitions
  add column if not exists center_matched_name    text not null default '',
  add column if not exists center_matched_address text not null default '';

comment on column public.grid_definitions.center_matched_name is
  'The business name of the Google listing a `places`-resolved centre came from. Empty '
  'for an operator-entered centre, and for rows created before 0142.';
comment on column public.grid_definitions.center_matched_address is
  'The address of that listing. Shown beside the coordinates so a centre resolved to '
  'the wrong city is visible before a run is paid for - see the header.';
