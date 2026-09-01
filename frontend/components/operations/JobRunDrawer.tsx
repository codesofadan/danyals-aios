"use client";

// ============================================================
// AIOS · Operations — ONE RUN IN FULL
//
// The record behind a row: the vocabulary fields as the server computed them, the
// written reason, the error when it failed, the result payload the job produced,
// and the correlation id that ties this run to the fan-out it belonged to.
//
// TWO RULES THIS SURFACE KEEPS:
//   1. `succeeded` is READ, never re-derived. The server computes it from
//      is_success() — completed and nothing else — so this drawer prints the flag
//      it was handed rather than testing a status string of its own.
//   2. A degraded or blocked run is never rendered without its reason. That field
//      is guaranteed non-empty by a DB CHECK constraint, so the explanation exists;
//      failing to show it would be the UI inventing an ambiguity the API refuses to.
//
// Cancel is COOPERATIVE and lead-only. It is not a kill: a queued run never starts,
// a running one stops at its next ctx.checkpoint(), and a job that never checkpoints
// cannot be stopped at all. The button says so rather than promising a halt.
// ============================================================

import { useEffect, useState } from "react";
import { usd } from "@/lib/cost";
import { formatDuration, type JobRun } from "@/lib/jobs";
import { statusChip } from "./vocabulary";
import { useCancelRun, useJobRun } from "@/lib/hooks/jobs";

const CANCELLABLE = new Set(["queued", "running"]);

