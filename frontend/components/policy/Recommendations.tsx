"use client";

import { useMemo, useState } from "react";
import {
  recommendations as seed, MODULE_META, REC_OPEN,
  type Recommendation, type RecStatus,
} from "@/lib/policy";

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
  const [recs, setRecs] = useState<Recommendation[]>(seed);
  const [filter, setFilter] = useState<RecStatus | "open" | "all">("open");

  function setStatus(id: string, status: RecStatus) {
    setRecs((prev) => prev.map((r) => (r.id === id ? { ...r, status } : r)));
  }

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
          <div className="cs">Nothing changes live until you confirm. Acknowledge, apply, or dismiss each closed-loop action.</div>
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
        {rows.map((r) => {
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

              <div className="pr-rec-btns">
                <button
                  className={`pr-act ack ${r.status === "acknowledged" ? "on" : ""}`}
                  onClick={() => setStatus(r.id, "acknowledged")}
                  disabled={r.status === "acknowledged"}
                >
                  <span className="material-symbols-rounded">visibility</span>Acknowledge
                </button>
                <button
                  className={`pr-act apply ${r.status === "applied" ? "on" : ""}`}
                  onClick={() => setStatus(r.id, "applied")}
                  disabled={r.status === "applied"}
                >
                  <span className="material-symbols-rounded">check_circle</span>Apply
                </button>
                <button
                  className={`pr-act dismiss ${r.status === "dismissed" ? "on" : ""}`}
                  onClick={() => setStatus(r.id, "dismissed")}
                  disabled={r.status === "dismissed"}
                >
                  <span className="material-symbols-rounded">cancel</span>Dismiss
                </button>
              </div>
            </article>
          );
        })}
        {rows.length === 0 && <div className="pr-empty pr-recs-empty">No {filter} recommendations.</div>}
      </div>
    </section>
  );
}
