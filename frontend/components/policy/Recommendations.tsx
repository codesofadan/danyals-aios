"use client";

import { MODULE_META, type RecStatus } from "@/lib/policy";
import { useRecommendations, useTransitionRecommendation, type RecAction } from "@/lib/hooks/policy";
import ReadMore from "@/components/ui/ReadMore";

const STATUS_META: Record<RecStatus, { label: string; cls: string; icon: string }> = {
  new: { label: "New", cls: "warn", icon: "fiber_new" },
  acknowledged: { label: "Acknowledged", cls: "info", icon: "visibility" },
  // `applied` is still a status the SERVER can return (a recommendation applied
  // before this change keeps it), so it must still render. It is no longer a state
  // this UI can put anything into - see the note on Apply below.
  applied: { label: "Applied", cls: "ok", icon: "check_circle" },
  dismissed: { label: "Dismissed", cls: "mut", icon: "cancel" },
};

// The recommendation queue.
//
// APPLY WAS WITHDRAWN, and the reason is worth keeping. Applying did persist: it
// flipped `recommendations.status` to 'applied' AND wrote an `audit_overlay` row.
// But `list_active_overlay` has exactly ONE caller - `GET /policy/overlay` - and
// nothing calls that: no audit worker, no report renderer, no scoring path, and no
// frontend hook. The overlay was written, was queryable, and was read by nothing.
//
// So the dialog's promise - "the change appears in those clients' reports" - was
// false, and "Applied" was a badge for an effect that never happened. QA asked for
// the honest option: remove the state rather than display a misleading one.
//
// Acknowledge and Dismiss stay: both mean exactly what they say (someone read it,
// someone rejected it) and neither claims a downstream effect.
//
// The backend route, the `audit_overlay` table and `apply_recommendation` are all
// left in place, unused. Re-offering Apply is a one-component change once an audit
// run actually reads the overlay.
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
  id, status, busy, onAct,
}: {
  id: string;
  status: RecStatus;
  busy: boolean;
  onAct: (action: RecAction) => void;
}) {
  return (
    <div className="pr-rec-actions" data-rec-id={id}>
      {status === "new" && (
        <button type="button" className="mini-btn" disabled={busy} onClick={() => onAct("acknowledge")}>
          <span className="material-symbols-rounded">visibility</span>Acknowledge
        </button>
      )}
      <button type="button" className="mini-btn" disabled={busy} onClick={() => onAct("dismiss")}>
        <span className="material-symbols-rounded">cancel</span>Dismiss
      </button>
    </div>
  );
}
