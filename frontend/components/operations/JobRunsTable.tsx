"use client";

// ============================================================
// AIOS · Operations — THE RUNS LOG
//
// One row per execution of one logical unit of background work, newest first.
// Filterable by status (server-side, `?status=`) and by job name (server-side,
// `?jobName=`, an EXACT match — so the control is a picker over the names actually
// seen, not a free-text box that silently returns nothing).
//
// THE LINE THAT MAKES THIS A LOG RATHER THAN A WALL OF RED: a degraded or blocked
// run renders its `reason` inline, under the row. That field is GUARANTEED
// non-empty for those two states (a DB CHECK constraint refuses to store one that
// is not), so there is always something true to show — "partially succeeded, cause
// unknown" is not a state this API can emit. A failed run gets the same treatment
// from `errorType` / `errorMessage`.
//
// Status is NEVER shown without its meaning: every pill carries statusMeta's
// one-line definition as its title, and the legend under the table spells out the
// distinction the vocabulary exists to force.
// ============================================================

import { Fragment, useEffect, useState } from "react";
import { usd } from "@/lib/cost";
import { formatDuration, relativeTime, type JobRun, type JobStatus } from "@/lib/jobs";
import { statusChip, statusMeaning } from "./vocabulary";

const PAGE_SIZE = 25;

// "attention" is not a status — it is the router's own `needsAttention=true` view:
// every terminal run that was not a clean success (degraded | blocked | failed) in
// one list. Filtered SERVER-side, so the count is the real one, not this page's.
type Filter = "all" | "attention" | JobStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "attention", label: "Needs attention" },
  { key: "running", label: "Running" },
  { key: "queued", label: "Queued" },
  { key: "completed", label: "Completed" },
  { key: "degraded", label: "Degraded" },
  { key: "blocked", label: "Blocked" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
];

/** The `status=` query value for a chip — "all" and "attention" send none. */
function statusParam(f: Filter): JobStatus | undefined {
  return f === "all" || f === "attention" ? undefined : f;
}

/** The `needsAttention=` query value for a chip. */
function attentionParam(f: Filter): boolean {
  return f === "attention";
}

