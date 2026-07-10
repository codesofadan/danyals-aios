"use client";

import {
  LIFECYCLE, STAGE_STATUS_META, HEALTH_META, projectProgress, currentStage,
  type ClientProject,
} from "@/lib/milestones";

export default function ClientTimeline({
  project, expanded, onToggle,
}: {
  project: ClientProject;
  expanded: boolean;
  onToggle: () => void;
}) {
  const pct = projectProgress(project);
  const cur = currentStage(project);
  const health = HEALTH_META[project.health];
  const curMeta = STAGE_STATUS_META[cur.status];
  const blocked = cur.status === "blocked";

  const byKey = new Map(project.stages.map((s) => [s.key, s] as const));

  return (
    <div className="ms-proj" data-health={project.health}>
      <div className="ms-phead">
        <span className="ms-avatar" style={{ background: project.c }}>{project.init}</span>
        <div className="ms-cid">
          <div className="ms-cn">{project.client}</div>
          <div className="ms-site">
            <span className="material-symbols-rounded">language</span>{project.site}
          </div>
        </div>
        <span className={`status-pill ${health.cls}`}>
          <span className="material-symbols-rounded ms-hic">{health.icon}</span>{health.label}
        </span>
        <div className="ms-pct">{pct}<span className="u">%</span></div>
        <button className={expanded ? "ms-expand on" : "ms-expand"} onClick={onToggle}
          aria-expanded={expanded} aria-label="Toggle stage detail">
          <span className="material-symbols-rounded">expand_more</span>
        </button>
      </div>

      <div className="ms-steps" role="list" aria-label={`${project.client} lifecycle`}>
        {LIFECYCLE.map((lc, i) => {
          const st = byKey.get(lc.key)!;
          const meta = STAGE_STATUS_META[st.status];
          const prev = i > 0 ? byKey.get(LIFECYCLE[i - 1].key)! : null;
          const isCurrent = st === cur;
          return (
            <div className="ms-step" role="listitem" data-s={st.status} key={lc.key}>
              {i > 0 && <span className="ms-conn" data-on={prev!.status === "completed" ? "1" : "0"} />}
              <span className="ms-node" data-s={st.status} title={`${lc.label} · ${meta.label}`}>
                <span className="material-symbols-rounded">{meta.icon}</span>
              </span>
              <span className="ms-slabel">{lc.short}{isCurrent && <em className="ms-cur">Current</em>}</span>
            </div>
          );
        })}
      </div>

      <div className="ms-prog" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} />
      </div>

      <div className={blocked ? "ms-note blocked" : "ms-note"}>
        <span className="material-symbols-rounded">{blocked ? "block" : "bolt"}</span>
        <span><b>{LIFECYCLE.find((l) => l.key === cur.key)?.label}</b> — {cur.auto_source}</span>
      </div>

      {expanded && (
        <div className="ms-detail">
          {LIFECYCLE.map((lc) => {
            const st = byKey.get(lc.key)!;
            const meta = STAGE_STATUS_META[st.status];
            return (
              <div className="ms-drow" key={lc.key} data-s={st.status}>
                <span className="ms-dic" style={{ color: meta.color }}>
                  <span className="material-symbols-rounded">{lc.icon}</span>
                </span>
                <div className="ms-dmain">
                  <div className="ms-dhead">
                    <span className="ms-dlabel">{lc.label}</span>
                    <span className={`status-pill ${meta.cls}`}>{meta.label}</span>
                  </div>
                  <div className="ms-dnote">{st.auto_source}</div>
                </div>
                <span className="ms-dago">{st.updated_at}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
