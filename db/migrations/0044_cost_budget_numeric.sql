-- 0044_cost_budget_numeric.sql - make per-client budget accounting count cents.
--
-- WHY (a latent, load-bearing defect in the client's #1 requirement): 0006 typed
-- public.client_budgets.cap and .spent as INTEGER, but every charge is
-- numeric(10,2) and most are sub-dollar (content ~$0.15/pg, a rank check
-- ~$0.001). add_budget_spend(p_amount numeric) writes that amount into the
-- INTEGER `spent`, so PostgreSQL ROUNDS it - $0.15 becomes 0. `spent` therefore
-- never grows for any sub-dollar module, and the gate's per-client cap check
-- (cost_gate.py: `spent + est > cap`) can never trip. Only the org-wide daily
-- spend-stop (which sums the numeric cost_log) actually bites today.
--
-- The fix is the column type: numeric(10,2) matches the charge precision and the
-- cost_log.cost / cost_settings.daily_stop columns, so 100 x $0.15 accumulates to
-- $15.00 exactly and a $10 cap trips. add_budget_spend already takes numeric and
-- needs no change; the gate's read (cost_store.client_budget) already casts to
-- float, so enforcement becomes exact with no code change. This is a widening of
-- existing integer values (0, 120, 500 -> 0.00, 120.00, 500.00) - lossless.
--
-- Cap SEMANTICS are deliberately UNCHANGED here: cap = 0 still means "uncapped"
-- (cost_gate.py only enforces `cap > 0`). Flipping 0 -> "stopped" with NULL =
-- uncapped is a separate product decision that also touches the API/frontend, so
-- it is intentionally NOT bundled into this type-only migration.

alter table public.client_budgets
  alter column cap   type numeric(10, 2) using cap::numeric(10, 2),
  alter column spent type numeric(10, 2) using spent::numeric(10, 2);

alter table public.client_budgets
  alter column cap   set default 0,
  alter column spent set default 0;
