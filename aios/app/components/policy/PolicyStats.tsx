"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { sources, changeEvents, recommendations, kbEntries, REC_OPEN } from "@/lib/policy";

type Tile = {
  icon: string;
  label: string;
  value: number;
  unit?: string;
  delta: string;
  deltaDir: "up" | "down";
  note: string;
  hero?: boolean;
};

const openRecs = recommendations.filter((r) => REC_OPEN.includes(r.status)).length;

const TILES: Tile[] = [
  { icon: "radar", label: "Sources watched", value: sources.length, delta: "live", deltaDir: "up", note: "monitored continuously", hero: true },
  { icon: "change_circle", label: "Changes detected (7d)", value: changeEvents.length, delta: "3", deltaDir: "up", note: "vs. prior week" },
  { icon: "recommend", label: "Open recommendations", value: openRecs, delta: "2", deltaDir: "up", note: "awaiting human confirm" },
  { icon: "library_books", label: "KB entries", value: kbEntries.length, delta: "4", deltaDir: "up", note: "versioned & cited" },
];

function useCountUp(target: number) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = target.toLocaleString();
      return;
    }
    const obj = { n: 0 };
    const anim = anime({
      targets: obj,
      n: target,
      duration: 1300,
      easing: "easeOutExpo",
      update: () => { node.textContent = Math.round(obj.n).toLocaleString(); },
    });
    return () => anim.pause();
  }, [target]);
  return ref;
}

function Value({ value, unit }: { value: number; unit?: string }) {
  const ref = useCountUp(value);
  return (
    <div className="val">
      <span ref={ref}>0</span>
      {unit && <span className="u">{unit}</span>}
    </div>
  );
}

export default function PolicyStats() {
  return (
    <section className="kpis">
      {TILES.map((t) => (
        <div key={t.label} className={t.hero ? "kpi hero" : "kpi"}>
          <div className="ic"><span className="material-symbols-rounded">{t.icon}</span></div>
          <div className="lab">{t.label}</div>
          <Value value={t.value} unit={t.unit} />
          <div className="sub">
            <span className={`delta ${t.deltaDir}`}>
              <span className="material-symbols-rounded">
                {t.deltaDir === "up" ? "trending_up" : "trending_down"}
              </span>
              {t.delta}
            </span>{" "}
            {t.note}
          </div>
        </div>
      ))}
    </section>
  );
}
