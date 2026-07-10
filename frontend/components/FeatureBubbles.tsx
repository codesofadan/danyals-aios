"use client";

import Link from "next/link";
import { useState } from "react";
import { featureModules, type Feature } from "@/lib/features";

type Tip = { name: string; blurb: string; x: number; y: number; below: boolean } | null;

// Grouped grid of feature bubbles. Each bubble carries a unique Material
// Icon; hovering (or focusing) reveals a tooltip with the full name +
// blurb; clicking navigates to that feature's page. Used by the Features
// popup and the /features page. Tooltip is fixed-positioned so it never
// clips inside the scrolling modal body.
export default function FeatureBubbles({ onNavigate }: { onNavigate?: () => void }) {
  const [tip, setTip] = useState<Tip>(null);

  const show = (e: React.SyntheticEvent<HTMLAnchorElement>, f: Feature) => {
    const r = e.currentTarget.getBoundingClientRect();
    const below = r.top < 108; // flip under the bubble when near the top edge
    setTip({
      name: f.name,
      blurb: f.blurb,
      x: r.left + r.width / 2,
      y: below ? r.bottom + 10 : r.top - 10,
      below,
    });
  };
  const hide = () => setTip(null);

  return (
    <>
      {featureModules.map((m) => (
        <section className="feat-module" key={m.id}>
          <div className="feat-module-h">
            <span className="mnum">{m.num}</span>
            <div>
              <div className="mname">{m.name}</div>
              <div className="mtag">{m.tagline}</div>
            </div>
            <span className={`ftier ${m.tag.cls}`}>{m.tag.label}</span>
          </div>

          <div className="feat-grid">
            {m.features.map((f) => (
              <Link
                key={f.slug}
                href={`/features/${f.slug}`}
                className="feat-bubble"
                onClick={onNavigate}
                onMouseEnter={(e) => show(e, f)}
                onMouseLeave={hide}
                onFocus={(e) => show(e, f)}
                onBlur={hide}
                aria-label={f.name}
              >
                <span className="medallion">
                  <span className="material-symbols-rounded">{f.icon}</span>
                </span>
                <span className="blab">{f.label}</span>
                <span className={`tdot ${f.tier}`} aria-hidden="true" />
              </Link>
            ))}
          </div>
        </section>
      ))}

      {tip && (
        <div
          className={`feat-tooltip${tip.below ? " below" : ""}`}
          style={{ left: tip.x, top: tip.y }}
          role="tooltip"
        >
          <div className="tt-name">{tip.name}</div>
          <div className="tt-blurb">{tip.blurb}</div>
        </div>
      )}
    </>
  );
}
