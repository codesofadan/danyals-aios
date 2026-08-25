"use client";

// ============================================================
// AIOS · Operations — IN FLIGHT
//
// What the per-client concurrency cap is acting on RIGHT NOW, one tile per
// (client, queue). This is the answer to "why is that client's work not
// starting": a client sitting at its cap on a queue has its next job deferred
// rather than started.
//
// A null clientId is agency-global work (a nightly sweep, a platform job) rather
// than an unknown client — it is labelled as such, never blanked.
// ============================================================

import type { InFlightRow } from "@/lib/jobs";

export default function InFlightStrip({
  rows,
  loading,
}: {
  rows: InFlightRow[];
  loading: boolean;
}) {
  const running = rows.reduce((s, r) => s + r.running, 0);
  const clients = new Set(rows.map((r) => r.clientId ?? "platform")).size;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">In flight</div>
          <div className="cs">Running now, by client and queue — the concurrency cap made visible.</div>
        </div>
        <div className="tools">
          <span className={`pill-tag ${running > 0 ? "info" : "ok"}`}>
            <span className="material-symbols-rounded">{running > 0 ? "sync" : "check_circle"}</span>
            {running} running
          </span>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="ops-empty">
          <span className="material-symbols-rounded">bedtime</span>
          <div className="ops-empty-t">{loading ? "Checking the queues…" : "Nothing is running right now"}</div>
          <div className="ops-empty-s">
            {loading
              ? "Asking the workers what they are holding."
              : "No client is occupying a concurrency slot on any queue. An idle platform and a stalled one look the same from a dashboard, so this is a live read, not a cached one."}
          </div>
        </div>
      ) : (
        <>
          <div className="ops-flight">
            {rows.map((r) => (
              <div className="ops-flight-i" key={`${r.clientId ?? "platform"}-${r.queue}`}>
                <div>
                  <span className={`ops-flight-n ${r.clientId ? "" : "plat"}`}>
                    {r.clientName || (r.clientId ? "Unnamed client" : "Platform-wide")}
                  </span>
                  <span className="ops-flight-q">
                    <span className="ops-q">{r.queue}</span>
                  </span>
                </div>
                <div className="ops-flight-run">
                  <b>{r.running}</b>
                  <span>{r.running === 1 ? "job" : "jobs"}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="ops-foot">
            <span>
              <b>{running}</b> {running === 1 ? "job" : "jobs"} across <b>{clients}</b>{" "}
              {clients === 1 ? "client" : "clients"} · queues are duration classes
              (interactive · standard · long · browser), not modules
            </span>
          </div>
        </>
      )}
    </section>
  );
}
