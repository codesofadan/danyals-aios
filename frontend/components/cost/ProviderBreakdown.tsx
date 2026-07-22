"use client";

import { providerLabel, providerMeta, usd, type Provider } from "@/lib/cost";

type Props = { data: { provider: Provider; amount: number }[]; total: number };

export default function ProviderBreakdown({ data, total }: Props) {
  const max = Math.max(...data.map((d) => d.amount), 1);
  const sorted = [...data].sort((a, b) => b.amount - a.amount);
  const denom = total > 0 ? total : 1; // guard: an empty month must not render NaN%

  return (
    <section className="card cst-prov-card">
      <div className="card-h">
        <div>
          <div className="ct">Spend by Provider</div>
          <div className="cs">Where the month&apos;s paid calls went.</div>
        </div>
        <div className="tools">
          <span className="pill-tag"><span className="material-symbols-rounded">receipt_long</span>{usd(total)}</span>
        </div>
      </div>

      <div className="cst-prov-list">
        {sorted.map((d) => {
          // Tolerant lookup — the log's provider strings are free-form.
          const pv = providerMeta(d.provider);
          const pct = Math.round((d.amount / denom) * 100);
          return (
            <div key={d.provider} className="cst-prov-row">
              <div className="cst-prov-top">
                <span className="cst-prov-nm">
                  <span className="cst-prov-dot" style={{ background: pv.c }} />
                  {providerLabel(d.provider)}
                  {!pv.paid && <span className="cst-prov-free">free</span>}
                </span>
                <span className="cst-prov-amt">{usd(d.amount)}<span className="cst-prov-pct">{pct}%</span></span>
              </div>
              <div className="cst-prov-track">
                <span style={{ width: `${(d.amount / max) * 100}%`, background: pv.c }} />
              </div>
              <div className="cst-prov-use">{pv.use} · {pv.unit}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
