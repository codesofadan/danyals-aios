"use client";

import { DIAL_MODES, DIAL_MODE_META, providerMeta, type DialFeature, type DialMode } from "@/lib/cost";

type Props = { dial: DialFeature[]; onSetMode: (key: string, mode: DialMode) => void };

export default function CostDial({ dial, onSetMode }: Props) {
  const live = dial.filter((d) => d.mode === "api").length;

  return (
    <section className="card cst-dial">
      <div className="card-h">
        <div>
          <div className="ct">Cost Dial</div>
          <div className="cs">Per-feature mode — cost is a dial, not a switch.</div>
        </div>
        <div className="tools">
          <span className="pill-tag"><span className="material-symbols-rounded">tune</span>{live} on API</span>
        </div>
      </div>

      <div className="cst-dial-list">
        {dial.map((d) => {
          const pv = providerMeta(d.provider);
          return (
            <div key={d.key} className="cst-dial-row">
              <span className="cst-dial-ic" style={{ color: pv.c, background: `${pv.c}22` }}>
                <span className="material-symbols-rounded">{d.icon}</span>
              </span>
              <div className="cst-dial-main">
                <div className="cst-dial-name">{d.label}</div>
                <div className="cst-dial-sub">
                  <b style={{ color: pv.c }}>{d.provider}</b> · {d.note}
                </div>
              </div>
              <div className="cst-dial-seg" role="group" aria-label={`${d.label} mode`}>
                {DIAL_MODES.map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={`cst-mode ${m} ${d.mode === m ? "on" : ""}`}
                    onClick={() => onSetMode(d.key, m)}
                    aria-pressed={d.mode === m}
                    title={DIAL_MODE_META[m].label}
                  >
                    <span className="material-symbols-rounded">{DIAL_MODE_META[m].icon}</span>
                    <span className="cst-mode-l">{DIAL_MODE_META[m].label}</span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="cst-dial-foot">
        <span><span className="cst-lg api" /> API · calls the paid provider</span>
        <span><span className="cst-lg byhand" /> By hand · queued for review</span>
        <span><span className="cst-lg off" /> Off · stubbed / skipped</span>
      </div>
    </section>
  );
}
