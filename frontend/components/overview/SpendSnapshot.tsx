import Link from "next/link";
import { budgetStatus, usd, type BudgetStatus } from "@/lib/cost";
import type { CCSpendSnapshot } from "@/lib/hooks/commandCenter";

const STATUS_COLOR: Record<BudgetStatus, string> = {
  ok: "var(--ok)", warn: "var(--warn)", crit: "var(--crit)",
};

// Platform spend snapshot for the main dashboard — month-to-date across all
// clients, plus the near/over-cap accounts. Fed from GET /command-center
// (`spend`, already rolled up + flagged worst-first). Full controls live in /cost.
export default function SpendSnapshot({ spend }: { spend: CCSpendSnapshot }) {
  const { totalSpent, totalCap, pct, flagged, dailyStop } = spend;

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
            <div key={b.cn} className="ov-flag">
              <span className="ov-flag-dot" style={{ background: b.c }} />
              <span className="ov-flag-name">{b.cn}</span>
              <span className="ov-flag-spent">{usd(b.spent)}/{usd(b.cap)}</span>
              <span className="ov-flag-pct" style={{ color: STATUS_COLOR[st] }}>{b.pct}%</span>
            </div>
          );
        })}
      </div>

      <div className="ov-spend-foot">
        <span>Daily spend-stop at {usd(dailyStop)}/day</span>
        <Link href="/admin/cost" className="ghostbtn">
          Open Cost Controls<span className="material-symbols-rounded">arrow_forward</span>
        </Link>
      </div>
    </section>
  );
}
