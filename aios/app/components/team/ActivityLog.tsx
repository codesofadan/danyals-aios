"use client";

import { useState } from "react";
import { ACTIVITY_META, type Activity, type ActivityKind } from "@/lib/data";

const FILTERS: { key: ActivityKind | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "task", label: "Tasks" },
  { key: "member", label: "Members" },
  { key: "access", label: "Access" },
  { key: "audit", label: "Audits" },
  { key: "content", label: "Content" },
];

export default function ActivityLog({ log }: { log: Activity[] }) {
  const [filter, setFilter] = useState<ActivityKind | "all">("all");
  const rows = filter === "all" ? log : log.filter((a) => a.kind === filter);

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">history</span>
          {log.length} events · newest first
        </div>
        <div className="log-filters">
          {FILTERS.map((f) => (
            <button key={f.key} className={filter === f.key ? "chip on" : "chip"} onClick={() => setFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="timeline">
        {rows.map((a) => {
          const meta = ACTIVITY_META[a.kind];
          return (
            <div className="tl-row" key={a.id}>
              <div className="tl-rail">
                <span className="tl-ic" style={{ background: `${meta.c}22`, color: meta.c }}>
                  <span className="material-symbols-rounded">{meta.icon}</span>
                </span>
              </div>
              <div className="tl-body">
                <div className="tl-line">
                  <span className="av xs" style={{ background: a.actorColor }}>{a.actorInit}</span>
                  <span className="tl-actor">{a.actorName}</span>
                  <span className="tl-action">{a.action}</span>
                  <span className="tl-target">{a.target}</span>
                </div>
                {a.meta && <div className="tl-meta">{a.meta}</div>}
              </div>
              <div className="tl-ago">{a.ago}</div>
            </div>
          );
        })}
        {rows.length === 0 && <div className="tl-empty">No {filter} events yet.</div>}
      </div>
    </div>
  );
}
