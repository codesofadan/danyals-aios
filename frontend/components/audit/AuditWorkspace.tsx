"use client";

import { useState } from "react";
import {
  auditTypes,
  TYPE_LABEL,
  type AuditTypeKey,
  type JobStatus,
} from "@/lib/audit";
import { useAudits, useAuditStats, useCreateAudit } from "@/lib/hooks/audits";
import { useClients } from "@/lib/hooks/clients";
import { downloadFile } from "@/lib/api";
import AuditStats from "./AuditStats";
import AuditScoreHistogram from "./AuditScoreHistogram";

const STATUS_META: Record<JobStatus, { pill: string; label: string; icon: string }> = {
  queued: { pill: "mut", label: "Queued", icon: "schedule" },
  running: { pill: "info", label: "Running", icon: "progress_activity" },
  done: { pill: "ok", label: "Done", icon: "check_circle" },
  failed: { pill: "warn", label: "Failed", icon: "error" },
};

function scoreClass(score: number) {
  if (score >= 80) return "ok";
  if (score >= 65) return "warn";
  return "crit";
}

export default function AuditWorkspace() {
  const auditsQ = useAudits(); // live: GET /audits, polls while a job is in flight
  const statsQ = useAuditStats();
  const clientsQ = useClients();
  const createAudit = useCreateAudit();

  const rows = auditsQ.data ?? [];
  const clients = clientsQ.data ?? [];

  // Run-new-audit form state (URL + client only — every dashboard audit is the FULL
  // comprehensive run, so there are no tier/type options to pick).
  const [url, setUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const effectiveClientId = clientId || clients[0]?.id || "";

  // Table filters
  const [statusFilter, setStatusFilter] = useState<"all" | JobStatus>("all");
  const [typeFilter, setTypeFilter] = useState<"all" | AuditTypeKey>("all");

  const canRun = url.trim().length > 3 && !!effectiveClientId && !createAudit.isPending;

  const runAudit = () => {
    if (!canRun) return;
    const clean = url.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    // The backend ALWAYS runs the full comprehensive audit (on-page + technical +
    // off-page + local + 21 AI agents + PDF) for dashboard runs; the tier/types below
    // are just the free-allowed defaults the worker ignores for depth.
    createAudit.mutate(
      { client_id: effectiveClientId, url: clean, tier: "Free", types: ["technical", "actionable"] },
      { onSuccess: () => setUrl("") },
    );
  };

  const shown = rows.filter(
    (r) =>
      (statusFilter === "all" || r.status === statusFilter) &&
      (typeFilter === "all" || r.types.includes(typeFilter)),
  );

  const runningCount = rows.filter((r) => r.status === "running").length;
  const createErr = createAudit.error instanceof Error ? createAudit.error.message : null;

  return (
    <>
      <AuditStats
        runningNow={runningCount}
        thisMonth={statsQ.data?.thisMonth ?? rows.length}
        avgScore={statsQ.data?.avgScore ?? 0}
        turnaroundMin={statsQ.data?.turnaroundMin ?? 0}
      />

      <div className="row">
        {/* Audit queue / history */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Audit Queue &amp; History</div>
              <div className="cs">queued → running → done · artifacts stored to the client&apos;s Google Sheet</div>
            </div>
          </div>

          <div className="au-filters">
            <div className="seg">
              {(["all", "queued", "running", "done", "failed"] as const).map((s) => (
                <button key={s} className={statusFilter === s ? "on" : undefined} onClick={() => setStatusFilter(s)}>
                  {s === "all" ? "All" : STATUS_META[s].label}
                </button>
              ))}
            </div>
            <div className="au-chips">
              <button className={`chip${typeFilter === "all" ? " on" : ""}`} onClick={() => setTypeFilter("all")}>All types</button>
              {auditTypes.map((t) => (
                <button key={t.key} className={`chip${typeFilter === t.key ? " on" : ""}`} onClick={() => setTypeFilter(t.key)}>
                  {t.short}
                </button>
              ))}
            </div>
          </div>

          <div className="tbl-wrap">
            <table className="tbl au-tbl">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Site / URL</th>
                  <th>Type</th>
                  <th>Tier</th>
                  <th>Status</th>
                  <th className="num">Score</th>
                  <th>Artifacts</th>
                  <th className="num">Run time</th>
                </tr>
              </thead>
              <tbody>
                {auditsQ.isLoading && (
                  <tr><td colSpan={8} className="au-empty">Loading audits…</td></tr>
                )}
                {auditsQ.isError && !auditsQ.isLoading && (
                  <tr><td colSpan={8} className="au-empty">Couldn&apos;t load audits — {(auditsQ.error as Error)?.message ?? "try again"}.</td></tr>
                )}
                {!auditsQ.isLoading && !auditsQ.isError && shown.map((r) => {
                  const sm = STATUS_META[r.status];
                  return (
                    <tr key={r.id}>
                      <td>
                        <div className="au-client">{r.client}</div>
                        <div className="au-when">{r.when}</div>
                      </td>
                      <td><span className="au-url"><span className="material-symbols-rounded">link</span>{r.url}</span></td>
                      <td>
                        <div className="au-types">
                          {r.types.map((k) => (
                            <span key={k} className="au-type-tag">{TYPE_LABEL[k]}</span>
                          ))}
                        </div>
                      </td>
                      <td><span className={`au-tier ${r.tier.toLowerCase()}`}>{r.tier}</span></td>
                      <td>
                        <span className={`status-pill ${sm.pill}`}>
                          <span className={`material-symbols-rounded${r.status === "running" ? " au-spin" : ""}`}>{sm.icon}</span>
                          {sm.label}
                        </span>
                      </td>
                      <td className="num">
                        {r.score === null ? (
                          <span className="au-dash">—</span>
                        ) : (
                          <span className={`au-score ${scoreClass(r.score)}`}>{r.score}</span>
                        )}
                      </td>
                      <td>
                        <div className="au-arts">
                          <button
                            className="au-art"
                            title="Download PDF report"
                            disabled={!r.pdf}
                            onClick={() =>
                              downloadFile(`/audits/${r.id}/report.pdf`, `${r.client}-audit-${r.id}.pdf`)
                            }
                          >
                            <span className="material-symbols-rounded">picture_as_pdf</span>
                          </button>
                          <button
                            className="au-art"
                            title="Download findings JSON"
                            disabled={!r.json}
                            onClick={() =>
                              downloadFile(`/audits/${r.id}/findings.json`, `${r.client}-findings-${r.id}.json`)
                            }
                          >
                            <span className="material-symbols-rounded">data_object</span>
                          </button>
                        </div>
                      </td>
                      <td className="num au-runtime">{r.runtime}</td>
                    </tr>
                  );
                })}
                {!auditsQ.isLoading && !auditsQ.isError && shown.length === 0 && (
                  <tr><td colSpan={8} className="au-empty">No audits match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Run new audit */}
        <section className="card au-run">
          <div className="card-h">
            <div>
              <div className="ct">Run New Audit</div>
              <div className="cs">A URL is all the engine needs — it runs as an async job</div>
            </div>
          </div>

          <div className="fld">
            <label>Site URL</label>
            <input
              placeholder="northpeakdental.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runAudit()}
            />
          </div>

          <div className="fld">
            <label>Client</label>
            <select
              value={effectiveClientId}
              onChange={(e) => setClientId(e.target.value)}
              disabled={clients.length === 0}
            >
              {clients.length === 0 ? (
                <option value="">{clientsQ.isLoading ? "Loading clients…" : "No clients yet"}</option>
              ) : (
                clients.map((c) => <option key={c.id} value={c.id}>{c.cn}</option>)
              )}
            </select>
          </div>

          <div className="fld-hint" style={{ margin: "2px 0 10px" }}>
            <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: "16px" }}>bolt</span>{" "}
            Every audit is the <b>full run</b> — on-page, technical, off-page, local, AI
            analysis + a branded PDF report. No options to pick.
          </div>

          <button className="primary-btn wide" onClick={runAudit} disabled={!canRun}>
            <span className="material-symbols-rounded">rocket_launch</span>
            {createAudit.isPending ? "Starting…" : "Run audit"}
          </button>
          {createErr && (
            <div className="au-run-note" role="alert" style={{ color: "var(--warn, #A96913)" }}>
              <span className="material-symbols-rounded">error</span>
              {createErr}
            </div>
          )}
          <div className="au-run-note">
            <span className="material-symbols-rounded">auto_awesome</span>
            On completion: PDF + JSON + scores, the milestone auto-advances and the client is notified.
          </div>
        </section>
      </div>

      <div className="row-single">
        <AuditScoreHistogram rows={rows} />
      </div>
    </>
  );
}
