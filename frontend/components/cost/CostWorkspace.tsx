"use client";

import { useMemo, useRef, useState } from "react";
import { dailyStopDefault, type DialMode, type Provider } from "@/lib/cost";
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
  const costLog = logQ.data ?? [];

  // Spend-stop: `armed` (providers live) is the inverse of the server `halted` flag.
  const armed = !(spendStopQ.data?.halted ?? false);
  const serverThreshold = spendStopQ.data?.dailyStop ?? dailyStopDefault;
  // Live day-to-date paid spend (the number the daily stop trips on).
  const todaySpent = spendStopQ.data?.todaySpent ?? 0;
  // Local draft so typing the threshold feels instant; the PUT is debounced and the
  // draft is cleared once the write settles (the query becomes authoritative).
  const [thresholdDraft, setThresholdDraft] = useState<number | null>(null);
  const threshold = thresholdDraft ?? serverThreshold;
  const thrTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const totals = useMemo(() => {
    const spent = budgets.reduce((s, b) => s + b.spent, 0);
    const cap = budgets.reduce((s, b) => s + b.cap, 0);
    const used = cap === 0 ? 0 : Math.round((spent / cap) * 100);
    return { spent, cap, used };
  }, [budgets]);

  // Derived from the real cost log — a job can have multiple provider rows (one
  // per API call), so "jobs this month" is the count of DISTINCT job ids, and the
  // provider breakdown groups+sums cost per provider (both replace hardcoded seeds).
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

  // Trip when armed, re-arm when tripped (new halted = the current armed flag).
  function handleToggleStop() {
    setSpendStop.mutate({ halted: armed });
  }

  function handleThreshold(v: number) {
    setThresholdDraft(v);
    if (thrTimer.current) clearTimeout(thrTimer.current);
    thrTimer.current = setTimeout(() => {
      setSpendStop.mutate({ daily_stop: v }, { onSettled: () => setThresholdDraft(null) });
    }, 500);
  }

  const readError =
    budgetsQ.isError || dialQ.isError || logQ.isError || spendStopQ.isError
      ? ((budgetsQ.error ?? dialQ.error ?? logQ.error ?? spendStopQ.error) as Error)?.message
      : null;

  return (
    <div className="cst">
      {readError && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Some cost data couldn&apos;t load — {readError ?? "try again"}.
        </div>
      )}

      <CostStats spend={totals.spent} budgetUsed={totals.used} jobs={jobsThisMonth} armed={armed} todaySpent={todaySpent} />

      <div className="row">
        <SpendStopCard
          armed={armed}
          threshold={threshold}
          todaySpent={todaySpent}
          onToggle={handleToggleStop}
          onThreshold={handleThreshold}
        />
        <CostDial dial={dial} onSetMode={handleSetMode} />
      </div>

      <div className="row-single">
        <BudgetTable budgets={budgets} total={totals} onEditCap={handleEditCap} />
      </div>

      <div className="row">
        <CostLog log={costLog} />
        <ProviderBreakdown data={providerSpend} total={providerTotal} />
      </div>

      <div className="row-single">
        <SpendHeatmap log={costLog} />
      </div>
    </div>
  );
}
