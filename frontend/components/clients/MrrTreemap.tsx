"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import { clientDirectory, TIER_COLOR, type SubTier } from "@/lib/data";

// Revenue treemap — MRR by plan tier. Each tier is a column sized by its
// share of total MRR; inside it every client is a tile sized by its own
// MRR. Proportional area = revenue, so the book's shape reads at a glance.
// Layout is proportional flexbox (area ∝ value); colour follows the tier.

const TIER_ORDER: SubTier[] = ["Scale", "Growth", "Starter"];
const usd = (n: number) => "$" + n.toLocaleString("en-US");

export default function MrrTreemap() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);

  // Only revenue-bearing accounts have area on the map (paused = $0).
  const paying = clientDirectory.filter((c) => c.mrr > 0);
  const totalMrr = paying.reduce((s, c) => s + c.mrr, 0);
  const paused = clientDirectory.length - paying.length;

  const groups = TIER_ORDER.map((tier) => {
    const items = paying
      .filter((c) => c.tier === tier)
      .sort((a, b) => b.mrr - a.mrr);
    const sum = items.reduce((s, c) => s + c.mrr, 0);
    return { tier, items, sum };
  }).filter((g) => g.sum > 0);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const tiles = root.querySelectorAll<HTMLElement>(".tm-tile");
    const a = anime({
      targets: tiles,
      opacity: [0, 1],
      scale: [0.86, 1],
      duration: 620,
      delay: anime.stagger(50, { start: 120 }),
      easing: "easeOutCubic",
    });
    return () => a.pause();
  }, []);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Revenue Treemap</div>
          <div className="cs">Monthly recurring revenue by plan tier · tile area = each account&apos;s MRR</div>
        </div>
        <div className="tools">
          <span className="pill-tag"><span className="material-symbols-rounded">payments</span>{usd(totalMrr)}/mo</span>
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      <div className="tmap" ref={rootRef}>
        {groups.map((g) => (
          <div className="tmap-group" key={g.tier} style={{ flexGrow: g.sum }}>
            <div className="tmap-group-h">
              <span className="tmap-dot" style={{ background: TIER_COLOR[g.tier] }} />
              {g.tier}
              <span className="tmap-group-sum">{usd(g.sum)}</span>
            </div>
            <div className="tmap-tiles">
              {g.items.map((c) => (
                <div
                  className="tm-tile"
                  key={c.id}
                  style={{ flexGrow: c.mrr, background: TIER_COLOR[g.tier] }}
                  title={`${c.cn} · ${usd(c.mrr)}/mo`}
                >
                  <span className="tm-tile-cn">{c.cn}</span>
                  <span className="tm-tile-mrr">{usd(c.mrr)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="tmap-foot">
        <span>{paying.length} paying accounts</span>
        {paused > 0 && <span className="tmap-dot-sep">·</span>}
        {paused > 0 && <span>{paused} paused / $0 (no area)</span>}
      </div>

      <div className={showTable ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Client</th><th>Tier</th><th>MRR</th></tr></thead>
          <tbody>
            {[...clientDirectory].sort((a, b) => b.mrr - a.mrr).map((c) => (
              <tr key={c.id}><td>{c.cn}</td><td>{c.tier}</td><td>{usd(c.mrr)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
