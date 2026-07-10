"use client";

type Props = {
  armed: boolean;
  threshold: number;
  onToggle: () => void;
  onThreshold: (v: number) => void;
};

export default function SpendStopCard({ armed, threshold, onToggle, onThreshold }: Props) {
  return (
    <section className={`card cst-stop ${armed ? "armed" : "tripped"}`}>
      <div className="card-h">
        <div>
          <div className="ct">Daily Spend-Stop</div>
          <div className="cs">Emergency global halt for every paid provider.</div>
        </div>
        <div className="tools">
          <span className={`pill-tag ${armed ? "ok" : "warn"}`}>
            <span className="material-symbols-rounded">{armed ? "verified_user" : "gpp_bad"}</span>
            {armed ? "Armed" : "Tripped"}
          </span>
        </div>
      </div>

      <div className="cst-stop-body">
        <button
          type="button"
          className={`cst-stop-toggle ${armed ? "armed" : "tripped"}`}
          onClick={onToggle}
          aria-pressed={!armed}
        >
          <span className="cst-stop-ring">
            <span className="material-symbols-rounded">{armed ? "power_settings_new" : "block"}</span>
          </span>
          <span className="cst-stop-tt">
            <span className="cst-stop-state">{armed ? "Providers live" : "Spend halted"}</span>
            <span className="cst-stop-act">{armed ? "Tap to trip the stop" : "Tap to re-arm providers"}</span>
          </span>
        </button>

        <div className="cst-thr">
          <label htmlFor="cst-thr-in">Daily threshold</label>
          <div className="cst-thr-in">
            <span className="cst-thr-cur">$</span>
            <input
              id="cst-thr-in"
              type="number"
              min={0}
              step={5}
              value={threshold}
              onChange={(e) => onThreshold(Math.max(0, Number(e.target.value) || 0))}
            />
            <span className="cst-thr-unit">/ day</span>
          </div>
          <div className="cst-thr-hint">
            Auto-trips if a single day&apos;s paid spend crosses this line.
          </div>
        </div>
      </div>

      <div className={`cst-stop-note ${armed ? "" : "crit"}`}>
        <span className="material-symbols-rounded">{armed ? "info" : "warning"}</span>
        <span>
          {armed
            ? <>Providers are calling normally. If a misbehaving run spikes cost, the stop trips automatically so <b>data volume can never become a surprise bill</b>.</>
            : <>All paid calls are stubbed and queued. Audits, content and backlink jobs run on cached data only until you re-arm.</>}
        </span>
      </div>
    </section>
  );
}
