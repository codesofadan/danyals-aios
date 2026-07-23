"use client";

import { useScheduledJobs } from "@/lib/hooks/reports";

// The "Scheduled jobs" panel: the REAL Celery beat cron jobs the platform runs in the
// background. The list is derived server-side from the live beat_schedule, so each
// row is a job that is actually scheduled — name, what it does, and its cadence.
export default function ScheduledJobs() {
  const q = useScheduledJobs();
  const jobs = q.data ?? [];

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Scheduled jobs</div>
          <div className="cs">Background cron jobs the platform runs on Celery beat</div>
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
            <div
              key={j.name}
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
                  <span style={{ fontWeight: 700 }}>{j.name}</span>
                  <span className="status-pill mut" style={{ whiteSpace: "nowrap" }}>
                    {j.cadence}
                  </span>
                </div>
                <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 3 }}>{j.description}</div>
                <div className="rp-mono" style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>
                  {j.task}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
