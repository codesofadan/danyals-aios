-- 0159_audit_not_measured_reason.sql - "not measured" now says WHY, and what it is
-- waiting on.
--
-- WHERE THIS STARTED. 0094 made an unmeasured dimension honest: `score` is NULL rather
-- than 0, and every row carries `checks_ran` / `checks_applicable` so "97.2" can never
-- again read as a clean bill of health over a quarter of the checklist. That was the right
-- fix and it is unchanged here.
--
-- WHAT IT STILL COULD NOT SAY. "Off-page - not measured (0 of 80 checks)" is true and
-- unactionable. Four completely different situations produce that same sentence:
--
--   * the backlink provider credential never reached the engine, so 80 checks had no data;
--   * the run's DEPTH did not buy the provider that answers them;
--   * the checks are AI-assisted and no agent ran at this depth;
--   * they are genuinely not applicable to this client (local checks, non-local business).
--
-- The first is a configuration bug the agency should fix today. The last is correct
-- behaviour that should be stated as such to the client. A reader could not tell them
-- apart, so nobody acted on any of them.
--
-- THE DATA ALREADY EXISTED. The engine's coverage.json records a reason PER CHECK, with a
-- `blocked_on` and a note written for a person (`audit_engine/emit.py`: `_why_no_output`,
-- SKIP_AI_NOT_RUN, SKIP_SOURCE_NOT_PERMITTED, ...), and 0094 stores the per-reason counts
-- in `skip_reasons`. What was missing is the one sentence a scorecard row can print. These
-- two columns are that sentence and the thing it is blocked on, derived at ingest from the
-- reason that accounts for the most checks on the row.
--
-- Only ever set where `score is null` - a measured row has nothing to explain, and a
-- reason sitting beside a real score would be read as a caveat on it.
--
-- Additive, idempotent, defaulted to '' so every existing row reads as "no reason
-- recorded" rather than as a claim.

alter table public.audit_rollups
  add column if not exists not_measured_reason text not null default '';

alter table public.audit_rollups
  add column if not exists blocked_on text not null default '';

comment on column public.audit_rollups.not_measured_reason is
  'One plain sentence for why this row has no score, derived at ingest from the dominant '
  'per-check skip reason in coverage.json. Empty when the row WAS measured - a measured '
  'score has nothing to explain, and a reason printed beside one reads as a caveat on it.';

comment on column public.audit_rollups.blocked_on is
  'What the unmeasured checks are waiting on, in the engine''s own words (a provider '
  'credential, AI agent dispatch, this audit command). This is the actionable half: it is '
  'the difference between a configuration the agency can fix today and a limit of the '
  'depth the client paid for.';
