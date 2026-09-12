-- 0143_grid_square_shape.sql - an N x N SQUARE grid, which is what this market ships.
--
-- WHY THE SHAPE CHANGES. `0138` modelled a grid as concentric 8-point rings, which is
-- a reasonable way to sample a service area and is not the thing anyone else shows.
-- Every tool an operator has used - Local Falcon, BrightLocal, Places Scout - presents
-- an N x N lattice of probe points laid over a real map: a 5x5 or 7x7 block where each
-- cell is a pin carrying its rank. An operator reading our rosette has to translate it
-- before they can compare it to the report they already know how to read, and a client
-- receiving it cannot compare it at all.
--
-- The ring model also cannot express the one thing a square does naturally: EVEN
-- coverage. Eight points per ring means the outer ring samples a much longer
-- circumference at the same point count, so the edges of a large service area are
-- measured more thinly than its centre - exactly backwards, since the edge is where
-- visibility falls off and where the operator is looking.
--
-- SO: `shape` + `grid_size`, and `point_count` becomes shape-aware.
--   'square' -> grid_size x grid_size points (3x3=9 … 11x11=121)
--   'rings'  -> 1 + 8*rings, preserved so every row created before this keeps its
--               geometry and its stored runs stay comparable point-for-point.
--
-- A generated column cannot be altered in place, so it is dropped and re-added with a
-- CASE over the shape. The values are recomputed from the columns that already exist,
-- so no row loses its point count.
--
-- THE CEILING IS 11x11 = 121 PROBES. That is a real bill (121 paid map-pack reads per
-- run), so the CHECK stops at a size the market also stops at rather than leaving
-- room for a 21x21 nobody intended to buy.

alter table public.grid_definitions
  add column if not exists shape text not null default 'square'
    check (shape in ('square', 'rings')),
  add column if not exists grid_size integer not null default 5
    check (grid_size between 3 and 11 and grid_size % 2 = 1);

-- Rows created before this migration are RINGS - that is what was actually probed, and
-- relabelling them 'square' would silently change the meaning of their stored runs.
update public.grid_definitions
set shape = 'rings'
where created_at < now() and shape = 'square' and rings is not null
  and exists (select 1 from public.grid_runs r where r.definition_id = grid_definitions.id);

alter table public.grid_definitions drop column if exists point_count;
alter table public.grid_definitions
  add column point_count integer generated always as (
    case when shape = 'square' then grid_size * grid_size
         else 1 + 8 * rings end
  ) stored;

comment on column public.grid_definitions.shape is
  'square = an N x N lattice (the market standard, and what the UI draws on a map); '
  'rings = the original concentric 8-point rings, kept so pre-0143 rows and their '
  'stored runs remain exactly what was probed.';
comment on column public.grid_definitions.grid_size is
  'N for an N x N square grid. Odd only, so the grid has a true centre cell that sits '
  'on the business. Capped at 11 (121 paid probes per run).';

-- The run row records the geometry AS RUN, so it needs the same two facts or a run
-- cannot be redrawn later without guessing which shape produced it.
alter table public.grid_runs
  add column if not exists shape text not null default 'square'
    check (shape in ('square', 'rings')),
  add column if not exists grid_size integer not null default 5;

update public.grid_runs set shape = 'rings' where shape = 'square';
