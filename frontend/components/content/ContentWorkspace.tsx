"use client";

import Link from "next/link";

import { useEffect, useState } from "react";
import { useContentJobs, useContentReviewQueue, useReviewContentJob } from "@/lib/hooks/content";
import { useMe } from "@/lib/hooks/portal";
import { useSpendHalted } from "@/lib/hooks/cost";
import ContentKpis from "./ContentKpis";
import PipelineBoard from "./PipelineBoard";
import ReviewGate, { type ReviewAction } from "./ReviewGate";
import ReviewPreview from "./ReviewPreview";

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

      {/* THE BOARD IS THE HOME. Creating content used to happen in a five-step
          wizard mounted INLINE here, so one scrolling page carried making,
          watching and approving at once - the operator's own read was that it
          had no logic. Making now has its own screens at /admin/content/new;
          this page is what is in flight and what needs a human. */}
      {/* The halt used to reach the operator only through the wizard that lived
          here. It still has to: nothing will be written while it is engaged, and
          the board would otherwise just look quiet. */}
      {halted && (
        <div role="alert" className="co-degrade" style={{ marginTop: "var(--s-6)" }}>
          <span className="material-symbols-rounded">pause_circle</span>
          <div>
            <b>API spend is halted</b>
            <div className="cs">
              No page will be researched, written or published while this is on. Lift it on{" "}
              <Link href="/admin/cost">Cost Controls</Link>.
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "var(--s-7) 0 var(--s-5)" }}>
        <div>
          <div className="ct">Content pipeline</div>
          <div className="cs">Every page in flight, and where it has got to.</div>
        </div>
        <Link className="primary-btn" href="/admin/content/new" style={{ marginLeft: "auto" }}>
          <span className="material-symbols-rounded">add</span>New content
        </Link>
      </div>

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
