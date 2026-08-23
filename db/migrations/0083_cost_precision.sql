-- 0083_cost_precision.sql - make the money ledger able to hold the money.
--
-- THE DEFECT, demonstrated rather than argued. Against the schema built from
-- 0000-0082, inserting the platform's three commonest charges:
--
--     job_type | recorded          add_budget_spend(0.0006) ->
--     ---------+----------         add_budget_spend(0.0012) ->  spent = 0.15
--     content  |     0.15          add_budget_spend(0.15)   ->
--     grid     |     0.00   <--    true total 0.1518, recorded 0.15
--     rank     |     0.00   <--
--
-- `cost_log.cost` and `client_budgets.cap`/`.spent` are numeric(10,2). A DataForSEO
-- Maps grid point costs $0.0006 and a rank check $0.0012, so BOTH of the platform's
-- highest-volume line items round to zero on the way in. Nothing in the application
-- layer rounds - `pricing.py` computes to six decimals and `cost_store.record_cost`
-- binds the value straight into the INSERT - so the column type is the whole defect.
--
-- WHY BOTH TABLES IN ONE MIGRATION. Widening one without the other is strictly worse
-- than widening neither: `cost_log` would report spend that the per-client cap at
-- `cost_gate.py` still cannot see, because `client_budgets.spent` would keep
-- accumulating sub-cent charges as 0.00. A ledger that disagrees with the enforcement
-- it feeds is harder to reason about than one that is uniformly wrong.
--
-- `0044_cost_budget_numeric.sql` already made this trip once, integer -> numeric(10,2),
-- to stop a $0.15 content charge vanishing. It fixed the charge size that existed in
-- 2026; the grid and rank line items are two orders of magnitude smaller and need six
-- decimals, not two. `job_runs.cost_usd` (0080) was specified at numeric(12,6) from
-- the start, so after this migration all three money columns agree.
--
-- WHAT THIS DELIBERATELY DOES NOT DO
--   * It does not change `cap = 0` semantics (still "uncapped"). Making NULL the
--     uncapped sentinel is a change to what money enforcement MEANS, and it wants its
--     own migration and its own rollback - not a rider on a type widening.
--   * It does not wire the daily stop, retire `CostGate.run()`'s estimate-as-actual
--     write, or add typed refusals. Those are application changes; this is the column
--     type they all depend on.
--
-- SAFETY. Widening a numeric is lossless and rewrites in place: every existing
-- 2-decimal value is representable at 6 decimals unchanged (0.15 -> 0.150000). No
-- view, index or constraint depends on these columns (checked against the built
-- schema via pg_depend). `add_budget_spend(uuid, numeric)` already takes numeric and
-- needs no change. Reversible with the same statements at (10,2), though any
-- sub-cent precision recorded in the meantime would be lost on the way back.

alter table public.cost_log
  alter column cost type numeric(12, 6);

comment on column public.cost_log.cost is
  'Actual USD charged, six decimals. A DataForSEO grid point is $0.000600 and a rank '
  'check $0.001200 - at the previous numeric(10,2) both recorded as $0.00, which is '
  'why the platform''s two highest-volume line items appeared free.';

alter table public.client_budgets
  alter column cap   type numeric(12, 6),
  alter column spent type numeric(12, 6);

comment on column public.client_budgets.spent is
  'Month-to-date USD, six decimals, maintained by add_budget_spend(). Must match '
  'cost_log.cost precision: if `spent` rounds where `cost` does not, the per-client '
  'cap cannot see spend the ledger reports.';

comment on column public.client_budgets.cap is
  'Monthly ceiling in USD. 0 still means UNCAPPED - deliberately unchanged here; '
  'making NULL the uncapped sentinel is a semantics change owed its own migration.';
