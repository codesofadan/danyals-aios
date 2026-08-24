"use client";

import { useEffect, useState } from "react";
import { useContentJobs, useContentReviewQueue, useReviewContentJob } from "@/lib/hooks/content";
import { useMe } from "@/lib/hooks/portal";
import { useSpendHalted } from "@/lib/hooks/cost";
import ContentKpis from "./ContentKpis";
import PipelineBoard from "./PipelineBoard";
import ReviewGate, { type ReviewAction } from "./ReviewGate";
import ReviewPreview from "./ReviewPreview";
import ContentWizard from "./ContentWizard";

export default function ContentWorkspace() {
  const jobsQ = useContentJobs(); // live: GET /content/jobs, polls while the worker moves a job
  const reviewQ = useContentReviewQueue(); // the gate, queried server-side (never truncated)
  const reviewJob = useReviewContentJob();
  const { halted } = useSpendHalted(); // global API-spend kill-switch
  const me = useMe();

  const jobs = jobsQ.data ?? [];

  // The review transition is LeadOnly server-side (routers/content.py: owner | admin |
  // manager). The UI used to render Approve/Reject unconditionally, so a Specialist or
  // Analyst could click them and get a raw backend 403 string. This is a UX gate only -
  // the server remains the boundary - but a button that cannot work should not invite
  // the click. Compared case-insensitively: the API serialises Title-Case roles while
  // the permission check is lowercase.
  const canReview = ["owner", "admin", "manager"].includes(
    (me.data?.role ?? "").toLowerCase(),
  );

  // The job selected for the framed draft preview. Kept by id (not the object) so the
  // preview tracks the SAME job across refetches - e.g. it follows a job from
  // needs_review through publishing to done, then shows the live URL + open action.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = jobs.find((j) => j.id === selectedId) ?? null;

  // The review gate; the DB trigger owns the transition. approve also hands the
  // publish worker the job (publishing → done happens server-side), so the board
  // polls to completion rather than faking the final hop. `note` carries the
  // reviewer's guided-edit instruction (edit action) → the worker re-drafts to it.
  function handleReview(id: string, action: ReviewAction, note?: string) {
    reviewJob.mutate({ code: id, action, note });
  }

  const needsReview = reviewQ.data ?? [];
  const reviewErr = reviewJob.error instanceof Error ? reviewJob.error.message : null;

  // Close the preview modal on Escape (the scrim handles click-outside).
  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  return (
    <>
      {jobsQ.isError && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Couldn&apos;t load content jobs. {(jobsQ.error as Error)?.message ?? "Try again"}.
        </div>
      )}
      {reviewErr && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Couldn&apos;t apply the review. {reviewErr}.
        </div>
      )}

      <ContentKpis />

      {/* THE primary surface — one guided wizard replacing the old research /
          design / new-job entry cards. */}
      <ContentWizard jobs={jobs} halted={halted} onReview={handleReview} />

      {/* Tracking surfaces for jobs already in flight. Cards are clickable → modal preview. */}
      <PipelineBoard jobs={jobs} onSelect={setSelectedId} />

      {/* The framed draft preview, as a modal: click a pipeline card (or a review row)
          to open; scrim click or Esc closes. */}
      {selected && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={`Preview ${selected.id}`}
          onClick={() => setSelectedId(null)}
        >
          <div className="co-preview-modal" onClick={(e) => e.stopPropagation()}>
            <ReviewPreview
              job={selected}
              onAction={handleReview}
              onClose={() => setSelectedId(null)}
              canReview={canReview}
            />
          </div>
        </div>
      )}

      <ReviewGate
        jobs={needsReview}
        onAction={handleReview}
        onPreview={setSelectedId}
        canReview={canReview}
      />
    </>
  );
}
