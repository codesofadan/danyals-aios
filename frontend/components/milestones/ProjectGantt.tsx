"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import {
  projects, LIFECYCLE, STAGE_STATUS_META, currentStage,
  type ClientProject,
} from "@/lib/milestones";

// Project lifecycle Gantt — one swimlane per client across the five
// lifecycle phases (the time axis). Each stage is a horizontal bar
// coloured by its status; completed stages read solid, the current
// stage pulses, upcoming stages are faint. A distinct time-bar view of
// the same auto-advancing timeline the stepper shows below.

const N = LIFECYCLE.length;

// A stage's bar fill proportion within its column (visual "progress").
function fillFor(status: string): number {
  if (status === "completed") return 1;
  if (status === "in_progress") return 0.55;
  if (status === "blocked") return 0.35;
  return 0; // upcoming
}

export default function ProjectGantt() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ x: number; y: number; html: string } | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      root.querySelectorAll<HTMLElement>(".gantt-fill").forEach((el) => {
        el.style.transform = "scaleX(1)";
      });
      return;
    }
    const bars = root.querySelectorAll<HTMLElement>(".gantt-fill");
    const a = anime({
      targets: bars,
      scaleX: [0, 1],
      duration: 780,
      delay: anime.stagger(45, { start: 150 }),
      easing: "easeOutCubic",
    });
    return () => a.pause();
  }, []);

  const showTip = (e: React.PointerEvent, p: ClientProject, idx: number) => {
    const stage = p.stages[idx];
    const meta = STAGE_STATUS_META[stage.status];
    const host = rootRef.current;
    if (!host) return;
    const r = host.getBoundingClientRect();
    setTip({
      x: e.clientX - r.left,
      y: e.clientY - r.top,
      html: `<span class="k">${p.client} · ${LIFECYCLE[idx].label}</span><br><span class="v">${meta.label}</span> <span class="k">· ${stage.updated_at}</span>`,
    });
  };

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Delivery Timeline</div>
          <div className="cs">Every client across the five lifecycle phases · stages auto-advance from job &amp; audit status</div>
        </div>
        <div className="tools">
          <div className="gantt-legend">
            {(["completed", "in_progress", "upcoming", "blocked"] as const).map((s) => (
              <span key={s} className="gantt-leg">
                <span className="gantt-leg-dot" style={{ background: STAGE_STATUS_META[s].color }} />
                {STAGE_STATUS_META[s].label}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="gantt" ref={rootRef} onPointerLeave={() => setTip(null)}>
        {/* time-axis header */}
        <div className="gantt-head">
          <div className="gantt-rowlabel" />
          <div className="gantt-track gantt-axis">
            {LIFECYCLE.map((s) => (
              <div className="gantt-col-h" key={s.key}>
                <span className="material-symbols-rounded">{s.icon}</span>
                <span className="gantt-col-lbl">{s.short}</span>
              </div>
            ))}
          </div>
        </div>

        {/* one swimlane per project */}
        {projects.map((p) => {
          const cur = currentStage(p);
          const curIdx = p.stages.findIndex((s) => s.key === cur.key);
          return (
            <div className="gantt-row" key={p.id}>
              <div className="gantt-rowlabel">
                <span className="av" style={{ background: p.c }}>{p.init}</span>
                <span className="gantt-cn">{p.client}</span>
              </div>
              <div className="gantt-track">
                {/* column separators */}
                {LIFECYCLE.map((_, i) => (
                  <span className="gantt-grid" key={i} style={{ left: `${(i / N) * 100}%` }} />
                ))}
                {p.stages.map((st, i) => {
                  const meta = STAGE_STATUS_META[st.status];
                  const fill = fillFor(st.status);
                  const isCurrent = i === curIdx && (st.status === "in_progress" || st.status === "blocked");
                  return (
                    <div
                      key={st.key}
                      className={`gantt-cell${st.status === "upcoming" ? " upcoming" : ""}`}
                      style={{ left: `${(i / N) * 100}%`, width: `${(1 / N) * 100}%` }}
                      onPointerMove={(e) => showTip(e, p, i)}
                    >
                      <div className="gantt-bar">
                        <div
                          className={`gantt-fill${isCurrent ? " current" : ""}`}
                          style={{ width: `${fill * 100}%`, background: meta.color }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {tip && (
          <div className="gantt-tip chart-tip show" style={{ left: tip.x, top: tip.y }} dangerouslySetInnerHTML={{ __html: tip.html }} />
        )}
      </div>
    </section>
  );
}
