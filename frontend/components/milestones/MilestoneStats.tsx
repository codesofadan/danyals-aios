"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { projectProgress } from "@/lib/milestones";
import { useMilestones } from "@/lib/hooks/milestones";

type Tile = {
  icon: string; label: string; value: number; unit?: string; suffix?: string;
  delta: string; deltaDir: "up" | "down"; note: string; hero?: boolean;
};

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
      targets: obj, n: target, duration: 1400, easing: "easeOutExpo",
      update: () => { node.textContent = Math.round(obj.n).toLocaleString(); },
    });
    return () => anim.pause();
  }, [target]);
  return ref;
}

function Value({ value, unit, suffix }: { value: number; unit?: string; suffix?: string }) {
  const ref = useCountUp(value);
  return (
    <div className="val">
      <span ref={ref}>0</span>
      {suffix && <span className="u">{suffix}</span>}
      {unit && <span className="u">{unit}</span>}
    </div>
  );
}

export default function MilestoneStats() {
  const projects = useMilestones().data ?? [];

  // Derived from the live projects so the tiles stay honest.
  const active = projects.filter((p) => p.health !== "completed").length;
  const completedStages = projects.reduce((s, p) => s + p.stages.filter((st) => st.status === "completed").length, 0);
  const onTrack = projects.filter((p) => p.health === "on_track" || p.health === "completed").length;
  const atRisk = projects.filter((p) => p.health === "at_risk").length;
  const avgPct = projects.length
    ? Math.round(projects.reduce((s, p) => s + projectProgress(p), 0) / projects.length)
    : 0;

  const TILES: Tile[] = [
    { icon: "flag", label: "Active projects", value: active, delta: "1", deltaDir: "up", note: `of ${projects.length} tracked`, hero: true },
    { icon: "task_alt", label: "Milestones completed", value: completedStages, delta: "6", deltaDir: "up", note: "this month, auto-advanced" },
    { icon: "monitoring", label: "On-track vs at-risk", value: onTrack, suffix: ` / ${atRisk}`, delta: `${atRisk}`, deltaDir: atRisk > 1 ? "down" : "up", note: "at-risk need attention" },
    { icon: "donut_large", label: "Avg. completion", value: avgPct, unit: "%", delta: "5%", deltaDir: "up", note: "across all projects" },
  ];

  return (
    <section className="kpis">
      {TILES.map((t) => (
        <div key={t.label} className={t.hero ? "kpi hero" : "kpi"}>
          <div className="ic"><span className="material-symbols-rounded">{t.icon}</span></div>
          <div className="lab">{t.label}</div>
          <Value value={t.value} unit={t.unit} suffix={t.suffix} />
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
