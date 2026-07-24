"use client";

import { useMemo } from "react";
import { type DialMode, type Provider } from "@/lib/cost";
import {
  useBudgets, useCostLog, useDial, useSpendStop,
  useSetBudget, useSetDial, useSetSpendStop,
} from "@/lib/hooks/cost";
import CostStats from "./CostStats";
import SpendStopCard from "./SpendStopCard";
import CostDial from "./CostDial";
import BudgetTable from "./BudgetTable";
import CostLog from "./CostLog";
import ProviderBreakdown from "./ProviderBreakdown";
import SpendHeatmap from "./SpendHeatmap";

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

  // API-spend HALT: the single agency-global kill-switch (halted === true).
  const halted = spendStopQ.data?.halted ?? false;
  const todaySpent = spendStopQ.data?.todaySpent ?? 0;

  const totals = useMemo(() => {
    const spent = budgets.reduce((s, b) => s + b.spent, 0);
    const cap = budgets.reduce((s, b) => s + b.cap, 0);
    const used = cap === 0 ? 0 : Math.round((spent / cap) * 100);
    return { spent, cap, used };
  }, [budgets]);

  // Derived from the recent cost-log window: a job can have multiple provider rows
  // (one per API call), so "jobs this month" is the count of DISTINCT job ids, and
  // the provider breakdown groups+sums cost per provider.
  const providerSpend = useMemo(() => {
    const byProvider = new Map<Provider, number>();
    for (const e of costLog) byProvider.set(e.provider, (byProvider.get(e.provider) ?? 0) + e.cost);
    return [...byProvider.entries()].map(([provider, amount]) => ({ provider, amount }));
  }, [costLog]);
  const providerTotal = useMemo(
    () => providerSpend.reduce((s, p) => s + p.amount, 0),
    [providerSpend],
  );
  const jobsThisMonth = useMemo(() => new Set(costLog.map((e) => e.id)).size, [costLog]);

  function handleEditCap(id: string, cap: number) {
    setBudget.mutate({ clientId: id, cap });
  }

  function handleSetMode(key: string, mode: DialMode) {
    setDial.mutate({ key, mode });
  }

  // Flip the global halt (new halted = the inverse of the current state).
  function handleToggleHalt() {
    setSpendStop.mutate({ halted: !halted });
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

      <CostStats spend={totals.spent} budgetUsed={totals.used} jobs={jobsThisMonth} armed={!halted} todaySpent={todaySpent} />

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

      <div className="row">
        <CostLog />
        <ProviderBreakdown data={providerSpend} total={providerTotal} />
      </div>

      <div className="row-single">
        <SpendHeatmap log={costLog} />
      </div>
    </div>
  );
}
