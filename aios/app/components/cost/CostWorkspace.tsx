"use client";

import { useMemo, useState } from "react";
import {
  budgets_seed, costLog_seed, dial_seed, providerSpend_seed,
  jobsThisMonth, dailyStopDefault,
  type ClientBudget, type DialFeature, type DialMode,
} from "@/lib/cost";
import CostStats from "./CostStats";
import SpendStopCard from "./SpendStopCard";
import CostDial from "./CostDial";
import BudgetTable from "./BudgetTable";
import CostLog from "./CostLog";
import ProviderBreakdown from "./ProviderBreakdown";

export default function CostWorkspace() {
  const [armed, setArmed] = useState(true);
  const [threshold, setThreshold] = useState(dailyStopDefault);
  const [budgets, setBudgets] = useState<ClientBudget[]>(budgets_seed);
  const [dial, setDial] = useState<DialFeature[]>(dial_seed);

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
    setBudgets((prev) => prev.map((b) => (b.id === id ? { ...b, cap } : b)));
  }

  function handleSetMode(key: string, mode: DialMode) {
    setDial((prev) => prev.map((d) => (d.key === key ? { ...d, mode } : d)));
  }

  return (
    <div className="cst">
      <CostStats spend={totals.spent} budgetUsed={totals.used} jobs={jobsThisMonth} armed={armed} />

      <div className="row">
        <SpendStopCard
          armed={armed}
          threshold={threshold}
          onToggle={() => setArmed((v) => !v)}
          onThreshold={setThreshold}
        />
        <CostDial dial={dial} onSetMode={handleSetMode} />
      </div>

      <div className="row-single">
        <BudgetTable budgets={budgets} total={totals} onEditCap={handleEditCap} />
      </div>

      <div className="row">
        <CostLog log={costLog_seed} />
        <ProviderBreakdown data={providerSpend_seed} total={providerTotal} />
      </div>
    </div>
  );
}
