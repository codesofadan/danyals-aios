"use client";

import { useMemo, useState } from "react";
import { MODULE_META, REC_OPEN, type RecStatus } from "@/lib/policy";
import { useRecommendations } from "@/lib/hooks/policy";

const STATUS_META: Record<RecStatus, { label: string; cls: string; icon: string }> = {
  new: { label: "New", cls: "warn", icon: "fiber_new" },
  acknowledged: { label: "Acknowledged", cls: "info", icon: "visibility" },
  applied: { label: "Applied", cls: "ok", icon: "check_circle" },
  dismissed: { label: "Dismissed", cls: "mut", icon: "cancel" },
};

const FILTERS: { key: RecStatus | "open" | "all"; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "applied", label: "Applied" },
  { key: "dismissed", label: "Dismissed" },
  { key: "all", label: "All" },
];

export default function Recommendations() {
  const recsQ = useRecommendations();
  const recs = recsQ.data ?? [];
  const [filter, setFilter] = useState<RecStatus | "open" | "all">("open");

  const openCount = recs.filter((r) => REC_OPEN.includes(r.status)).length;

  const rows = useMemo(
    () =>
      recs.filter((r) =>
        filter === "all" ? true : filter === "open" ? REC_OPEN.includes(r.status) : r.status === filter
      ),
    [recs, filter]
  );

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
        <div className="tools">
          <span className="pr-cc-count">{openCount} open</span>
          <div className="seg">
            {FILTERS.map((f) => (
              <button key={f.key} className={filter === f.key ? "on" : ""} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="pr-recs">
        {recsQ.isLoading && <div className="pr-empty pr-recs-empty">Loading recommendations…</div>}
        {recsQ.isError && !recsQ.isLoading && (
          <div className="pr-empty pr-recs-empty">Couldn&apos;t load recommendations — {(recsQ.error as Error)?.message ?? "try again"}.</div>
        )}
        {!recsQ.isLoading && !recsQ.isError && rows.map((r) => {
          const mod = MODULE_META[r.target];
          const st = STATUS_META[r.status];
          const settled = r.status === "applied" || r.status === "dismissed";
          return (
            <article className={`pr-rec ${settled ? "settled" : ""}`} key={r.id}>
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
            </article>
          );
        })}
        {!recsQ.isLoading && !recsQ.isError && rows.length === 0 && (
          <div className="pr-empty pr-recs-empty">No {filter} recommendations.</div>
        )}
      </div>
    </section>
  );
}
