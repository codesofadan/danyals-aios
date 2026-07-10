import Link from "next/link";
import { budgets_seed, budgetPct, budgetStatus, dailyStopDefault, usd, type BudgetStatus } from "@/lib/cost";

const STATUS_COLOR: Record<BudgetStatus, string> = {
  ok: "var(--ok)", warn: "var(--warn)", crit: "var(--crit)",
};

// Platform spend snapshot for the main dashboard — month-to-date across all
// clients, plus the near/over-cap accounts. Full controls live in /cost.
export default function SpendSnapshot() {
  const totalSpent = budgets_seed.reduce((s, b) => s + b.spent, 0);
  const totalCap = budgets_seed.reduce((s, b) => s + b.cap, 0);
  const pct = Math.round((totalSpent / totalCap) * 100);
  const flagged = budgets_seed
    .filter((b) => budgetStatus(b) !== "ok")
    .sort((a, b) => budgetPct(b) - budgetPct(a));

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Platform Spend · Cost Controls</div>
          <div className="cs">Month-to-date across all clients</div>
        </div>
        <div className="tools">
          <span className="pill-tag ok"><span className="material-symbols-rounded">shield</span>Spend-stop armed</span>
        </div>
      </div>

      <div className="ov-spend-head">
        <span className="ov-spend-big">{usd(totalSpent)}</span>
        <span className="ov-spend-cap">/ {usd(totalCap)} cap · {pct}% used</span>
      </div>
      <div className="ov-spend-bar"><span style={{ width: `${pct}%` }} /></div>

      <div className="ov-flagged">
        {flagged.map((b) => {
          const st = budgetStatus(b);
          return (
            <div key={b.id} className="ov-flag">
              <span className="ov-flag-dot" style={{ background: b.c }} />
              <span className="ov-flag-name">{b.cn}</span>
              <span className="ov-flag-spent">{usd(b.spent)}/{usd(b.cap)}</span>
              <span className="ov-flag-pct" style={{ color: STATUS_COLOR[st] }}>{budgetPct(b)}%</span>
            </div>
          );
        })}
      </div>

      <div className="ov-spend-foot">
        <span>Daily spend-stop at {usd(dailyStopDefault)}/day</span>
        <Link href="/cost" className="ghostbtn">
          Open Cost Controls<span className="material-symbols-rounded">arrow_forward</span>
        </Link>
      </div>
    </section>
  );
}
