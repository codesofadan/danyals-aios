"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { useMembers, useTasks } from "@/lib/hooks/team";
import QueryGuard from "@/components/ui/QueryGuard";

type Tile = {
  icon: string;
  label: string;
  value: number;
  unit?: string;
  note: string;
  hero?: boolean;
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

export default function TeamStats() {
  // The QUERIES, not just their data: `?? []` turns a failed request into a
  // confident animated 0 ("Team members: 0 · Avg. utilization: 0%"), which
  // reads exactly like a real, healthy answer. QueryGuard shows the failure
  // instead of the zero.
  const membersQ = useMembers();
  const tasksQ = useTasks();
  const members = membersQ.data ?? [];
  const tasks = tasksQ.data ?? [];

  // Derived live from the shared roster + task board so the tiles stay honest
  // as members are invited and tasks are assigned during the demo.
  const active = members.filter((m) => m.status !== "invited");
  const headcount = members.length;
  const openTasks = tasks.filter((t) => t.status !== "done").length;
  const avgUtil = active.length ? Math.round(active.reduce((s, m) => s + m.utilization, 0) / active.length) : 0;
  const avgOnTime = active.length ? Math.round(active.reduce((s, m) => s + m.onTime, 0) / active.length) : 0;

  // Live values only — no fabricated period-over-period deltas (there is no
  // historical series to compute a real trend from, so no trend chip is shown).
  const TILES: Tile[] = [
    { icon: "groups", label: "Team members", value: headcount, note: "on the roster", hero: true },
    { icon: "assignment", label: "Active tasks", value: openTasks, note: "across the board" },
    { icon: "bolt", label: "Avg. utilization", value: avgUtil, unit: "%", note: "capacity in use" },
    { icon: "schedule", label: "On-time delivery", value: avgOnTime, unit: "%", note: "of assigned jobs" },
  ];

  return (
    <QueryGuard queries={[membersQ, tasksQ]} label="team stats" minHeight={128}>
      <section className="kpis">
        {TILES.map((t) => (
          <div key={t.label} className={t.hero ? "kpi hero" : "kpi"}>
            <div className="ic"><span className="material-symbols-rounded">{t.icon}</span></div>
            <div className="lab">{t.label}</div>
            <Value value={t.value} unit={t.unit} />
            <div className="sub">{t.note}</div>
          </div>
        ))}
      </section>
    </QueryGuard>
  );
}
