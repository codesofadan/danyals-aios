"use client";

import { useMemo, useState } from "react";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { type DialMode } from "@/lib/cost";
import {
  useBudgets, useCostLog, useDial, useSpendStop,
  useSetBudget, useSetDial, useSetSpendStop,
} from "@/lib/hooks/cost";
import CostStats from "./CostStats";
import SpendStopCard from "./SpendStopCard";
import CostDial from "./CostDial";
import BudgetTable from "./BudgetTable";

export default function CostWorkspace() {
  const budgetsQ = useBudgets();
  const dialQ = useDial();
  const logQ = useCostLog();
  const spendStopQ = useSpendStop();
  const setBudget = useSetBudget();
  const setDial = useSetDial();
  const setSpendStop = useSetSpendStop();

  const budgets = budgetsQ.data ?? [];
  const dial = dialQ.data ?? [];
  // The recent-window log feeds the aggregate cards (breakdown / heatmap / jobs).
  // The cost-log TABLE paginates its own fetch (see CostLog), so it no longer grows
  // unbounded with this window.
  const costLog = logQ.data ?? [];

  const [haltPrompt, setHaltPrompt] = useState(false);

  // API-spend HALT: the single agency-global kill-switch (halted === true).
  const halted = spendStopQ.data?.halted ?? false;
  const todaySpent = spendStopQ.data?.todaySpent ?? 0;
  // REAL calendar-month-to-date spend (summed from cost_log by the backend) - the
  // honest source for a "Spend this month" tile. `budgets[].spent` is an ALL-TIME
  // cumulative counter (never reset monthly), so it feeds ONLY the all-time
  // "Budget used" cap ratio below, never a "this month" figure.
  const monthSpent = spendStopQ.data?.monthSpent ?? 0;

  const totals = useMemo(() => {
    const spent = budgets.reduce((s, b) => s + b.spent, 0);
    const cap = budgets.reduce((s, b) => s + b.cap, 0);
    const used = cap === 0 ? 0 : Math.round((spent / cap) * 100);
    return { spent, cap, used };
  }, [budgets]);

  // Derived from the recent cost-log window: a job can have multiple provider rows
  // (one per API call), so "jobs this month" is the count of DISTINCT job ids.
  const jobsThisMonth = useMemo(() => new Set(costLog.map((e) => e.id)).size, [costLog]);

  function handleEditCap(id: string, cap: number) {
    setBudget.mutate({ clientId: id, cap });
  }

  function handleSetMode(key: string, mode: DialMode) {
    setDial.mutate({ key, mode });
  }

  // Flip the global halt (new halted = the inverse of the current state).
  //
  // CONFIRMED, BOTH WAYS. This one control stops - or restarts - every metered
  // feature for the whole agency, and it used to fire on a single click while
  // deleting one WordPress connection asked "are you sure?". ENGAGING it is the
  // safe direction (work pauses, nothing is lost), so it confirms plainly;
  // RELEASING it re-arms real money across every client, so it asks for the
  // word to be typed.
  function handleToggleHalt() {
    setHaltPrompt(true);
  }

  function commitHalt() {
    setSpendStop.mutate(
      { halted: !halted },
      { onSuccess: () => setHaltPrompt(false) },
    );
  }

  const readError =
    budgetsQ.isError || dialQ.isError || logQ.isError || spendStopQ.isError
      ? ((budgetsQ.error ?? dialQ.error ?? logQ.error ?? spendStopQ.error) as Error)?.message
      : null;

  return (
    <div className="cst">
      {readError && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Some cost data couldn&apos;t load. {readError ?? "Try again"}.
        </div>
      )}

      {halted && (
        <div className="cst-halt-banner" role="alert">
          <span className="material-symbols-rounded">block</span>
          <div>
            <b>API spend is HALTED.</b>
            <span> All paid features are paused. Audits, content, policy ask and every metered tool are blocked platform-wide until you resume spend below.</span>
          </div>
        </div>
      )}

      <CostStats spend={monthSpent} budgetUsed={totals.used} jobs={jobsThisMonth} armed={!halted} todaySpent={todaySpent} />

      <div className="row">
        <SpendStopCard
          halted={halted}
          todaySpent={todaySpent}
          onToggle={handleToggleHalt}
          pending={setSpendStop.isPending}
        />
        <CostDial dial={dial} onSetMode={handleSetMode} halted={halted} />
      </div>

      <div className="row-single">
        <BudgetTable budgets={budgets} total={totals} onEditCap={handleEditCap} />
      </div>

      <ConfirmDialog
        open={haltPrompt}
        tone={halted ? "danger" : "caution"}
        title={halted ? "Resume API spending?" : "Halt all API spending?"}
        body={
          halted ? (
            <>
              Every metered feature starts calling providers again for <b>all clients</b> —
              audits, content, policy ask, keyword, rank, embeddings and images — governed
              only by each client&apos;s dials and caps.
            </>
          ) : (
            <>
              Every paid call is refused platform-wide, immediately and for all clients.
              Audits, content generation, policy ask and every metered tool stop spending
              at once.
            </>
          )
        }
        reassurance={
          halted
            ? undefined
            : "Work already in progress is not deleted, and nothing you have paid for is lost — new paid calls are simply refused until you turn this off."
        }
        confirmLabel={halted ? "Resume spending" : "Halt spending"}
        // Typing is required only to RELEASE the halt: engaging it is the safe
        // direction, releasing it re-arms real money across every client.
        typeToConfirm={halted ? "RESUME" : undefined}
        pending={setSpendStop.isPending}
        onConfirm={commitHalt}
        onCancel={() => setHaltPrompt(false)}
      />
    </div>
  );
}
