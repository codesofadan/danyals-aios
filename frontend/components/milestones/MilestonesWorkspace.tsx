"use client";

import { useMemo, useState } from "react";
import {
  projectProgress, PROJECT_FILTERS, STAGE_STATUS_META,
  type ProjectFilter,
} from "@/lib/milestones";
import { useMilestones } from "@/lib/hooks/milestones";
import ClientTimeline from "./ClientTimeline";
import AutoAdvanceFeed from "./AutoAdvanceFeed";
import StagePipeline from "./StagePipeline";
import ProjectGantt from "./ProjectGantt";

const LEGEND: { status: keyof typeof STAGE_STATUS_META }[] = [
  { status: "completed" }, { status: "in_progress" }, { status: "upcoming" }, { status: "blocked" },
];

export default function MilestonesWorkspace() {
  const projectsQ = useMilestones();
  const projects = projectsQ.data ?? [];

  const [filter, setFilter] = useState<ProjectFilter>("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const shown = useMemo(
    () => projects.filter((p) => filter === "all" || p.health === filter),
    [projects, filter],
  );

  const avg = shown.length
    ? Math.round(shown.reduce((s, p) => s + projectProgress(p), 0) / shown.length)
    : 0;

  const toggle = (id: string) => setOpen((o) => ({ ...o, [id]: !o[id] }));

  return (
    <>
      <div className="row-single">
        <ProjectGantt />
      </div>

      <section className="card ms-board">
        <div className="card-h">
          <div>
            <div className="ct">Client project timelines</div>
            <div className="cs">Onboarding → Baseline → Content → Off-page → Reporting. Stages auto-advance from job &amp; audit status.</div>
          </div>
          <div className="tools">
            <div className="seg" role="tablist" aria-label="Filter projects by health">
              {PROJECT_FILTERS.map((f) => (
                <button key={f.key} role="tab" aria-selected={filter === f.key}
                  className={filter === f.key ? "on" : ""} onClick={() => setFilter(f.key)}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="ms-summary">
          <span><b>{shown.length}</b> {shown.length === 1 ? "project" : "projects"}</span>
          <span className="ms-dot">·</span>
          <span><b>{avg}%</b> avg completion</span>
          <span className="ms-summary-hint">
            <span className="material-symbols-rounded">bolt</span>Advances are automatic — no manual edits
          </span>
        </div>

        <div className="ms-list">
          {projectsQ.isLoading && <div className="ms-empty">Loading projects…</div>}
          {projectsQ.isError && !projectsQ.isLoading && (
            <div className="ms-empty">Couldn&apos;t load projects — {(projectsQ.error as Error)?.message ?? "try again"}.</div>
          )}
          {!projectsQ.isLoading && !projectsQ.isError && shown.map((p) => (
            <ClientTimeline key={p.id} project={p} expanded={!!open[p.id]} onToggle={() => toggle(p.id)} />
          ))}
          {!projectsQ.isLoading && !projectsQ.isError && shown.length === 0 && (
            <div className="ms-empty">No projects match this filter.</div>
          )}
        </div>

        <div className="ms-legend">
          {LEGEND.map((l) => {
            const m = STAGE_STATUS_META[l.status];
            return (
              <span className="ms-leg" key={l.status}>
                <span className="d" style={{ background: m.color }} />{m.label}
              </span>
            );
          })}
          <span className="ms-leg-hint">Node color = stage status</span>
        </div>
      </section>

      <div className="row b ms-row">
        <AutoAdvanceFeed />
        <StagePipeline />
      </div>
    </>
  );
}
