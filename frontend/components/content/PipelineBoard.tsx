"use client";

import { COLUMNS, PAGE_TYPE_LABELS, type ContentJob, type ColumnKey } from "@/lib/content";

const PAGE_ICON: Record<ContentJob["pageType"], string> = {
  service: "home_repair_service",
  blog: "article",
  local: "location_on",
  gbp_post: "storefront",
};

function JobCard({ job }: { job: ContentJob }) {
  return (
    <article className="co-card" style={{ ["--acc" as string]: job.color }}>
      <div className="co-card-top">
        <span className="co-jid">{job.id}</span>
        <span className={`co-page ${job.pageType}`}>
          <span className="material-symbols-rounded">{PAGE_ICON[job.pageType]}</span>
          {PAGE_TYPE_LABELS[job.pageType]}
        </span>
      </div>
      <div className="co-topic">{job.topic}</div>
      <div className="co-client">
        <span className="co-dot" style={{ background: job.color }} />
        {job.client}
      </div>
      <div className="co-card-foot">
        <span className="co-fw">{job.framework}{job.auto && <i>auto</i>}</span>
        <span className="co-cost">${job.cost}</span>
      </div>
      <div className="co-stage">
        <span className="material-symbols-rounded">bolt</span>
        {job.stage}
        <span className="co-target">{job.target === "WordPress" ? "WP" : "PDF/MD"}</span>
      </div>
    </article>
  );
}

export default function PipelineBoard({ jobs }: { jobs: ContentJob[] }) {
  const byCol = (k: ColumnKey) => jobs.filter((j) => j.status === k);

  return (
    <section className="card co-board-card">
      <div className="card-h">
        <div>
          <div className="ct">Content pipeline</div>
          <div className="cs">Kanban by job status · Research → Framework → Draft → Review → Publish, ~90% automated.</div>
        </div>
        <div className="tools">
          <span className="pill-tag"><span className="material-symbols-rounded">bolt</span>{jobs.length} jobs</span>
        </div>
      </div>

      <div className="co-board">
        {COLUMNS.map((col) => {
          const items = byCol(col.key);
          return (
            <div className="co-col" key={col.key}>
              <div className="co-col-h">
                <span className={`co-col-ic ${col.tone}`}>
                  <span className="material-symbols-rounded">{col.icon}</span>
                </span>
                <span className="co-col-name">{col.label}</span>
                <span className="co-col-n">{items.length}</span>
              </div>
              <div className="co-col-body">
                {items.length === 0
                  ? <div className="co-empty">No jobs</div>
                  : items.map((j) => <JobCard key={j.id} job={j} />)}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
