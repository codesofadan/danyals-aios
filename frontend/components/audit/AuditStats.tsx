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

export default function AuditStats({
  runningNow,
  thisMonth,
  avgScore,
  turnaroundMin,
}: {
  runningNow: number;
  thisMonth: number;
  avgScore: number;
  turnaroundMin: number;
}) {
  // Every value is the live figure from GET /audits/stats — no fabricated
  // deltas. On a fresh tenant these read 0, which is the honest current state.
  const tiles: Tile[] = [
    { icon: "fact_check", label: "Audits this month", value: thisMonth, note: "completed + queued this month", hero: true },
    { icon: "speed", label: "Avg. site score", value: avgScore, note: "composite · completed audits" },
    { icon: "play_circle", label: "Running now", value: runningNow, note: "in the job queue" },
    { icon: "timer", label: "Avg. turnaround", value: turnaroundMin, suffix: "m", note: "queued → done" },
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
