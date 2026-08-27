"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";

type Tile = {
  icon: string;
  label: string;
  value: number;
  decimals?: number;
  prefix?: string;
  unit?: string;
  suffix?: string;
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

function Value({
  value, decimals, prefix, unit, suffix,
}: { value: number; decimals?: number; prefix?: string; unit?: string; suffix?: string }) {
  const ref = useCountUp(value, decimals);
  return (
    <div className="val">
      {prefix && <span className="u">{prefix}</span>}
      <span ref={ref}>0</span>
      {unit && <span className="u">{unit}</span>}
      {suffix && <span className="u">{suffix}</span>}
    </div>
  );
}

export default function AuditStats({
  lifetime,
  thisMonth,
  runningNow,
  avgCostUsd,
}: {
  lifetime: number;
  thisMonth: number;
  runningNow: number;
  avgCostUsd: number;
}) {
  // Every value is the live figure from GET /audits/stats - no fabricated deltas.
  // On a fresh tenant these read 0, which is the honest current state.
  //
  // `avgCostUsd` carries ONE decimal, by owner decision. Four decimals were
  // chosen so a month of mostly free-tier runs did not round its sub-cent mean to
  // $0.00 - but the tile they actually produce reads `$0.0000`, which is four
  // digits of nothing. The trade is accepted knowingly: a real mean reads $13.5
  // or $69.2, and a genuine fraction of a cent now reads $0.0. The per-run cost
  // in the queue still carries cents, because that one is a bill.
  const tiles: Tile[] = [
    { icon: "history", label: "Lifetime audits", value: lifetime, note: "every run, all time", hero: true },
    { icon: "fact_check", label: "Audits this month", value: thisMonth, note: "completed + queued this month" },
    { icon: "play_circle", label: "Running now", value: runningNow, note: "in the job queue" },
    {
      icon: "payments",
      label: "Avg. audit cost",
      value: avgCostUsd,
      decimals: 1,
      prefix: "$",
      note: "committed spend · completed runs",
    },
  ];
  return (
    <section className="kpis">
      {tiles.map((t) => (
        <div key={t.label} className={t.hero ? "kpi hero" : "kpi"}>
          <div className="ic"><span className="material-symbols-rounded">{t.icon}</span></div>
          <div className="lab">{t.label}</div>
          <Value value={t.value} decimals={t.decimals} prefix={t.prefix} unit={t.unit} suffix={t.suffix} />
          <div className="sub">{t.note}</div>
        </div>
      ))}
    </section>
  );
}
