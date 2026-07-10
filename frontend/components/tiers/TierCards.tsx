import type { CSSProperties } from "react";
import { TIERS, type TierKey } from "@/lib/tiers";

// Three preset comparison cards. `counts` shows live client distribution.
export default function TierCards({ counts }: { counts: Record<TierKey, number> }) {
  return (
    <div className="tr-plans">
      {TIERS.map((t) => (
        <div
          key={t.key}
          className={t.popular ? "tr-plan pop" : "tr-plan"}
          style={{ "--tc": t.c } as CSSProperties}
        >
          {t.popular && <div className="tr-ribbon">Most popular</div>}
          <div className="tr-plan-h">
            <span className="tr-dot" />
            <div>
              <div className="tr-name">{t.name}</div>
              <div className="tr-tag">{t.tagline}</div>
            </div>
          </div>

          <div className="tr-price">
            <span className="tr-cur">$</span>
            {t.price}
            <span className="tr-per">/client/mo</span>
          </div>
          <div className="tr-blurb">{t.blurb}</div>

          <div className="tr-count">
            <b>{counts[t.key]}</b> {counts[t.key] === 1 ? "client" : "clients"} on this tier
          </div>

          <ul className="tr-feat">
            {t.unlocks.map((u) => (
              <li key={u}>
                <span className="material-symbols-rounded">check</span>
                {u}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