function whenText(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function isUrl(v: string): boolean {
  return /^https?:\/\//i.test(v);
}

/** The job's own output, rendered readably: scalars as facts (URLs as links),
 *  everything structured as pretty JSON behind a disclosure. A replica's
 *  `preview_url`, `sections` and `widgets` all arrive through here. */
function ResultBlock({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result);
  if (entries.length === 0) return null;

  // Scalars read as facts; objects and arrays (sections, widgets, a list of
  // published URLs) keep their shape behind a disclosure rather than being flattened
  // into something that looks like data it is not.
  const scalars = entries.filter(([, v]) => v === null || typeof v !== "object");
  const structured = entries.filter(([, v]) => v !== null && typeof v === "object");

  return (
    <div className="ops-sec">
      <div className="ops-sec-h">Result</div>
      {scalars.length > 0 && (
        <div className="ops-facts">
          {scalars.map(([k, v]) => (
            <div key={k}>
              <div className="ops-fact-k">{k.replace(/_/g, " ")}</div>
              <div className={`ops-fact-v ${typeof v === "string" && v.length > 40 ? "mono" : ""}`}>
                {typeof v === "string" && isUrl(v) ? (
                  <a href={v} target="_blank" rel="noopener noreferrer">
                    {v}
                  </a>
                ) : v === null ? (
                  "—"
                ) : (
                  String(v)
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {structured.length > 0 && (
        <details className="ops-detail">
          <summary>
            Structured output ({structured.map(([k]) => k).join(", ")})
          </summary>
          <pre className="ops-pre">{JSON.stringify(Object.fromEntries(structured), null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

export default function JobRunDrawer({
  runId,
  fallback,
  canAct,
  onClose,
}: {
  runId: string;
  /** The row the operator clicked — renders instantly while the fresh read lands. */
  fallback: JobRun | null;
  canAct: boolean;
  onClose: () => void;
}) {
  const q = useJobRun(runId);
  const cancel = useCancelRun();
  const [reason, setReason] = useState("");

  const run = q.data ?? fallback;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!run) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-panel ops-drawer" onClick={(e) => e.stopPropagation()}>
          <div className="modal-body">
            <div className="ops-empty">
              <span className="material-symbols-rounded">hourglass_top</span>
              <div className="ops-empty-t">{q.isError ? "That run could not be loaded" : "Loading the run…"}</div>
              <div className="ops-empty-s">
                {q.isError ? (q.error as Error)?.message ?? "Try again." : "Reading the ledger."}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const meta = statusChip(run.status);
  const cancellable = CANCELLABLE.has(run.status) && !run.cancelRequested;
  const previewUrl =
    (run.result?.preview_url as string | undefined) ?? (run.result?.previewUrl as string | undefined);
  const cancelError = cancel.error instanceof Error ? cancel.error.message : null;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Job run detail" onClick={onClose}>
      <div className="modal-panel ops-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="ey">{run.queue} queue · attempt {run.attempt} of {run.maxAttempts}</div>
            <h2>{run.jobName}</h2>
            <p>
              {run.task || "One execution of one logical unit of background work."}
              {run.clientName ? ` · ${run.clientName}` : run.clientId ? "" : " · platform-wide"}
            </p>
          </div>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        <div className="modal-body">
          {/* The verdict, in the server's own words. `succeeded` is printed, never
              inferred: exactly one definition of success exists and it lives there. */}
          <div className="ops-verdict">
            <span className={`status-pill ${meta.cls}`}>{meta.label}</span>
            <div>
              <div className="ops-verdict-t">{meta.meaning}</div>
              <div className="ops-verdict-s">
                Succeeded: <b>{run.succeeded ? "yes" : "no"}</b> · Needs attention:{" "}
                <b>{run.needsAttention ? "yes" : "no"}</b>
                {!run.succeeded && run.status === "degraded" && (
                  <> — a degraded run finished, but part of the promise was not kept.</>
                )}
              </div>
            </div>
          </div>

          {/* Guaranteed non-empty on degraded/blocked. Rendering the run without it
              is not a thing this component is allowed to do. */}
          {(run.reason || run.reasonCode) && (
            <div className="ops-sec">
              <div className="ops-sec-h">Why</div>
              <div className={`ops-why ${run.status === "failed" ? "crit" : "warn"}`}>
                <span className="material-symbols-rounded">
                  {run.status === "blocked" ? "block" : "warning"}
                </span>
                <span>
                  {run.reasonCode && <span className="ops-code">{run.reasonCode}</span>}{" "}
                  {run.reason || "No prose reason was recorded with this code."}
                </span>
              </div>
            </div>
          )}

          {(run.errorType || run.errorMessage) && (
            <div className="ops-sec">
              <div className="ops-sec-h">Error</div>
              <div className="ops-why crit">
                <span className="material-symbols-rounded">bug_report</span>
                <span>
                  <b>{run.errorType || "Error"}</b>
                  {run.errorMessage ? ` — ${run.errorMessage}` : ""}
                </span>
              </div>
            </div>
          )}

          {run.detail && !run.reason && (
            <div className="ops-sec">
              <div className="ops-sec-h">Detail</div>
              <div className="ops-fact-v">{run.detail}</div>
            </div>
          )}

          {previewUrl && (
            <div className="ops-sec">
              <div className="ops-sec-h">What this run produced</div>
              <a className="ops-btn primary" href={previewUrl} target="_blank" rel="noopener noreferrer">
                <span className="material-symbols-rounded">open_in_new</span>
                Open the preview
              </a>
            </div>
          )}

          <div className="ops-sec">
            <div className="ops-sec-h">The run</div>
            <div className="ops-facts">
              <Fact k="Client" v={run.clientName || (run.clientId ? "Unnamed client" : "Platform-wide")} />
              <Fact k="Queue" v={run.queue} />
              <Fact k="Task" v={run.task || "—"} mono />
              <Fact k="Attempt" v={`${run.attempt} of ${run.maxAttempts}`} />
              <Fact
                k="Duration"
                v={run.durationSeconds != null ? formatDuration(run.durationSeconds) : run.status === "running" ? "still running" : "—"}
              />
              <Fact k="Cost" v={usd(run.costUsd, 2)} />
              <Fact k="Scope" v={run.scopeType ? `${run.scopeType}${run.scopeId ? ` · ${run.scopeId}` : ""}` : "—"} mono />
              <Fact k="Created" v={whenText(run.createdAt)} />
              {/* Scheduled work only. Shown beside Started so "was it late?" is a
                  glance rather than an arithmetic exercise; absent for a run nobody
                  scheduled, because a manual run has no due time to be late against. */}
              {run.scheduledAt && <Fact k="Due at" v={whenText(run.scheduledAt)} />}
              <Fact k="Started" v={whenText(run.startedAt)} />
              <Fact k="Finished" v={whenText(run.finishedAt)} />
              <Fact k="Last heartbeat" v={whenText(run.heartbeatAt)} />
              {run.scheduledFor && <Fact k="Scheduled for" v={whenText(run.scheduledFor)} />}
            </div>
          </div>

          <div className="ops-sec">
            <div className="ops-sec-h">Tracing</div>
            <div className="ops-facts">
              <Fact k="Run id" v={run.id} mono />
              {/* One nightly sweep and the eighty per-client jobs it enqueued share
                  one correlation id — this is how a fan-out is reassembled. */}
              <Fact k="Correlation id" v={run.correlationId} mono />
              <Fact k="Idempotency key" v={run.idempotencyKey || "—"} mono />
              {run.parentRunId && <Fact k="Parent run" v={run.parentRunId} mono />}
            </div>
          </div>

          {run.result && Object.keys(run.result).length > 0 && <ResultBlock result={run.result} />}
        </div>

        <div className="modal-foot">
          {run.cancelRequested ? (
            <span className="ops-foot-note">
              <b>Cancellation requested.</b> The run stops at its next checkpoint — a job that
              never checkpoints cannot be stopped.
            </span>
          ) : canAct && cancellable ? (
            <div className="ops-cancel">
              <input
                type="text"
                maxLength={500}
                value={reason}
                placeholder="Why are you stopping this run? (required — recorded on the activity log)"
                onChange={(e) => setReason(e.target.value)}
                aria-label="Cancellation reason"
              />
              {/* The reason is REQUIRED, not decorative. Cancelling used to be a
                  single click with an optional note; the deliberation a written
                  reason forces is the confirmation step here, and it matches
                  resolving a dead letter. It is also the only record of WHY the
                  run stopped - the row itself only records that it was cancelled. */}
              <button
                type="button"
                className="ops-btn crit"
                disabled={cancel.isPending || reason.trim().length === 0}
                onClick={() => cancel.mutate({ runId: run.id, reason: reason.trim() })}
              >
                <span className="material-symbols-rounded">cancel</span>
                {cancel.isPending ? "Requesting…" : "Cancel this run"}
              </button>
            </div>
          ) : cancellable ? (
            <span className="ops-foot-note">
              Cancelling a run is a lead action (owner / admin / manager).
            </span>
          ) : (
            <span className="ops-foot-note">
              This run has finished — its outcome is the record, and cannot be overwritten.
            </span>
          )}
        </div>

        {cancelError && (
          <div style={{ padding: "0 26px 16px" }}>
            <div className="ops-err">
              <span className="material-symbols-rounded">error</span>
              <span>{cancelError}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Fact({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <div className="ops-fact-k">{k}</div>
      <div className={`ops-fact-v ${mono ? "mono" : ""}`}>{v}</div>
    </div>
  );
}
