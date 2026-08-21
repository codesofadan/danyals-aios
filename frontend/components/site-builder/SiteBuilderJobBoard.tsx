"use client";

import { STATUS_META, type SiteGenerationJob } from "@/lib/site-builder";
import { useSiteBuilderJobs } from "@/lib/hooks/site-builder";

export default function SiteBuilderJobBoard() {
  const jobsQ = useSiteBuilderJobs();
  const jobs = jobsQ.data ?? [];

  return (
    <section className="card sb-board">
      <div className="card-h">
        <div>
          <div className="ct">Recent builds</div>
          <div className="cs">Every website/page build, newest first.</div>
        </div>
      </div>
      {jobs.length === 0 ? (
        <div className="sb-wiz-empty">
          <span className="material-symbols-rounded">inbox</span>
          <div>No builds yet — start one above.</div>
        </div>
      ) : (
        <div>
          {jobs.map((job: SiteGenerationJob) => {
            const meta = STATUS_META[job.status];
            return (
              <div className="sb-job-row" key={job.id}>
                <span className="sb-job-code">{job.code}</span>
                <span className="sb-job-title">{job.pageType || job.sourceType}</span>
                <span className="sb-job-stage">{job.stageDetail}</span>
                <span className={`status-pill ${meta.cls}`}>{meta.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
