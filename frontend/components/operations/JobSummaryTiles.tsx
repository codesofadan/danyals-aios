"use client";

// ============================================================
// AIOS · Operations — the window headline
//
// Five numbers over one window, in the backend's own vocabulary:
//
//   TOTAL RUNS        every job the platform executed in the window
//   SUCCEEDED         `succeededRuns` — COMPLETED ONLY. The server computes it
//                     (app.jobs.status.is_success); this tile never re-derives
//                     success from a status string, because there is exactly one
//                     definition and `degraded` is not it.
//   NEEDS ATTENTION   `needsAttentionRuns` — degraded + blocked + failed, the three
//                     an operator must act on.
//   SPEND             `totalCostUsd` — what the window cost in real money.
//   OPEN DEAD LETTERS work the platform ACCEPTED and did not deliver. Any number
//                     above zero is an outage a client is living with, so the tile
//                     reads as urgent rather than as a statistic.
//
// The per-status breakdown strip below the tiles exists so `degraded` is never
// folded into a success count — it gets its own line, with its meaning attached.
// ============================================================

import { useMemo } from "react";
import { usd } from "@/lib/cost";
import { JOB_STATUSES, type JobSummary } from "@/lib/jobs";
import { statusChip } from "./vocabulary";

export type WindowHours = 24 | 168;

const WINDOWS: { hours: WindowHours; label: string; long: string }[] = [
  { hours: 24, label: "24h", long: "the last 24 hours" },
  { hours: 168, label: "7d", long: "the last 7 days" },
];

const whole = (n: number) => n.toLocaleString("en-US");

export default function JobSummaryTiles({
  summary,
  windowHours,
  onWindow,
  loading,
}: {
  summary: JobSummary | undefined;
  windowHours: WindowHours;
  onWindow: (h: WindowHours) => void;
  loading: boolean;
}) {
  const win = WINDOWS.find((w) => w.hours === windowHours) ?? WINDOWS[0];
  const total = summary?.totalRuns ?? 0;
  const succeeded = summary?.succeededRuns ?? 0;
  const attention = summary?.needsAttentionRuns ?? 0;
  const cost = summary?.totalCostUsd ?? 0;
  const dead = summary?.openDeadLetters ?? 0;

  // What worked, then what needs a human, then what is still moving — lib/jobs.ts
  // owns that order so every surface tells the story the same way round.
  const byStatus = useMemo(() => {
    const rows = summary?.byStatus ?? [];
    return [...rows].sort(
      (a, b) => JOB_STATUSES.indexOf(a.status) - JOB_STATUSES.indexOf(b.status),
    );
  }, [summary]);

  return (
    <>
      <div className="ops-winbar">
        <div className="ops-winbar-t">
          Every background job the platform ran in <b>{win.long}</b> — what failed, and what it cost.
        </div>
        <div className="seg" role="tablist" aria-label="Summary window">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              type="button"
              role="tab"
              aria-selected={w.hours === windowHours}
              className={w.hours === windowHours ? "on" : undefined}
              onClick={() => onWindow(w.hours)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <section className="kpis ops-kpis">
        <div className="kpi hero">
          <div className="ic"><span className="material-symbols-rounded">conveyor_belt</span></div>
          <div className="lab">Runs</div>
          <div className="val">{loading && !summary ? "—" : whole(total)}</div>
          <div className="sub">jobs executed in {win.long}</div>
        </div>

        <div className="kpi ops-kpi-ok">
          <div className="ic"><span className="material-symbols-rounded">check_circle</span></div>
          <div className="lab">Succeeded</div>
          <div className="val">{loading && !summary ? "—" : whole(succeeded)}</div>
          {/* The distinction is the product: `degraded` finished, but it did not keep
              the promise, so it is never counted here. */}
          <div className="sub">completed only — degraded is not a success</div>
        </div>

        <div className={`kpi ops-kpi-att ${attention > 0 ? "hot" : ""}`}>
          <div className="ic"><span className="material-symbols-rounded">error</span></div>
          <div className="lab">Needs attention</div>
          <div className="val">{loading && !summary ? "—" : whole(attention)}</div>
          <div className="sub">degraded · blocked · failed</div>
        </div>

        <div className="kpi">
          <div className="ic"><span className="material-symbols-rounded">payments</span></div>
          <div className="lab">Spend</div>
          <div className="val">{loading && !summary ? "—" : usd(cost, 2)}</div>
          <div className="sub">metered cost of this window&apos;s runs</div>
        </div>

        <div className={`kpi ops-kpi-dl ${dead > 0 ? "urgent" : ""}`}>
          <div className="ic"><span className="material-symbols-rounded">{dead > 0 ? "report" : "inventory_2"}</span></div>
          <div className="lab">Open dead letters</div>
          <div className="val">{loading && !summary ? "—" : whole(dead)}</div>
          <div className="sub">
            {dead > 0 && <span className="ops-dot" />}
            {dead > 0 ? "accepted work never delivered" : "nothing accepted was lost"}
          </div>
        </div>
      </section>

      {byStatus.length > 0 && (
        <div className="ops-break">
          {byStatus.map((s) => {
            const meta = statusChip(s.status);
            return (
              <span key={s.status} className="ops-break-i" title={meta.meaning}>
                <span className={`status-pill ${meta.cls}`}>{meta.label}</span>
                <b>{whole(s.runs)}</b>
                <span className="ops-break-c">{usd(s.costUsd, 2)}</span>
              </span>
            );
          })}
        </div>
      )}
    </>
  );
}
