"use client";

// ============================================================
// AIOS · citation-audit progress
//
// "The citation audit does not provide enough visibility into whether the audit is
// actually running." It provided none. POST returned a bare {"status":"queued"} with
// no id, the task behind it produced no ledger row at all, and the only feedback was
// a flash that faded after 4.2 seconds. From then on a sweep still working, a sweep
// that died, and a sweep that never started because nothing was consuming its queue
// all looked exactly alike.
//
// The sweep is a job under the contract now, so this reads the same ledger every
// other long job uses: its status, the live stage line the worker writes, and the
// counts it finished with. No new endpoint and no polling of its own beyond the
// shared runs query.
// ============================================================

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  CITATIONS_KEY,
  CITATION_GAP_KEY,
  OFFPAGE_KPIS_KEY,
  useCitationAuditRuns,
} from "@/lib/hooks/offpage";
import { isTerminalStatus } from "@/lib/jobs";

const TONE: Record<string, { label: string; cls: string }> = {
  queued: { label: "Queued", cls: "mut" },
  running: { label: "Running", cls: "info" },
  completed: { label: "Completed", cls: "ok" },
  degraded: { label: "Partial", cls: "warn" },
  blocked: { label: "Blocked", cls: "warn" },
  failed: { label: "Failed", cls: "op-crit" },
  cancelled: { label: "Cancelled", cls: "mut" },
};

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function CitationAuditProgress({ clientId }: { clientId: string }) {
  const qc = useQueryClient();
  const runsQ = useCitationAuditRuns(clientId, 3);
  const latest = runsQ.data?.[0];

  // Refresh the board the moment the sweep lands, rather than leaving the operator
  // looking at pre-audit counts next to a "Completed" badge.
  const settled = useRef<string | null>(null);
  useEffect(() => {
    if (!latest || !isTerminalStatus(latest.status)) return;
    if (settled.current === latest.id) return;
    settled.current = latest.id;
    void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
    void qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
    void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
  }, [latest, qc]);

  // A FAILED FETCH IS NOT "NEVER AUDITED". Falling back to an empty list here would
  // render nothing at all - identical to a client who has never been audited - which
  // is the same lie this panel exists to remove, one level up. (The repo's own
  // honesty guard catches exactly this; it caught this component.)
  if (runsQ.isError) {
    return (
      <div style={{ marginTop: 10, fontSize: 13, color: "var(--crit)", fontWeight: 600 }}>
        Couldn&rsquo;t load this client&rsquo;s audit history.{" "}
        <button type="button" className="ghostbtn" onClick={() => void runsQ.refetch()}>
          Retry
        </button>
      </div>
    );
  }
  if (!latest) return null;

  const tone = TONE[latest.status] ?? { label: latest.status, cls: "mut" };
  const active = !isTerminalStatus(latest.status);
  const result = (latest.result ?? {}) as {
    citations_new?: number;
    citations_changed?: number;
    backlinks_new?: number;
  };

  return (
    <div
      style={{
        marginTop: 10,
        border: "1px solid var(--line)",
        borderRadius: 10,
        padding: "10px 12px",
        display: "grid",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className={`status-pill ${tone.cls}`}>{tone.label}</span>
        {/* Only say something the pill has not. A terminal run whose detail is empty
            would otherwise render its own status label twice, side by side. */}
        <span style={{ fontSize: 13, color: "var(--body)" }}>
          {active ? (
            <>
              <span
                className="material-symbols-rounded"
                style={{ fontSize: 15, verticalAlign: "-2px", animation: "bkspin 1s linear infinite" }}
              >
                progress_activity
              </span>{" "}
              {/* The worker's own line. "Queued" here means waiting for a worker,
                  which is a real state and now a visible one. */}
              {latest.detail || (latest.status === "queued" ? "Waiting for a worker…" : "Working…")}
            </>
          ) : (
            latest.detail
          )}
        </span>
        <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: "auto" }}>
          {when(latest.createdAt)}
          {latest.finishedAt ? ` · finished ${when(latest.finishedAt)}` : ""}
        </span>
      </div>

      {/* A partial or refused sweep must say which half did not run. The counts
          underneath then describe only what did. */}
      {latest.reason && (
        <div style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.5 }}>{latest.reason}</div>
      )}
      {latest.status === "failed" && latest.errorMessage && (
        <div style={{ fontSize: 12.5, color: "var(--crit)", lineHeight: 1.5 }}>
          {latest.errorType}: {latest.errorMessage}
        </div>
      )}
      {isTerminalStatus(latest.status) && result.citations_new !== undefined && (
        <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
          {result.citations_new} new and {result.citations_changed ?? 0} changed listings recorded.
        </div>
      )}
    </div>
  );
}
