-- 0110_citation_operator_queue.sql - the human work queue, as durable state.
--
-- WHAT THIS REPLACES. The human handoff was `tools/finish_citation.py`: a desktop script
-- that read an exported JSON of every directory login for a campaign and printed
-- "Password for all: ..." (:46). Credentials left the platform as a file, one password
-- covered every account, and the work it did was invisible - nothing recorded who worked
-- what, how long it took, or whether it succeeded. It also could not be assigned, could
-- not be resumed on another machine, and vanished if the file was lost.
--
-- WHY THIS IS THE MOST VALUABLE TABLE IN THE MODULE. Route C - a human, working a
-- directory by hand - is roughly 200 of the 226 catalogue rows and, measured, 56% of the
-- loaded cost per live citation. The two levers on that cost are the per-Add aggregator
-- price and MINUTES PER ITEM, and minutes per item cannot be improved without first being
-- measured. `worked_seconds` below is that measurement. Everything else here exists to
-- make the minutes smaller: a claim so two operators never duplicate an item, a deep link
-- so nobody hunts for the form, and a resumable state so a closed laptop is not lost work.
--
-- WHY THE CLAIM LIVES ON `citations` AND NOT IN A SEPARATE QUEUE TABLE. A listing is one
-- row with one story - 0045 says so in its own header, and 0064 followed it. A second
-- ledger keyed to the same listing is a second thing that can disagree about what happened
-- to it, and the whole recovery this module is undergoing exists because two
-- representations of the same fact were allowed to drift apart.
--
-- THE QUEUE ITSELF IS NOT A NEW STATUS. `ready_for_human` already exists (0064). A row is
-- IN the queue when its status says so; these columns only record who holds it and for how
-- long. Adding a `queued_for_human` status beside `ready_for_human` would be a synonym,
-- and synonyms are how a state machine stops being checkable.
--
-- Additive + idempotent. No new table -> nothing new for app/db/rls_check.py to gate;
-- `citations` is already ENABLE + FORCE (0018).

alter table public.citations
  -- WHO holds this item right now. NULL = unclaimed and available.
  add column if not exists claimed_by       uuid references public.users (id) on delete set null,
  add column if not exists claimed_at       timestamptz,
  -- When the claim lapses. A claim is a LEASE, not a lock: an operator who closes their
  -- laptop must not strand an item forever, so the sweeper below returns it to the pool.
  add column if not exists claim_expires_at timestamptz,
  -- How many humans have picked this up and not finished it. A rising count is the
  -- signal that a directory is harder than the catalogue believes - it is what moves a
  -- row from "we keep trying" to "stop offering this one".
  add column if not exists human_attempts   int not null default 0,
  -- MEASURED time on the item, in seconds, accumulated across claims. This is the number
  -- the entire loaded-cost model rests on, and it was previously unmeasured - the "5
  -- minutes per item" in every projection is an assumption nobody has ever checked.
  -- Accumulated rather than a single duration so a resumed item still totals correctly.
  add column if not exists worked_seconds   int not null default 0,
  -- Free-text note from the operator who worked it: what the directory actually asked
  -- for, what was confusing, why it took as long as it did. This is how a spec gets
  -- better, and it is the only channel the person doing the work has.
  add column if not exists operator_note    text not null default '';

-- The claim query orders by this and filters on status, so both belong in the index.
-- Partial: an item that is not awaiting a human is not part of the queue at all.
create index if not exists citations_queue_idx
  on public.citations (submit_status, claim_expires_at, created_at)
  where submit_status = 'ready_for_human';

-- Reclaiming a lapsed lease is a scan over held items; keep it cheap.
create index if not exists citations_claim_expiry_idx
  on public.citations (claim_expires_at)
  where claimed_by is not null;
