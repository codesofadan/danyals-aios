"use client";

// ============================================================
// AIOS · Automations — scheduled work an admin can see, change and switch off.
//
// This replaces a read-only panel that could only ever show what a developer had put
// in a static beat schedule. That schedule was emptied on 2026-08-19, so the panel
// honestly rendered zero rows: nothing recurring ran at all - no nightly backup, no
// scheduled content publishing, no citation liveness re-check, no monthly reports.
//
// It had to be emptied wholesale, because a static schedule is read at process start:
// pausing one entry, re-timing one, or scoping one to particular clients each needed a
// developer and a deploy. They are rows now, and this is where they are managed.
//
// EVERYTHING STARTS PAUSED, and every row says whether running it SPENDS MONEY before
// anyone switches it on.
// ============================================================

import { useState } from "react";
import {
  useAutomations,
  useRunAutomationNow,
  useUpdateAutomation,
  type Automation,
} from "@/lib/hooks/jobs";
import { statusChip } from "./vocabulary";

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** The outcome of the last run, or an honest "not yet" - which is a different thing
 *  from a failure and must not be rendered as one. */
function LastRun({ a }: { a: Automation }) {
  if (!a.lastStatus) {
    return <span className="op-muted">Not run yet</span>;
  }
  // Every status pill carries its MEANING as a title, the rule the rest of
  // Operations follows - "degraded" is not self-explanatory to anyone.
  const chip = statusChip(a.lastStatus);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className={`status-pill ${chip.cls}`} title={chip.meaning}>
        {chip.label}
      </span>
      <span className="op-muted">{when(a.lastFinishedAt ?? a.lastFiredAt)}</span>
    </span>
  );
}

function Row({ a, onError }: { a: Automation; onError: (m: string) => void }) {
  const update = useUpdateAutomation();
  const runNow = useRunAutomationNow();

  const fail = (err: unknown) =>
    onError(err instanceof Error ? err.message : "That could not be changed.");

  return (
    <tr>
      <td>
        <div style={{ fontWeight: 700 }}>{a.name}</div>
        <div className="op-muted" style={{ fontSize: 12 }}>
          {a.kindLabel}
          {a.paid && (
            <>
              {" · "}
              {/* The one thing an operator must know before enabling: this one bills. */}
              <span style={{ color: "var(--warn)", fontWeight: 700 }}>spends budget</span>
            </>
          )}
        </div>
      </td>
      <td>{a.cadence}</td>
      <td>{a.enabled ? when(a.nextDueAt) : <span className="op-muted">Paused</span>}</td>
      <td>
        <LastRun a={a} />
        {a.lastDetail && (
          <div className="op-muted" style={{ fontSize: 12, marginTop: 2 }}>{a.lastDetail}</div>
        )}
      </td>
      <td>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button
            type="button"
            className={a.enabled ? "ghostbtn" : "primary-btn"}
            disabled={update.isPending}
            onClick={() =>
              update.mutate({ id: a.id, changes: { enabled: !a.enabled } }, { onError: fail })
            }
          >
            {a.enabled ? "Pause" : "Enable"}
          </button>
          <button
            type="button"
            className="ghostbtn"
            disabled={runNow.isPending}
            title="Fire it once now without changing its schedule"
            onClick={() => runNow.mutate(a.id, { onError: fail })}
          >
            Run now
          </button>
        </div>
      </td>
    </tr>
  );
}

export default function AutomationsManager() {
  const autosQ = useAutomations();
  const [error, setError] = useState("");

  const rows = autosQ.data ?? [];
  const live = rows.filter((a) => a.enabled).length;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          {/* No "New automation" button, and the POST route 405s to match. The
              platform seeds ONE automation per module it actually has (0128); an
              admin decides whether each runs and how often, not what exists. */}
          <div className="ct">Automations</div>
          <div className="cs">
            {autosQ.isError
              ? "Scheduled work."
              : `${live} of ${rows.length} running. Everything else is paused and does nothing until you enable it.`}
          </div>
        </div>
      </div>

      {error && (
        <div style={{ padding: "0 16px 10px", color: "var(--crit)", fontWeight: 600, fontSize: 13 }}>
          {error}
        </div>
      )}

      {autosQ.isLoading ? (
        <div className="op-muted" style={{ padding: 18 }}>Loading automations…</div>
      ) : autosQ.isError ? (
        // A failed fetch is not "no automations". Telling an operator nothing is
        // scheduled when the request simply failed is the defect this panel exists
        // to stop repeating.
        <div style={{ padding: 18, color: "var(--crit)", fontWeight: 600, fontSize: 13 }}>
          Couldn&rsquo;t load automations.{" "}
          <button type="button" className="ghostbtn" onClick={() => void autosQ.refetch()}>
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="op-muted" style={{ padding: 18 }}>
          No automations are set up. The platform seeds one per module on deploy — if
          this is empty, the seed migration has not run on this environment.
        </div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl ops-tbl">
            <thead>
              <tr>
                <th>Automation</th>
                <th>Runs</th>
                <th>Next</th>
                <th>Last run</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <Row key={a.id} a={a} onError={setError} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
