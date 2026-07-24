"use client";

import { usd } from "@/lib/cost";

type Props = {
  halted: boolean;
  todaySpent: number;
  onToggle: () => void;
  pending?: boolean;
};

// The global API-spend HALT: a single, manual, agency-wide kill-switch (owner/admin).
// When engaged the cost gate blocks EVERY metered feature (audits, content, policy
// ask, keyword/rank/embeddings/image, every paid call) - no provider is called and
// no cost is logged - until it is toggled off. It replaced the old per-day dollar
// spend-stop threshold, so there is no number to tune here: it is on or off.
export default function SpendStopCard({ halted, todaySpent, onToggle, pending }: Props) {
  const live = !halted;
  return (
    <section className={`card cst-stop ${live ? "armed" : "tripped"}`}>
      <div className="card-h">
        <div>
          <div className="ct">API Spend Halt</div>
          <div className="cs">Manual global kill-switch for every paid provider call.</div>
        </div>
        <div className="tools">
          <span className={`pill-tag ${live ? "ok" : "warn"}`}>
            <span className="material-symbols-rounded">{live ? "verified_user" : "gpp_bad"}</span>
            {live ? "Providers live" : "Halted"}
          </span>
        </div>
      </div>

      <div className="cst-stop-body">
        <button
          type="button"
          className={`cst-stop-toggle ${live ? "armed" : "tripped"}`}
          onClick={onToggle}
          disabled={pending}
          aria-pressed={halted}
        >
          <span className="cst-stop-ring">
            <span className="material-symbols-rounded">{live ? "power_settings_new" : "block"}</span>
          </span>
          <span className="cst-stop-tt">
            <span className="cst-stop-state">{live ? "Providers live" : "API spend is halted"}</span>
            <span className="cst-stop-act">
              {pending ? "Saving…" : live ? "Tap to HALT all paid calls" : "Tap to resume providers"}
            </span>
          </span>
        </button>

        <div className="cst-thr">
          <div className="cst-thr-today" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
            <div className="cst-thr-today-row">
              <span>Paid spend today</span>
              <b>{usd(todaySpent, 2)}</b>
            </div>
            <div className="cst-thr-today-cap">
              Informational only. The halt is a manual switch, not a spend threshold.
            </div>
          </div>
        </div>
      </div>

      <div className={`cst-stop-note ${live ? "" : "crit"}`}>
        <span className="material-symbols-rounded">{live ? "info" : "warning"}</span>
        <span>
          {live
            ? <>Providers are calling normally. Engage the halt to <b>instantly pause every paid feature</b> across the platform. Audits, content, policy ask and every metered tool stop spending at once.</>
            : <><b>API spend is halted.</b> Every paid call is refused platform-wide (audits, content, policy ask, keyword/rank/embeddings/image). Turn it off to restore normal dial-governed behavior.</>}
        </span>
      </div>
    </section>
  );
}
