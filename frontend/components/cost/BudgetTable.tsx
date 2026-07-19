"use client";

import { useMemo, useState } from "react";
import {
  budgetPct, budgetStatus, BUDGET_STATUS_META, usd,
  type ClientBudget,
} from "@/lib/cost";

type Props = {
  budgets: ClientBudget[];
  total: { spent: number; cap: number; used: number };
  onEditCap: (id: string, cap: number) => void;
};

const STATUS_COLOR: Record<string, string> = { ok: "var(--ok)", warn: "var(--warn)", crit: "var(--crit)" };

export default function BudgetTable({ budgets, total, onEditCap }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState(0);

  // Near-cap and over clients float to the top so risk is visible first.
  const sorted = useMemo(
    () => [...budgets].sort((a, b) => budgetPct(b) - budgetPct(a)),
    [budgets],
  );
  const flagged = budgets.filter((b) => budgetStatus(b) !== "ok").length;

  function startEdit(b: ClientBudget) {
    setEditing(b.id);
    setDraft(b.cap);
  }
  function commit(id: string) {
    onEditCap(id, Math.max(0, Math.round(draft)));
    setEditing(null);
  }

  return (
    <section className="card cst-budget">
      <div className="card-h">
        <div>
          <div className="ct">Per-Client Budgets</div>
          <div className="cs">Monthly spend ceilings on the job queue — highest usage first.</div>
        </div>
        <div className="tools">
          <span className={`pill-tag ${flagged ? "warn" : "ok"}`}>
            <span className="material-symbols-rounded">{flagged ? "notification_important" : "check_circle"}</span>
            {flagged ? `${flagged} near / over cap` : "All within cap"}
          </span>
        </div>
      </div>

      <div className="tbl-wrap cst-budget-wrap">
        <table className="tbl cst-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Tier</th>
              <th className="num">Monthly cap</th>
              <th className="num">Spent</th>
              <th className="num">Remaining</th>
              <th className="cst-usecol">Usage</th>
              <th>Status</th>
              <th className="num"></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((b) => {
              const pct = budgetPct(b);
              const st = budgetStatus(b);
              const remaining = b.cap - b.spent;
              const isEditing = editing === b.id;
              return (
                <tr key={b.id} className={st !== "ok" ? `cst-flag ${st}` : ""}>
                  <td>
                    <div className="cst-cli">
                      <span className="cst-cli-dot" style={{ background: b.c }} />
                      <span className="cst-cli-nm">{b.cn}</span>
                    </div>
                  </td>
                  <td><span className="cst-tier">{b.tier}</span></td>
                  <td className="num cst-cap">
                    {isEditing ? (
                      <span className="cst-cap-edit">
                        <span>$</span>
                        <input
                          type="number"
                          min={0}
                          step={10}
                          autoFocus
                          value={draft}
                          onChange={(e) => setDraft(Number(e.target.value) || 0)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commit(b.id);
                            if (e.key === "Escape") setEditing(null);
                          }}
                        />
                      </span>
                    ) : (
                      usd(b.cap)
                    )}
                  </td>
                  <td className="num">{usd(b.spent)}</td>
                  <td className={`num cst-rem ${remaining < 0 ? "over" : ""}`}>
                    {remaining < 0 ? `−${usd(Math.abs(remaining))}` : usd(remaining)}
                  </td>
                  <td className="cst-usecol">
                    <div className="cst-use">
                      <div className="cst-use-bar">
                        <span style={{ width: `${Math.min(pct, 100)}%`, background: STATUS_COLOR[st] }} />
                      </div>
                      <span className="cst-use-n">{pct}%</span>
                    </div>
                  </td>
                  <td>
                    <span className={`status-pill ${BUDGET_STATUS_META[st].cls === "crit" ? "warn" : BUDGET_STATUS_META[st].cls}`}
                      style={st === "crit" ? { color: "var(--crit)", background: "rgba(183,67,85,.15)" } : undefined}>
                      {BUDGET_STATUS_META[st].label}
                    </span>
                  </td>
                  <td className="num">
                    {isEditing ? (
                      <button className="primary-btn sm" onClick={() => commit(b.id)}>
                        <span className="material-symbols-rounded">check</span>Save
                      </button>
                    ) : (
                      <button className="mini-btn" onClick={() => startEdit(b)}>
                        <span className="material-symbols-rounded">edit</span>Cap
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="cst-budget-foot">
        <span>Combined caps <b>{usd(total.cap)}</b> · spent <b>{usd(total.spent)}</b> · {total.used}% used across {budgets.length} clients</span>
        <span className="cst-foot-hint">Caps live on the job queue — a job is skipped once its client is over cap.</span>
      </div>
    </section>
  );
}
