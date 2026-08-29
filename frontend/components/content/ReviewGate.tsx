"use client";

import { useState } from "react";
import type { ContentJob } from "@/lib/content";
import ReadMore from "@/components/ui/ReadMore";
import ApproveGate from "./ApproveGate";

export type ReviewAction = "approve" | "edit" | "reject";

const PAGE_LABEL: Record<ContentJob["pageType"], string> = {
  service: "Service", blog: "Blog", local: "Local", gbp_post: "GMB Post",
};

export default function ReviewGate({
  jobs, onAction, onPreview, canReview = true,
}: {
  jobs: ContentJob[];
  onAction: (id: string, action: ReviewAction, note?: string) => void;
  onPreview?: (id: string) => void;
  /** The review transition is LeadOnly server-side. False disables the decision
   *  buttons rather than letting a non-lead click into a raw 403. Preview stays
   *  available - reading a draft needs no lead role. */
  canReview?: boolean;
}) {
  const gateTitle = canReview ? undefined : "Only a lead (owner, admin or manager) can review";
  // "Request edit" needs a free-text instruction, which lives in the full SEO
  // preview. So the row-level edit button OPENS the preview, where the reviewer
  // writes the note.
  //
  // THERE IS NO NOTE-LESS FALLBACK. This used to read `onPreview ? onPreview(id) :
  // onAction(id, "edit")`, i.e. with no preview wired it fired an edit carrying no
  // instruction. The server now refuses that with a 400 (routers/content.py,
  // _EDIT_NEEDS_INSTRUCTION) because a blank instruction stranded the job at
  // "Edit requested". Sending it anyway would just turn a silent dead end into a
  // toast the reviewer can do nothing about, so the button is disabled instead and
  // says why - the row has nowhere to type a note.
  const canRequestEdit = canReview && Boolean(onPreview);
  const editTitle = !canReview
    ? gateTitle
    : onPreview
      ? undefined
      : "Open the draft preview to request edits — an edit needs an instruction";
  // D-4: approving publishes to a client's live site, so the QA verdict is shown
  // and acknowledged HERE rather than living on a preview tab nobody must open.
  const [approving, setApproving] = useState<ContentJob | null>(null);
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Review gate</div>
          <div className="cs">The human 10% — approve, request edits, or reject before publish.</div>
        </div>
        <div className="tools">
          <span className="pill-tag warn"><span className="material-symbols-rounded">how_to_reg</span>{jobs.length} to review</span>
        </div>
      </div>

      {jobs.length === 0 ? (
        <div className="co-gate-empty">
          <span className="material-symbols-rounded">inbox</span>
          <div>Queue is clear — every draft is approved or published.</div>
        </div>
      ) : (
        <div className="co-gate-list">
          <ReadMore
            items={jobs}
            initialCount={10}
            getKey={(j) => j.id}
            renderItem={(j) => (
              <div className="co-gate-row" style={{ ["--acc" as string]: j.color }}>
                <div className="co-gate-main">
                  <div className="co-gate-head">
                    <span className="co-jid">{j.id}</span>
                    <span className="co-gate-page">{PAGE_LABEL[j.pageType]}</span>
                    <span className="co-fw sm">{j.framework}</span>
                  </div>
                  <div className="co-gate-topic">{j.topic}</div>
                  <div className="co-gate-meta">
                    <span className="co-dot" style={{ background: j.color }} />
                    {j.client}
                    <span className="co-sep">·</span>
                    <span className="material-symbols-rounded">edit_note</span>{j.words.toLocaleString()} words
                    <span className="co-sep">·</span>
                    <span className="material-symbols-rounded">data_object</span>{j.schema}
                    <span className="co-sep">·</span>
                    <span className="material-symbols-rounded">imagesmode</span>{j.images}
                    <span className="co-sep">·</span>
                    <span className="co-cost">${j.cost}</span>
                  </div>
                </div>
                <div className="co-gate-actions">
                  {onPreview && (
                    <button className="ghostbtn" onClick={() => onPreview(j.id)}>
                      <span className="material-symbols-rounded">visibility</span>Preview
                    </button>
                  )}
                  <button
                    className="primary-btn co-approve"
                    onClick={() => setApproving(j)}
                    disabled={!canReview}
                    title={gateTitle}
                  >
                    <span className="material-symbols-rounded">check</span>Approve
                  </button>
                  <button
                    className="ghostbtn"
                    onClick={() => onPreview?.(j.id)}
                    disabled={!canRequestEdit}
                    title={editTitle}
                  >
                    <span className="material-symbols-rounded">edit</span>Request edit
                  </button>
                  <button
                    className="ghostbtn co-reject"
                    onClick={() => onAction(j.id, "reject")}
                    disabled={!canReview}
                    title={gateTitle}
                  >
                    <span className="material-symbols-rounded">close</span>Reject
                  </button>
                </div>
              </div>
            )}
          />
        </div>
      )}

      <ApproveGate
        code={approving?.id ?? null}
        title={approving?.topic ?? ""}
        onCancel={() => setApproving(null)}
        onConfirm={(note) => {
          const job = approving;
          setApproving(null);
          if (job) onAction(job.id, "approve", note);
        }}
      />
    </section>
  );
}
