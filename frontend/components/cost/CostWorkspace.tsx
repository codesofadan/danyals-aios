"use client";

import { useMemo, useRef, useState } from "react";
import {
  providerSpend_seed, jobsThisMonth, dailyStopDefault,
  type DialMode,
} from "@/lib/cost";
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

  const providerTotal = useMemo(
    () => providerSpend_seed.reduce((s, p) => s + p.amount, 0),
    [],
  );

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

      <CostStats spend={totals.spent} budgetUsed={totals.used} jobs={jobsThisMonth} armed={armed} />

      <div className="row">
        <SpendStopCard
          armed={armed}
          threshold={threshold}
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
        <ProviderBreakdown data={providerSpend_seed} total={providerTotal} />
      </div>

      <div className="row-single">
        <SpendHeatmap log={costLog} />
      </div>
    </div>
  );
}
