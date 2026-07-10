"use client";

import type { ContentJob } from "@/lib/content";

export type ReviewAction = "approve" | "edit" | "reject";

const PAGE_LABEL: Record<ContentJob["pageType"], string> = {
  service: "Service", blog: "Blog", local: "Local",
};

export default function ReviewGate({
  jobs, onAction,
}: {
  jobs: ContentJob[];
  onAction: (id: string, action: ReviewAction) => void;
}) {
  return (
    <section className="card co-review-card">
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
          {jobs.map((j) => (
            <div className="co-gate-row" key={j.id} style={{ ["--acc" as string]: j.color }}>
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
                <button className="primary-btn co-approve" onClick={() => onAction(j.id, "approve")}>
                  <span className="material-symbols-rounded">check</span>Approve
                </button>
                <button className="ghostbtn" onClick={() => onAction(j.id, "edit")}>
                  <span className="material-symbols-rounded">edit</span>Request edit
                </button>
                <button className="ghostbtn co-reject" onClick={() => onAction(j.id, "reject")}>
                  <span className="material-symbols-rounded">close</span>Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
