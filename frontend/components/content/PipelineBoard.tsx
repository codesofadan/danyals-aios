"use client";

import Link from "next/link";

import { COLUMNS, PAGE_TYPE_LABELS, type ContentJob, type ColumnKey } from "@/lib/content";
import ReadMore from "@/components/ui/ReadMore";

const PAGE_ICON: Record<ContentJob["pageType"], string> = {
  service: "home_repair_service",
  blog: "article",
  local: "location_on",
  gbp_post: "storefront",
};

function JobCard({ job, onSelect }: { job: ContentJob; onSelect?: (id: string) => void }) {
  const clickable = !!onSelect;
  return (
    <article
      className={`co-card${clickable ? " co-card-clickable" : ""}`}
      style={{ ["--acc" as string]: job.color }}
      onClick={clickable ? () => onSelect!(job.id) : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect!(job.id);
              }
            }
          : undefined
      }
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-label={clickable ? `Preview ${job.id}: ${job.topic}` : undefined}
    >
      <div className="co-card-top">
        {/* The code chip is the door to the job's DETAIL page - the full record
            (process timeline, QA, republish, CSV). The card body keeps opening
            the quick review preview. */}
        <Link
          className="co-jid"
          href={`/admin/content/${job.id}`}
          onClick={(e) => e.stopPropagation()}
          title={`Open ${job.id} in full`}
        >
          {job.id}
        </Link>
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

export default function PipelineBoard({
  jobs,
  onSelect,
}: {
  jobs: ContentJob[];
  onSelect?: (id: string) => void;
}) {
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
                {items.length === 0 ? (
                  <div className="co-empty">No jobs</div>
                ) : (
                  <ReadMore
                    items={items}
                    initialCount={10}
                    getKey={(j) => j.id}
                    renderItem={(j) => <JobCard job={j} onSelect={onSelect} />}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
