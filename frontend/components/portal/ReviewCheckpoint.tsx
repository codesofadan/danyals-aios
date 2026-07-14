"use client";

import { CAN_REVIEW, dueInfo, type Task, type TeamMemberRecord } from "@/lib/data";

export type ReviewAction = "approve" | "reject";

export default function ReviewCheckpoint({
  me, tasks, onReview,
}: {
  me: TeamMemberRecord;
  tasks: Task[];
  onReview: (id: string, action: ReviewAction) => void;
}) {
  const canReview = CAN_REVIEW.includes(me.role);
  const inReview = tasks.filter((t) => t.status === "review");

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">how_to_reg</span>
          The human 10% — {canReview ? "sign off before content publishes" : "your work awaiting a lead's sign-off"}
        </div>
        <span className={`pill-tag ${inReview.length ? "warn" : "ok"}`}>
          <span className="material-symbols-rounded">{inReview.length ? "pending" : "check_circle"}</span>
          {inReview.length} in review
        </span>
      </div>

      {inReview.length === 0 ? (
        <div className="pt-empty">
          <span className="material-symbols-rounded">inbox</span>
          <div className="pt-empty-t">Review queue is clear</div>
          <div className="pt-empty-s">Nothing of yours is waiting at the review gate.</div>
        </div>
      ) : (
        <div className="rv-list">
          {inReview.map((t) => {
            const due = dueInfo(t.due);
            return (
              <div className="rv-row" key={t.id}>
                <span className={`prio-bar ${t.priority}`} />
                <div className="rv-main">
                  <div className="rv-head">
                    <span className="task-id">{t.id}</span>
                    <span className="task-type">{t.type}</span>
                    <span className={`pq-due ${due.tone}`}>{due.label}</span>
                  </div>
                  <div className="rv-title">{t.title}</div>
                  <div className="rv-meta">
                    <span className="rv-dot" style={{ background: me.c }} />
                    {t.client}
                  </div>
                </div>
                {canReview ? (
                  <div className="rv-actions">
                    <button className="primary-btn" onClick={() => onReview(t.id, "approve")}>
                      <span className="material-symbols-rounded">check</span>Approve &amp; publish
                    </button>
                    <button className="ghostbtn rv-reject" onClick={() => onReview(t.id, "reject")}>
                      <span className="material-symbols-rounded">undo</span>Send back
                    </button>
                  </div>
                ) : (
                  <div className="rv-waiting">
                    <span className="material-symbols-rounded">hourglass_top</span>
                    Awaiting sign-off
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!canReview && (
        <div className="bk-note" style={{ marginTop: 16 }}>
          <span className="material-symbols-rounded">info</span>
          <span>Only <b>Manager</b>, <b>Admin</b> and <b>Owner</b> roles can approve at the review gate. Your submissions publish once a lead signs off.</span>
        </div>
      )}
    </div>
  );
}
