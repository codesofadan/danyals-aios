"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";

type Tile = {
  icon: string;
  label: string;
  value: number;
  decimals?: number;
  unit?: string;
  suffix?: string;
  delta?: string;
  deltaDir?: "up" | "down";
  note: string;
  hero?: boolean;
};

function useCountUp(target: number, decimals = 0) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = target.toFixed(decimals);
      return;
    }
    const obj = { n: 0 };
    const anim = anime({
      targets: obj, n: target, duration: 1400, easing: "easeOutExpo",
      update: () => { node.textContent = obj.n.toFixed(decimals); },
    });
    return () => anim.pause();
  }, [target, decimals]);
  return ref;
}

function Value({ value, decimals, unit, suffix }: { value: number; decimals?: number; unit?: string; suffix?: string }) {
  const ref = useCountUp(value, decimals);
  return (
    <div className="val">
      <span ref={ref}>0</span>
      {unit && <span className="u">{unit}</span>}
      {suffix && <span className="u">{suffix}</span>}
    </div>
  );
}

export default function AuditStats({ runningNow, thisMonth }: { runningNow: number; thisMonth: number }) {
  const tiles: Tile[] = [
    { icon: "fact_check", label: "Audits this month", value: thisMonth, delta: "18", deltaDir: "up", note: "vs. last month", hero: true },
    { icon: "speed", label: "Avg. site score", value: 76, delta: "2.4", deltaDir: "up", note: "composite · rolling 30d" },
    { icon: "play_circle", label: "Running now", value: runningNow, note: "in the job queue" },
    { icon: "timer", label: "Avg. turnaround", value: 6, suffix: "m", delta: "0.8m", deltaDir: "down", note: "queued → done" },
  ];
  return (
    <section className="kpis">
      {tiles.map((t) => (
        <div key={t.label} className={t.hero ? "kpi hero" : "kpi"}>
          <div className="ic"><span className="material-symbols-rounded">{t.icon}</span></div>
          <div className="lab">{t.label}</div>
          <Value value={t.value} decimals={t.decimals} unit={t.unit} suffix={t.suffix} />
          <div className="sub">
            {t.delta ? (
              <>
                <span className={`delta ${t.deltaDir}`}>
                  <span className="material-symbols-rounded">{t.deltaDir === "up" ? "trending_up" : "trending_down"}</span>
                  {t.delta}
                </span>{" "}
                {t.note}
              </>
            ) : (
              t.note
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
