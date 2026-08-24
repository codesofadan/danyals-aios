"use client";

import { DIAL_MODES, DIAL_MODE_META, pricingSummary, providerMeta, type DialFeature, type DialMode } from "@/lib/cost";
import { useProviderPricing } from "@/lib/hooks/cost";

type Props = {
  dial: DialFeature[];
  onSetMode: (key: string, mode: DialMode) => void;
  halted?: boolean;
};

export default function CostDial({ dial, onSetMode, halted = false }: Props) {
  const live = dial.filter((d) => d.mode === "api").length;
  // Live unit prices from GET /cost/pricing — the same Settings values the cost
  // gate bills at. While it loads (or if it fails) the row simply shows no price
  // rather than a placeholder figure: an absent number beats an invented one.
  const pricingQ = useProviderPricing();
  const priceByProvider = new Map((pricingQ.data ?? []).map((p) => [p.provider, p]));

  return (
    <section className="card cst-dial">
      <div className="card-h">
        <div>
          <div className="ct">Cost Dial</div>
          <div className="cs">Per-feature mode. Cost is a dial, not a switch.</div>
        </div>
        <div className="tools">
          {halted ? (
            <span className="pill-tag warn">
              <span className="material-symbols-rounded">block</span>All paused
            </span>
          ) : (
            <span className="pill-tag"><span className="material-symbols-rounded">tune</span>{live} on API</span>
          )}
        </div>
      </div>

      {halted && (
        <div className="cst-dial-halt" role="status">
          <span className="material-symbols-rounded">warning</span>
          <span>API spend is halted, so every dial is <b>effectively off</b> right now. Resume spend to restore these settings.</span>
        </div>
      )}

      <div className={`cst-dial-list ${halted ? "halted" : ""}`}>
        {dial.map((d) => {
          const pv = providerMeta(d.provider);
          const price = pricingSummary(priceByProvider.get(d.provider));
          return (
            <div key={d.key} className="cst-dial-row">
              <span className="cst-dial-ic" style={{ color: pv.c, background: `${pv.c}22` }}>
                <span className="material-symbols-rounded">{d.icon}</span>
              </span>
              <div className="cst-dial-main">
                <div className="cst-dial-name">{d.label}</div>
                <div className="cst-dial-sub">
                  <b style={{ color: pv.c }}>{d.provider}</b> · {d.note}
                  {price && <> · <span title={`Live unit price for ${d.provider}`}>{price}</span></>}
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
