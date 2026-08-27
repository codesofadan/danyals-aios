"use client";

// One client's delivery project: the five lifecycle stages, at a URL.
//
// Milestones was a read-only board; a single project - which stage it sits on,
// what auto-advanced it, what is blocking it - could not be linked. The stages
// are AUTO-ADVANCED from delivery events and never hand-edited here; that rule
// holds, so this page is deliberately action-free.

import Link from "next/link";
import { HEALTH_META, LIFECYCLE, projectProgress, type ClientProject } from "@/lib/milestones";
import { useMilestones } from "@/lib/hooks/milestones";
import DetailShell from "@/components/ui/DetailShell";
import StageTimeline, { type Stage as TimelineStage } from "@/components/ui/StageTimeline";

function timelineOf(p: ClientProject): TimelineStage[] {
  return p.stages.map((s) => ({
    key: s.key,
    label: LIFECYCLE.find((l) => l.key === s.key)?.label ?? s.key,
    state:
      s.status === "completed" ? "done"
      : s.status === "in_progress" ? "running"
      : s.status === "blocked" ? "failed"
      : "pending",
    detail: s.auto_source
      ? `${s.status === "blocked" ? "Blocked by" : "Advances from"}: ${s.auto_source}${s.updated_at ? ` · ${s.updated_at}` : ""}`
      : undefined,
  }));
}

export default function MilestoneDetail({ id }: { id: string }) {
  const projectsQ = useMilestones();
  const project = projectsQ.data?.find((p) => p.id === id);

  if (projectsQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load the project</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/milestones">Back to Milestones</Link></div>
      </section>
    );
  }
  if (projectsQ.isLoading) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading project…</div>;
  }
  if (!project) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">No project with this id</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/milestones">Back to Milestones</Link></div>
      </section>
    );
  }

  const health = HEALTH_META[project.health];

  return (
    <DetailShell
      eyebrow="Delivery project"
      title={project.client}
      statusPill={<span className={`status-pill ${health.cls}`}>{health.label}</span>}
      facts={[
        { label: "Site", value: project.site },
        { label: "Progress", value: `${projectProgress(project)}%` },
      ]}
      tabs={[{ key: "stages", label: "Lifecycle", icon: "flag" }]}
    >
      {() => (
        <section className="card" style={{ padding: "var(--s-7)", maxWidth: 640 }}>
          <div className="cs" style={{ marginBottom: "var(--s-6)" }}>
            Stages advance automatically from delivery events (audits landing, content
            publishing) — nobody edits them by hand, so what you see is what happened.
          </div>
          <StageTimeline stages={timelineOf(project)} />
        </section>
      )}
    </DetailShell>
  );
}