export default function JobRunsTable({
  rows,
  loading,
  fetching,
  page,
  onPage,
  filter,
  onFilter,
  jobName,
  onJobName,
  onOpenRun,
}: {
  rows: JobRun[];
  loading: boolean;
  fetching: boolean;
  page: number;
  onPage: (p: number) => void;
  filter: Filter;
  onFilter: (f: Filter) => void;
  jobName: string;
  onJobName: (n: string) => void;
  onOpenRun: (run: JobRun) => void;
}) {
  // A full page means there may be another after it (the API returns no total).
  const hasMore = rows.length === PAGE_SIZE;

  // `jobName` is an exact match server-side, so the picker offers only names the
  // board has actually seen. Accumulated across pages: filtering to one job would
  // otherwise collapse the list to the single option already selected.
  const [seenNames, setSeenNames] = useState<string[]>([]);
  useEffect(() => {
    if (rows.length === 0) return;
    setSeenNames((prev) => {
      const next = new Set(prev);
      for (const r of rows) next.add(r.jobName);
      return next.size === prev.length ? prev : [...next].sort();
    });
  }, [rows]);

  const pageCost = rows.reduce((s, r) => s + r.costUsd, 0);
  const pageAttention = rows.filter((r) => r.needsAttention).length;

  function changeFilter(f: Filter) {
    onFilter(f);
    onPage(0); // filtering restarts from the newest page
  }

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Job runs</div>
          <div className="cs">
            Every execution, newest first. A degraded or blocked run always states why.
          </div>
        </div>
        <div className="tools ops-tools">
          <select
            className="ops-select"
            value={jobName}
            aria-label="Filter by job name"
            onChange={(e) => {
              onJobName(e.target.value);
              onPage(0);
            }}
          >
            <option value="">All jobs</option>
            {seenNames.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <div className="log-filters">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className={filter === f.key ? "chip on" : "chip"}
                onClick={() => changeFilter(f.key)}
                title={
                  f.key === "all"
                    ? "Every run in the ledger"
                    : f.key === "attention"
                      ? "Degraded, blocked and failed — the three an operator must act on"
                      : statusMeaning(f.key)
                }
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="tbl-wrap">
        <table className="tbl ops-tbl">
          <thead>
            <tr>
              <th>Job</th>
              <th>Client</th>
              <th>Queue</th>
              <th>Status</th>
              <th className="num">Attempt</th>
              <th className="num">Duration</th>
              <th className="num">Cost</th>
              <th className="num">Finished</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const meta = statusChip(r.status);
              // Guaranteed present on degraded/blocked; failed carries error_type
              // instead (job_runs_error_required_ck). Either way an attention row
              // explains itself without being opened.
              const why = r.reason || r.errorMessage || r.detail;
              const showWhy = r.needsAttention && Boolean(why || r.errorType);
              return (
                <Fragment key={r.id}>
                  <tr
                    className="ops-row"
                    tabIndex={0}
                    role="button"
                    aria-label={`Open run ${r.jobName} (${meta.label})`}
                    onClick={() => onOpenRun(r)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onOpenRun(r);
                      }
                    }}
                  >
                    <td>
                      <div className="ops-job">{r.jobName}</div>
                      {r.task && <div className="ops-task">{r.task}</div>}
                    </td>
                    <td className={r.clientId ? "ops-cli" : "ops-cli plat"}>
                      {r.clientName || (r.clientId ? "Unnamed client" : "Platform-wide")}
                    </td>
                    <td><span className="ops-q">{r.queue}</span></td>
                    <td>
                      <span className={`status-pill ${meta.cls}`} title={meta.meaning}>
                        {meta.label}
                      </span>
                    </td>
                    <td className={`num ops-att ${r.attempt > 1 ? "retried" : ""}`}>
                      {r.attempt}/{r.maxAttempts}
                    </td>
                    {/* formatDuration returns "" for an unfinished run rather than a
                        fake "0s", so the placeholder is chosen here. */}
                    <td className="num ops-dur">
                      {formatDuration(r.durationSeconds) ||
                        (r.status === "running" ? "running…" : "—")}
                    </td>
                    <td className={`num ops-cost ${r.costUsd === 0 ? "zero" : ""}`}>
                      {usd(r.costUsd, 2)}
                    </td>
                    <td className="num ops-when">
                      {relativeTime(r.finishedAt) || "—"}
                    </td>
                  </tr>
                  {showWhy && (
                    <tr className="ops-why-row">
                      <td colSpan={8}>
                        <div className={`ops-why ${r.status === "failed" ? "crit" : "warn"}`}>
                          <span className="material-symbols-rounded">
                            {r.status === "failed" ? "bug_report" : r.status === "blocked" ? "block" : "warning"}
                          </span>
                          <span>
                            {r.reasonCode && <span className="ops-code">{r.reasonCode}</span>}
                            {r.reasonCode && " "}
                            {r.errorType && <b>{r.errorType}: </b>}
                            {why || "No further detail was recorded."}
                          </span>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8}>
                  <div className="ops-empty">
                    <span className="material-symbols-rounded">
                      {loading ? "hourglass_top" : "inbox"}
                    </span>
                    <div className="ops-empty-t">
                      {loading
                        ? "Loading runs…"
                        : filter === "all" && !jobName
                          ? "No runs in the ledger yet"
                          : "Nothing matches this filter"}
                    </div>
                    <div className="ops-empty-s">
                      {loading
                        ? "Reading the job ledger."
                        : filter === "attention"
                          ? "Nothing is degraded, blocked or failed. Every terminal run was a clean success."
                          : "Every job the platform runs lands here — clear the filters to see the rest."}
                    </div>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="ops-foot">
        <span>
          <b>{rows.length}</b> {rows.length === 1 ? "run" : "runs"} on this page ·{" "}
          <b>{pageAttention}</b> needing attention · <b>{usd(pageCost, 2)}</b> spent
          {filter === "attention" && " · narrowed within this page"}
        </span>
        <div className="ops-pager">
          <button
            type="button"
            className="ops-pager-btn"
            onClick={() => onPage(Math.max(0, page - 1))}
            disabled={page === 0 || fetching}
          >
            <span className="material-symbols-rounded">chevron_left</span>Newer
          </button>
          <span className="ops-pager-pos">Page {page + 1}</span>
          <button
            type="button"
            className="ops-pager-btn"
            onClick={() => onPage(page + 1)}
            disabled={!hasMore || fetching}
          >
            Older<span className="material-symbols-rounded">chevron_right</span>
          </button>
        </div>
      </div>

      <div className="ops-note">
        <span className="material-symbols-rounded">info</span>
        <span>
          <b>Completed</b> is the only success. <b>Degraded</b> finished but did not keep
          the whole promise, <b>blocked</b> deliberately did not spend, <b>failed</b> hit
          an error it could not recover from, <b>cancelled</b> was stopped by a person.
          Click any row for the full record.
        </span>
      </div>
    </section>
  );
}

export { PAGE_SIZE, statusParam, attentionParam };
export type { Filter };
