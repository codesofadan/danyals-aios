"use client";

import { useState } from "react";
import { type TeamMemberRecord } from "@/lib/data";

// Small inline donut for the headline quality score.
function Donut({ value, color }: { value: number; color: string }) {
  const r = 26;
  const circ = 2 * Math.PI * r;
  const off = circ * (1 - value / 100);
  return (
    <div className="perf-dial">
      <svg width="64" height="64" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r={r} className="perf-track" />
        <circle
          cx="32" cy="32" r={r} className="perf-prog"
          stroke={color} strokeDasharray={circ} strokeDashoffset={off} strokeLinecap="round"
          transform="rotate(-90 32 32)"
        />
      </svg>
      <div className="perf-pct">{value}<span>%</span></div>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="metric">
      <div className="metric-top">
        <span className="metric-l">{label}</span>
        <span className="metric-v">{value}%</span>
      </div>
      <div className="metric-bar"><span style={{ width: `${value}%`, background: color }} /></div>
    </div>
  );
}

export default function TeamPerformance({ members }: { members: TeamMemberRecord[] }) {
  // Invited members have no metrics yet — exclude them from the scorecards.
  const scored = members.filter((m) => m.status !== "invited");
  const [sort, setSort] = useState<"quality" | "onTime" | "completed">("completed");

  const ranked = [...scored].sort((a, b) => b[sort] - a[sort]);

  const SORTS: { key: typeof sort; label: string }[] = [
    { key: "completed", label: "Throughput" },
    { key: "quality", label: "Quality" },
    { key: "onTime", label: "On-time" },
  ];

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">insights</span>
          Individual performance · this cycle
        </div>
        <div className="seg" role="tablist" aria-label="Rank by">
          {SORTS.map((s) => (
            <button key={s.key} className={sort === s.key ? "on" : undefined} onClick={() => setSort(s.key)}>{s.label}</button>
          ))}
        </div>
      </div>

      <div className="perf-grid">
        {ranked.map((m, i) => (
          <div className="perf-card" key={m.id}>
            <div className="perf-head">
              <span className="av" style={{ background: m.c }}>{m.init}</span>
              <div className="perf-id">
                <div className="perf-name">{m.name}</div>
                <div className="perf-role">{m.title}</div>
              </div>
              {i === 0 && <span className="top-badge"><span className="material-symbols-rounded">emoji_events</span>Top</span>}
              <Donut value={m.quality} color={m.c} />
            </div>

            <div className="perf-nums">
              <div className="pn"><div className="pn-v">{m.completed}</div><div className="pn-l">Delivered</div></div>
              <div className="pn"><div className="pn-v">{m.activeTasks}</div><div className="pn-l">Active</div></div>
              <div className="pn"><div className="pn-v">{m.onTime}%</div><div className="pn-l">On-time</div></div>
            </div>

            <div className="perf-metrics">
              <Metric label="Utilization" value={m.utilization} color={m.c} />
              <Metric label="On-time delivery" value={m.onTime} color={m.c} />
              <Metric label="QA pass rate" value={m.quality} color={m.c} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
