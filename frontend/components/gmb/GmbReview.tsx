"use client";

// GMB post review list: shows each drafted GBP post, its policy report (violations
// block approval; warnings are advisory), and the review + dormant-publish actions.

import { POST_TYPE_LABELS, type GmbPost, type GmbPublishResult } from "@/lib/gmb";

const STATUS_LABEL: Record<GmbPost["status"], string> = {
  draft: "Draft", needs_review: "Needs review", approved: "Approved", posted: "Posted", rejected: "Rejected",
};

export default function GmbReview({
  posts, onReview, onPublish, publishResult, busy,
}: {
  posts: GmbPost[];
  onReview: (code: string, action: "approve" | "reject") => void;
  onPublish: (code: string) => void;
  publishResult: GmbPublishResult | null;
  busy: boolean;
}) {
  return (
    <section className="card gmb-review">
      <div className="card-h">
        <div>
          <div className="ct">Posts</div>
          <div className="cs">Review, approve, and (once connected) publish to Google Business Profile.</div>
        </div>
        <div className="tools">
          <span className="pill-tag"><span className="material-symbols-rounded">storefront</span>{posts.length}</span>
        </div>
      </div>

      {posts.length === 0 ? (
        <div className="gmb-empty">
          <span className="material-symbols-rounded">post_add</span>
          <div>No GMB posts yet — generate one to get started.</div>
        </div>
      ) : (
        <div className="gmb-list">
          {posts.map((p) => (
            <article className="gmb-post" key={p.id} style={{ ["--acc" as string]: p.color }}>
              <div className="gmb-post-head">
                <span className="gmb-jid">{p.id}</span>
                <span className="gmb-type">{POST_TYPE_LABELS[p.postType]}</span>
                <span className={`gmb-status s-${p.status}`}>{STATUS_LABEL[p.status]}</span>
                <span className="gmb-post-meta">
                  <span className="gmb-dot" style={{ background: p.color }} />
                  {p.client}
                  <span className="gmb-sep">·</span>{p.charCount} chars
                  {p.cost > 0 && (<><span className="gmb-sep">·</span>${p.cost.toFixed(2)}</>)}
                </span>
              </div>

              {p.title && <div className="gmb-post-title">{p.title}</div>}
              {p.body ? (
                <p className="gmb-post-body">{p.body}</p>
              ) : (
                <p className="gmb-post-body muted">{p.stage || "No draft yet — generation was degraded."}</p>
              )}

              {/* Policy report: violations block approval; warnings are advisory. */}
              {(p.policy?.violations?.length > 0 || p.policy?.warnings?.length > 0) && (
                <div className="gmb-policy">
                  {p.policy.violations.map((v) => (
                    <span className="gmb-issue viol" key={`v-${v.code}`} title={v.message}>
                      <span className="material-symbols-rounded">block</span>{v.message}
                    </span>
                  ))}
                  {p.policy.warnings.map((w) => (
                    <span className="gmb-issue warn" key={`w-${w.code}`} title={w.message}>
                      <span className="material-symbols-rounded">info</span>{w.message}
                    </span>
                  ))}
                </div>
              )}

              <div className="gmb-post-actions">
                {p.status === "needs_review" && (
                  <>
                    <button
                      className="primary-btn"
                      disabled={!p.policyOk || busy}
                      title={p.policyOk ? "Approve this post" : "Resolve policy violations before approving"}
                      onClick={() => onReview(p.id, "approve")}
                    >
                      <span className="material-symbols-rounded">check</span>Approve
                    </button>
                    <button className="ghostbtn" disabled={busy} onClick={() => onReview(p.id, "reject")}>
                      <span className="material-symbols-rounded">close</span>Reject
                    </button>
                  </>
                )}
                {p.status === "approved" && (
                  <button className="ghostbtn" disabled={busy} onClick={() => onPublish(p.id)}>
                    <span className="material-symbols-rounded">publish</span>Publish to Google
                  </button>
                )}
              </div>

              {publishResult && publishResult.code === p.id && !publishResult.posted && (
                <div className="gmb-dormant" role="status">
                  <span className="material-symbols-rounded">cloud_off</span>
                  {publishResult.message}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
