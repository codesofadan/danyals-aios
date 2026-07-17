"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import type { CCClientPoint } from "@/lib/hooks/commandCenter";

const R = 44;
const CIRC = 2 * Math.PI * R;
const RAMP = ["#EBFFB8", "#D6FF6B", "#C6FF3C", "#A6E62A", "#7FB814"]; // lime ordinal
const colorFor = (p: number) => RAMP[Math.min(RAMP.length - 1, Math.floor((p / 100) * RAMP.length))];

// Active client progress — animated SVG rings + counting % (anime.js).
export default function ClientProgress({ clients }: { clients: CCClientPoint[] }) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const anims: anime.AnimeInstance[] = [];
    root.querySelectorAll<SVGCircleElement>(".ring").forEach((_, idx) => {
      const ring = root.querySelectorAll<HTMLElement>(".ring")[idx];
      const prog = ring.querySelector<SVGCircleElement>(".prog")!;
      const pv = ring.querySelector<HTMLElement>(".pv")!;
      const p = clients[idx].p;
      const offset = CIRC * (1 - p / 100);
      if (reduce) {
        prog.style.strokeDashoffset = String(offset);
        pv.textContent = String(p);
        return;
      }
      anims.push(anime({ targets: prog, strokeDashoffset: [CIRC, offset], duration: 1500, delay: 250 + idx * 90, easing: "easeInOutCubic" }));
      const o = { n: 0 };
      anims.push(anime({ targets: o, n: p, duration: 1500, delay: 250 + idx * 90, easing: "easeInOutCubic", round: 1, update: () => { pv.textContent = String(o.n); } }));
    });

    return () => anims.forEach((a) => a.pause());
  }, [clients]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Active Client Progress</div>
          <div className="cs">Milestone completion · auto-updated from jobs</div>
        </div>
      </div>

      <div className="rings" ref={rootRef}>
        {clients.map((c) => (
          <div className="ring" key={c.cn}>
            <div className="dial">
              <svg width="104" height="104" viewBox="0 0 104 104">
                <circle className="track" cx="52" cy="52" r={R} />
                <circle
                  className="prog" cx="52" cy="52" r={R}
                  stroke={colorFor(c.p)}
                  strokeDasharray={CIRC}
                  strokeDashoffset={CIRC}
                />
              </svg>
              <div className="pct">
                <div className="p"><span className="pv">0</span><span className="u">%</span></div>
              </div>
            </div>
            <div className="meta">
              <div className="cn">{c.cn}</div>
              <div className="cd">{c.cd}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
