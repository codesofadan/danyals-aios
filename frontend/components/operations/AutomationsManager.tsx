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

import { useMemo, useState } from "react";
import {
  useAutomationCapabilities,
  useAutomations,
  useCreateAutomation,
  useDeleteAutomation,
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
  const remove = useDeleteAutomation();
  const [confirming, setConfirming] = useState(false);

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
          {confirming ? (
            <>
              <button
                type="button"
                className="ghostbtn co-reject"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(a.id, { onError: fail, onSettled: () => setConfirming(false) })
                }
              >
                Delete for good
              </button>
              <button type="button" className="ghostbtn" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button type="button" className="ghostbtn" onClick={() => setConfirming(true)}>
              Delete
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

function CreateForm({ onClose, onError }: { onClose: () => void; onError: (m: string) => void }) {
  const capsQ = useAutomationCapabilities();
  const create = useCreateAutomation();
  const caps = useMemo(() => capsQ.data ?? [], [capsQ.data]);

  const [kind, setKind] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"interval" | "cron">("interval");
  const [minutes, setMinutes] = useState("60");
  const [cron, setCron] = useState("0 2 * * *");

  const chosen = caps.find((c) => c.kind === kind);
  // A client-scoped capability needs clients chosen, and this form does not collect
  // them yet - so it says so rather than letting someone save an automation the
  // server will refuse.
  const clientScoped = chosen?.scope === "client";
  const canSave = Boolean(kind && name.trim() && !clientScoped);

  return (
    <div className="card" style={{ padding: 16, marginBottom: 14, display: "grid", gap: 12 }}>
      <div className="fld">
        <label htmlFor="auto-kind">What should it do?</label>
        <select
          id="auto-kind"
          value={kind}
          onChange={(e) => {
            const next = caps.find((c) => c.kind === e.target.value);
            setKind(e.target.value);
            if (next) {
              setName((n) => n || next.label);
              setMinutes(String(Math.max(1, Math.round(next.defaultIntervalSeconds / 60))));
            }
          }}
        >
          <option value="">Choose…</option>
          {caps.map((c) => (
            <option key={c.kind} value={c.kind}>
              {c.label}
              {c.paid ? " (spends budget)" : ""}
            </option>
          ))}
        </select>
      </div>

      {chosen && (
        <div className="op-muted" style={{ fontSize: 13, lineHeight: 1.5 }}>
          {chosen.description}
          {chosen.needs.length > 0 && (
            <>
              {" "}
              Needs {chosen.needs.join(", ")}; without it a run reports that it could not
              do its work rather than failing silently.
            </>
          )}
          {clientScoped && (
            <div style={{ color: "var(--warn)", fontWeight: 600, marginTop: 6 }}>
              This one runs per client, and choosing clients isn&rsquo;t available on this
              form yet. Pick a platform-wide automation for now.
            </div>
          )}
        </div>
      )}

      <div className="fld">
        <label htmlFor="auto-name">Name</label>
        <input id="auto-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <div className="seg">
        <button className={mode === "interval" ? "on" : undefined} onClick={() => setMode("interval")}>
          Every…
        </button>
        <button className={mode === "cron" ? "on" : undefined} onClick={() => setMode("cron")}>
          At a set time
        </button>
      </div>

      {mode === "interval" ? (
        <div className="fld">
          <label htmlFor="auto-mins">Run every (minutes)</label>
          <input
            id="auto-mins"
            inputMode="numeric"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value.replace(/[^0-9]/g, ""))}
          />
          <div className="fld-hint">Minimum 1 minute — the dispatcher runs once a minute.</div>
        </div>
      ) : (
        <div className="fld">
          <label htmlFor="auto-cron">Schedule</label>
          <input id="auto-cron" value={cron} onChange={(e) => setCron(e.target.value)} />
          <div className="fld-hint">
            minute hour day-of-month month day-of-week — e.g. <code>0 2 * * *</code> for 02:00
            daily. Times are UTC.
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 10 }}>
        <button
          type="button"
          className="primary-btn"
          disabled={!canSave || create.isPending}
          onClick={() =>
            create.mutate(
              {
                name: name.trim(),
                kind,
                scheduleKind: mode,
                intervalSeconds: mode === "interval" ? Math.max(60, Number(minutes || 0) * 60) : null,
                cronExpr: mode === "cron" ? cron.trim() : null,
                // Created PAUSED. A schedule that starts running the moment it is
                // saved is a schedule nobody reviewed.
                enabled: false,
              },
              {
                onSuccess: onClose,
                onError: (err) =>
                  onError(err instanceof Error ? err.message : "That could not be created."),
              },
            )
          }
        >
          {create.isPending ? "Creating…" : "Create (paused)"}
        </button>
        <button type="button" className="ghostbtn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function AutomationsManager() {
  const autosQ = useAutomations();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const rows = autosQ.data ?? [];
  const live = rows.filter((a) => a.enabled).length;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Automations</div>
          <div className="cs">
            {autosQ.isError
              ? "Scheduled work."
              : `${live} of ${rows.length} running. Everything else is paused and does nothing until you enable it.`}
          </div>
        </div>
        <button type="button" className="primary-btn" onClick={() => setCreating((c) => !c)}>
          <span className="material-symbols-rounded">add</span>New automation
        </button>
      </div>

      {error && (
        <div style={{ padding: "0 16px 10px", color: "var(--crit)", fontWeight: 600, fontSize: 13 }}>
          {error}
        </div>
      )}

      {creating && (
        <div style={{ padding: "0 16px" }}>
          <CreateForm onClose={() => setCreating(false)} onError={setError} />
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
          No automations yet. Create one to have the platform do something on a schedule.
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
