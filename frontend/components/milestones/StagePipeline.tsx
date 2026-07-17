"use client";

import { LIFECYCLE } from "@/lib/milestones";
import { SERIES } from "@/lib/data";
import { useMilestones } from "@/lib/hooks/milestones";

const ACCENT = [SERIES.c1, SERIES.c4, SERIES.c3, SERIES.c2, SERIES.c5];

export default function StagePipeline() {
  const projectsQ = useMilestones();
  const projects = projectsQ.data ?? [];
  const total = projects.length;

  // How many projects have cleared (completed) each lifecycle stage — a funnel.
  const funnel = LIFECYCLE.map((lc) => ({
    label: lc.label,
    icon: lc.icon,
    count: projects.filter((p) => p.stages.find((s) => s.key === lc.key)?.status === "completed").length,
  }));

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Stage pipeline</div>
          <div className="cs">Projects that have cleared each lifecycle stage.</div>
        </div>
        <span className="pill-tag"><span className="material-symbols-rounded">groups</span>{total} projects</span>
      </div>

      <div className="ms-funnel">
        {funnel.map((f, i) => (
          <div className="ms-fstage" key={f.label}>
            <div className="ms-ftop">
              <span className="ms-fl">
                <span className="material-symbols-rounded">{f.icon}</span>{f.label}
              </span>
              <span className="ms-fv">{f.count}<span className="ms-fo">/{total}</span></span>
            </div>
            <div className="ms-fbar">
              <span style={{ width: `${total ? (f.count / total) * 100 : 0}%`, background: ACCENT[i] }} />
            </div>
          </div>
        ))}
        {projectsQ.isLoading && <div className="ms-empty">Loading pipeline…</div>}
        {projectsQ.isError && !projectsQ.isLoading && (
          <div className="ms-empty">Couldn&apos;t load the pipeline — {(projectsQ.error as Error)?.message ?? "try again"}.</div>
        )}
      </div>
    </section>
  );
}
