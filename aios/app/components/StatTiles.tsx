"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";

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

const TILES: Tile[] = [
  { icon: "fact_check", label: "Free audits this month", value: 1284, delta: "18.2%", deltaDir: "up", note: "vs last month", hero: true },
  { icon: "diversity_3", label: "Active clients", value: 42, delta: "5", deltaDir: "up", note: "onboarded this week" },
  { icon: "bolt", label: "Team utilization", value: 87, unit: "%", delta: "4.1%", deltaDir: "up", note: "across 5 specialists" },
  { icon: "travel_explore", label: "Monthly organic traffic", value: 318, unit: "K", delta: "12.6%", deltaDir: "up", note: "sessions MoM" },
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
      duration: 1400,
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

export default function StatTiles() {
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
