"use client";

import { useContentJobs, useCreateContentJob, useReviewContentJob } from "@/lib/hooks/content";
import ContentKpis from "./ContentKpis";
import PipelineBoard from "./PipelineBoard";
import ReviewGate, { type ReviewAction } from "./ReviewGate";
import NewJobForm, { type NewJob } from "./NewJobForm";
import Frameworks from "./Frameworks";

export default function ContentWorkspace() {
  const jobsQ = useContentJobs(); // live: GET /content/jobs, polls while the worker moves a job
  const createJob = useCreateContentJob();
  const reviewJob = useReviewContentJob();

  const jobs = jobsQ.data ?? [];

  // The server snapshots the client name/color, resolves Auto → framework + the
  // JSON-LD schema, seeds source_pack, and returns the queued job — the board then
  // refetches. `code` is unused here; the new row arrives via invalidation.
  function handleCreate(input: NewJob) {
    createJob.mutate({
      client_id: input.clientId,
      pageType: input.pageType,
      topic: input.topic,
      framework: input.framework,
      target: input.target,
    });
  }

  // The review gate; the DB trigger owns the transition. approve also hands the
  // publish worker the job (publishing → done happens server-side), so the board
  // polls to completion rather than faking the final hop.
  function handleReview(id: string, action: ReviewAction) {
    reviewJob.mutate({ code: id, action });
  }

  const needsReview = jobs.filter((j) => j.status === "needs_review");
  const createErr = createJob.error instanceof Error ? createJob.error.message : null;
  const reviewErr = reviewJob.error instanceof Error ? reviewJob.error.message : null;
  const actionErr = createErr ?? reviewErr;

  return (
    <>
      {jobsQ.isError && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Couldn&apos;t load content jobs — {(jobsQ.error as Error)?.message ?? "try again"}.
        </div>
      )}
      {actionErr && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          {createErr ? "Couldn't queue the job" : "Couldn't apply the review"} — {actionErr}.
        </div>
      )}

      <ContentKpis jobs={jobs} />

      <PipelineBoard jobs={jobs} />

      <div className="row">
        <ReviewGate jobs={needsReview} onAction={handleReview} />
        <NewJobForm onCreate={handleCreate} />
      </div>

      <div className="row-single">
        <Frameworks />
      </div>
    </>
  );
}
