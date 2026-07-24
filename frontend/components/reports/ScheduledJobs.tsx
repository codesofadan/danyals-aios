"use client";

import { useScheduledJobs, type ScheduledJob } from "@/lib/hooks/reports";

// The "Scheduled jobs" panel: the REAL Celery beat cron jobs the platform runs in the
// background. The list is derived server-side from the live beat_schedule, so each row is
// a job that is actually scheduled — name, what it does, its cadence, the next fire time,
// and (from the run ledger) when it last ran and how it went. A job that needs an absent
// provider key is shown flagged, never hidden.

// Compact relative label for an ISO timestamp: "in 2d" (future) / "5h ago" (past).
function relTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = then - Date.now();
  const future = diff >= 0;
  const abs = Math.abs(diff);
  const mins = Math.round(abs / 60000);
  let label: string;
  if (mins < 1) label = "now";
  else if (mins < 60) label = `${mins}m`;
  else if (mins < 1440) label = `${Math.round(mins / 60)}h`;
  else label = `${Math.round(mins / 1440)}d`;
  if (label === "now") return "now";
  return future ? `in ${label}` : `${label} ago`;
}

const STATUS_TONE: Record<string, string> = {
  ok: "ok",
  degraded: "warn",
  blocked: "warn",
  skipped: "mut",
  error: "warn",
};

function JobRow({ job }: { job: ScheduledJob }) {
  const tone = job.lastStatus ? STATUS_TONE[job.lastStatus] ?? "mut" : "mut";
  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        alignItems: "flex-start",
        padding: "12px 14px",
        border: "1px solid var(--line, rgba(0,0,0,0.08))",
        borderRadius: 12,
      }}
    >
      <span className="material-symbols-rounded" style={{ color: "var(--brand, #7B69EE)" }}>
        schedule
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 8,
            alignItems: "baseline",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontWeight: 700 }}>{job.name}</span>
          <span className="status-pill mut" style={{ whiteSpace: "nowrap" }}>
            {job.cadence}
          </span>
        </div>
        <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 3 }}>{job.description}</div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            alignItems: "center",
            marginTop: 6,
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          <span className="rp-mono">{job.task}</span>
          <span>
            <span className="material-symbols-rounded" style={{ fontSize: 14, verticalAlign: "-2px" }}>
              update
            </span>{" "}
            next {relTime(job.nextRun)}
          </span>
          <span>
            <span className="material-symbols-rounded" style={{ fontSize: 14, verticalAlign: "-2px" }}>
              history
            </span>{" "}
            last {relTime(job.lastRun)}
          </span>
          {job.lastStatus && (
            <span className={`status-pill ${tone}`} style={{ whiteSpace: "nowrap" }}>
              {job.lastStatus}
            </span>
          )}
          {job.waitingOn && (
            <span className="status-pill warn" style={{ whiteSpace: "nowrap" }}>
              waiting on {job.waitingOn}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ScheduledJobs() {
  const q = useScheduledJobs();
  const jobs = q.data ?? [];

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Scheduled jobs</div>
          <div className="cs">Autonomous cron jobs the platform runs on Celery beat</div>
        </div>
        <div className="tools">
          <span className="pill-tag">
            <span className="material-symbols-rounded">schedule</span>
            {jobs.length} job{jobs.length === 1 ? "" : "s"}
          </span>
        </div>
      </div>

      {q.isLoading ? (
        <div className="rp-conn-foot">
          <span className="material-symbols-rounded">hourglass_empty</span>
          Loading scheduled jobs…
        </div>
      ) : q.isError ? (
        <div className="rp-conn-foot" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t load scheduled jobs — {(q.error as Error)?.message ?? "try again"}.
        </div>
      ) : jobs.length === 0 ? (
        <div className="rp-conn-foot">
          <span className="material-symbols-rounded">schedule</span>
          No scheduled jobs are configured.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "4px 2px" }}>
          {jobs.map((j) => (
            <JobRow key={j.name} job={j} />
          ))}
        </div>
      )}
    </section>
  );
}
