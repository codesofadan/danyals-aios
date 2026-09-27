-- 0153_grid_center_maps_url.sql - a third centre source: the operator's pasted Maps link.
--
-- 0138 fixed `center_source` to exactly two values, and its two-source rule was right
-- for the sources that existed: coordinates a human typed (`operator`), or a Places
-- TEXT SEARCH for the business name (`places`). 0142's header records what the second
-- one costs - "Alligator Pools" plus a Karachi address resolving to Miami, Florida -
-- and the fix there was to store the matched listing as evidence so a human could catch
-- it. That helps after the fact. It does not stop Places from having to guess.
--
-- A pasted Google Maps URL removes the guess. The operator has already found the
-- business on Google; the link names that exact listing and carries its own pin. There
-- is no top-hit-wins step, so there is no wrong-continent failure mode to catch.
--
-- WHY IT IS A THIRD VALUE AND NOT `places`. Both call the Places API, so folding this
-- into `places` is tempting and wrong: they differ in the thing that actually matters
-- about a stored centre, which is how much you should trust it. A `places` centre is a
-- name match that a human should eyeball against the evidence columns. A `maps_url`
-- centre is a place_id lookup of a listing a human already picked. Recording them as
-- the same fact would erase, permanently, the distinction the operator created by
-- taking the trouble to paste a link - and every grid created before and after this
-- migration would then read identically.
--
-- The evidence columns from 0142 carry MORE here, not less: `center_matched_name` and
-- `center_matched_address` are filled from the Places Details response for the exact
-- listing, so the confirmation screen shows the business the operator pointed at.
--
-- Additive: widening a CHECK constraint accepts every row that already exists.

alter table public.grid_definitions
  drop constraint if exists grid_definitions_center_source_check;

alter table public.grid_definitions
  add constraint grid_definitions_center_source_check
  check (center_source in ('places', 'operator', 'maps_url'));

comment on column public.grid_definitions.center_source is
  'How this grid''s centre was fixed. `operator` - coordinates typed by hand. '
  '`places` - a Places TEXT SEARCH for the business name (a match, judge it against '
  'the center_matched_* evidence). `maps_url` - resolved from a Google Maps link the '
  'operator pasted, which names one exact listing; the most trustworthy of the three.';
