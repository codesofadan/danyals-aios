"use client";

import { MODULE_META, type RecStatus } from "@/lib/policy";
import { useRecommendations, useTransitionRecommendation, type RecAction } from "@/lib/hooks/policy";
import ReadMore from "@/components/ui/ReadMore";

const STATUS_META: Record<RecStatus, { label: string; cls: string; icon: string }> = {
  new: { label: "New", cls: "warn", icon: "fiber_new" },
  acknowledged: { label: "Acknowledged", cls: "info", icon: "visibility" },
  applied: { label: "Applied", cls: "ok", icon: "check_circle" },
  dismissed: { label: "Dismissed", cls: "mut", icon: "cancel" },
};

// The recommendation queue.
//
// It rendered four status pills - New / Acknowledged / Applied / Dismissed - under a
// subtitle reading "Closed-loop recommendations", and offered NO WAY TO REACH ANY OF
// THEM. `useTransitionRecommendation` existed with zero call sites, and
// `POST /policy/recommendations/{id}/{action}` had no caller, so every recommendation
// the radar produced stayed "New" forever however many times an operator read it.
//
// `apply` is the consequential one: server-side it also writes the closed-loop
// `audit_overlay` row, which is the change the presentation layer lays on top of the
// untouched engine. So it is separated from the other two and asks first.
export default function Recommendations() {
  const recsQ = useRecommendations();
  const transition = useTransitionRecommendation();
  const rows = recsQ.data ?? [];

  return (
    <section className="card pr-cc">
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded pr-cc-star">recommend</span>
            Command Center — Recommendations
          </div>
          <div className="cs">Closed-loop recommendations from Policy Radar, refreshed daily.</div>
        </div>
      </div>

      <div className="pr-recs">
        {recsQ.isLoading && <div className="pr-empty pr-recs-empty">Loading recommendations…</div>}
        {recsQ.isError && !recsQ.isLoading && (
          <div className="pr-empty pr-recs-empty">Couldn&apos;t load recommendations — {(recsQ.error as Error)?.message ?? "try again"}.</div>
        )}
        {!recsQ.isLoading && !recsQ.isError && rows.length > 0 && (
          <ReadMore
            items={rows}
            initialCount={10}
            getKey={(r) => r.id}
            renderItem={(r) => {
              const mod = MODULE_META[r.target];
              const st = STATUS_META[r.status] ?? { label: r.status, cls: "mut", icon: "help" };
              const settled = r.status === "applied" || r.status === "dismissed";
              return (
                <article className={`pr-rec ${settled ? "settled" : ""}`}>
                  <div className="pr-rec-head">
                    <div className="pr-rec-title">{r.title}</div>
                    <span className={`status-pill ${st.cls}`}>
                      <span className="material-symbols-rounded pr-st-ic">{st.icon}</span>{st.label}
                    </span>
                  </div>

                  <div className="pr-rec-why">
                    <span className="pr-rec-k">Why it matters</span>
                    {r.why}
                  </div>

                  <div className="pr-rec-tags">
                    <span className="pr-tag"><span className="material-symbols-rounded">{mod.icon}</span>{mod.label}</span>
                    <span className="pr-tag"><span className="material-symbols-rounded">crop_free</span>{r.scope}</span>
                    <span className={`pr-region ${r.region}`}>
                      <span className="material-symbols-rounded">{r.region === "global" ? "public" : "flag"}</span>
                      {r.regionLabel}
                    </span>
                    {r.clients && <span className="pr-tag mut"><span className="material-symbols-rounded">groups</span>{r.clients}</span>}
                  </div>

                  <div className="pr-rec-action">
                    <span className="material-symbols-rounded">arrow_forward</span>
                    <span><span className="pr-rec-k">Recommended action</span>{r.action}</span>
                  </div>

                  {settled ? (
                    // Applied and dismissed are terminal. Re-offering the controls
                    // would invite a second `apply`, and a second overlay row.
                    <div className="pr-rec-settled">
                      <span className="material-symbols-rounded">{st.icon}</span>
                      {st.label} — no further action needed.
                    </div>
                  ) : (
                    <RecActions
                      id={r.id}
                      status={r.status}
                      title={r.title}
                      busy={transition.isPending}
                      onAct={(action) => transition.mutate({ id: r.id, action })}
                    />
                  )}
                </article>
              );
            }}
          />
        )}
        {!recsQ.isLoading && !recsQ.isError && rows.length === 0 && (
          <div className="pr-empty pr-recs-empty">No recommendations yet.</div>
        )}
      </div>
    </section>
  );
}


function RecActions({
  id, status, title, busy, onAct,
}: {
  id: string;
  status: RecStatus;
  title: string;
  busy: boolean;
  onAct: (action: RecAction) => void;
}) {
  return (
    <div className="pr-rec-actions">
      {status === "new" && (
        <button type="button" className="mini-btn" disabled={busy} onClick={() => onAct("acknowledge")}>
          <span className="material-symbols-rounded">visibility</span>Acknowledge
        </button>
      )}
      <button type="button" className="mini-btn" disabled={busy} onClick={() => onAct("dismiss")}>
        <span className="material-symbols-rounded">cancel</span>Dismiss
      </button>
      <button
        type="button"
        className="primary-btn sm"
        disabled={busy}
        onClick={() => {
          // `apply` writes an audit overlay that changes what every client's report
          // says. It is not undoable from here, so it asks.
          if (window.confirm(`Apply "${title}"? This writes an overlay onto affected audits.`)) {
            onAct("apply");
          }
        }}
        data-rec-id={id}
      >
        <span className="material-symbols-rounded">check_circle</span>Apply
      </button>
    </div>
  );
}
