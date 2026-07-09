"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { subStatusMix, subTierMix, TIER_PRICE, TIER_COLOR } from "@/lib/data";

const totalAccounts = subStatusMix.reduce((s, x) => s + x.count, 0);
const mrr = subTierMix.reduce((s, t) => s + t.count * TIER_PRICE[t.tier], 0);

// Subscription health — status distribution bar + tier breakdown + MRR.
export default function SubscriptionStatus() {
  const rootRef = useRef<HTMLDivElement>(null);
  const mrrRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const anims: anime.AnimeInstance[] = [];

    root.querySelectorAll<HTMLElement>(".seg-fill").forEach((el) => {
      const target = el.dataset.w || "0%";
      if (reduce) { el.style.width = target; return; }
      anims.push(anime({ targets: el, width: [0, target], duration: 1100, delay: 200, easing: "easeOutExpo" }));
    });

    if (mrrRef.current) {
      const node = mrrRef.current;
      if (reduce) {
        node.textContent = mrr.toLocaleString();
      } else {
        const o = { n: 0 };
        anims.push(anime({ targets: o, n: mrr, duration: 1400, easing: "easeOutExpo", round: 1, update: () => { node.textContent = Math.round(o.n).toLocaleString(); } }));
      }
    }

    return () => anims.forEach((a) => a.pause());
  }, []);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Subscription Status</div>
          <div className="cs">{totalAccounts} accounts across all plans</div>
        </div>
      </div>

      <div ref={rootRef}>
        {/* stacked status distribution */}
        <div className="sub-bar">
          {subStatusMix.map((s) => (
            <div
              key={s.status}
              className="seg-fill"
              data-w={`${(s.count / totalAccounts) * 100}%`}
              style={{ background: s.c }}
              title={`${s.label}: ${s.count}`}
            />
          ))}
        </div>

        <div className="sub-legend">
          {subStatusMix.map((s) => (
            <div className="sub-leg" key={s.status}>
              <span className="dotc" style={{ background: s.c }} />
              <span className="lg-lab">{s.label}</span>
              <span className="lg-n">{s.count}</span>
            </div>
          ))}
        </div>

        <div className="sub-div" />

        {/* tier breakdown */}
        <div className="tier-list">
          {subTierMix.map((t) => (
            <div className="tier-row" key={t.tier}>
              <span className="tier-chip" style={{ color: TIER_COLOR[t.tier], borderColor: TIER_COLOR[t.tier] }}>{t.tier}</span>
              <span className="tier-price">${TIER_PRICE[t.tier]}/mo</span>
              <span className="tier-n">{t.count} clients</span>
            </div>
          ))}
        </div>

        <div className="sub-foot">
          <div>
            <div className="sf-lab">Monthly recurring</div>
            <div className="sf-val">$<span ref={mrrRef}>0</span></div>
          </div>
          <span className="pill-tag warn">
            <span className="material-symbols-rounded">error</span>2 past due
          </span>
        </div>
      </div>
    </section>
  );
}
