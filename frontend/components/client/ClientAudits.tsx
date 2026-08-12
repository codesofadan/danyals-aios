"use client";

import { useState } from "react";
import { SERIES } from "@/lib/data";
import { TYPE_LABEL } from "@/lib/audit";
import { openFile, downloadFile } from "@/lib/api";
import { useClientAudits, type PortalAudit } from "@/lib/hooks/portalClient";
import ClientHeader from "./ClientHeader";

// The Audits section — the client's OWN SEO audit runs, wired to
// GET /portal/audits (RLS-scoped to this tenant). Each completed run exposes
// its branded PDF + findings JSON straight from the artifact store
// (GET /portal/audits/{id}/report.pdf|findings.json); a queued/running run shows
// a live status pill and the list auto-polls until it settles.
const STATUS_META: Record<PortalAudit["status"], { label: string; cls: string; icon: string }> = {
  done: { label: "Complete", cls: "ok", icon: "check_circle" },
  running: { label: "Running", cls: "info", icon: "sync" },
  queued: { label: "Queued", cls: "mut", icon: "schedule" },
  failed: { label: "Failed", cls: "warn", icon: "error" },
};

export default function ClientAudits() {
  const auditsQ = useClientAudits();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorId, setErrorId] = useState<string | null>(null);

  const audits = auditsQ.data ?? [];
  const completed = audits.filter((a) => a.status === "done").length;

  async function view(id: string) {
    if (busyId) return;
    setBusyId(id);
    setErrorId(null);
    try {
      await openFile(`/portal/audits/${id}/report.pdf`);
    } catch {
      setErrorId(id);
    } finally {
      setBusyId(null);
    }
  }

  async function download(id: string, path: string, name: string) {
    if (busyId) return;
    setBusyId(id);
    setErrorId(null);
    try {
      await downloadFile(`/portal/audits/${id}/${path}`, name);
    } catch {
      setErrorId(id);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="tw cl">
      <ClientHeader
        focus={
          <>
            <span className="cl-focus-k">Your audits</span>
            <span className="cl-focus-v">{completed} completed report{completed === 1 ? "" : "s"}</span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">fact_check</span>Full audit PDFs, ready to open
            </span>
          </>
        }
      />

      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Audit runs</div>
            <div className="cs">Every SEO audit run for your sites — download the PDF or the raw findings.</div>
          </div>
        </div>

        {auditsQ.isLoading ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded spin">progress_activity</span>
            <div className="pt-empty-t">Loading your audits…</div>
          </div>
        ) : auditsQ.isError ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">error</span>
            <div className="pt-empty-t">Couldn&apos;t load your audits</div>
            <div className="pt-empty-s">There was a problem reaching the server.</div>
            <button className="primary-btn sm" type="button" onClick={() => auditsQ.refetch()} style={{ marginTop: 12 }}>
              <span className="material-symbols-rounded">refresh</span>Retry
            </button>
          </div>
        ) : audits.length === 0 ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">fact_check</span>
            <div className="pt-empty-t">No audits yet</div>
            <div className="pt-empty-s">Your first SEO audit will appear here once your team runs it.</div>
          </div>
        ) : (
          <div className="cl-rp-list">
            {audits.map((a) => {
              const sm = STATUS_META[a.status];
              const pending = a.status === "queued" || a.status === "running";
              const types = a.types.length ? a.types.map((t) => TYPE_LABEL[t]).join(" · ") : "Full audit";
              return (
                <div className={`cl-rp-row${pending ? " gen" : ""}`} key={a.id}>
                  <span className="cl-rp-ic" style={{ ["--c" as string]: SERIES.c4 }}>
                    <span className="material-symbols-rounded">fact_check</span>
                  </span>
                  <div className="cl-rp-main">
                    <div className="cl-rp-t">{a.url}</div>
                    <div className="cl-rp-meta">
                      <span className="cl-rp-kind" style={{ color: SERIES.c4 }}>{a.tier}</span>
                      <span className="dot-sep">·</span>
                      <span>{types}</span>
                      <span className="dot-sep">·</span>
                      <span>{a.when}</span>
                      {a.status === "done" && a.score !== null && (
                        <>
                          <span className="dot-sep">·</span>
                          <span>Score {a.score}/100</span>
                        </>
                      )}
                    </div>
                  </div>
                  {pending ? (
                    <span className="cl-rp-gen">
                      <span className={`material-symbols-rounded${a.status === "running" ? " spin" : ""}`}>{sm.icon}</span>{sm.label}
                    </span>
                  ) : (
                    <div className="cl-rp-actions">
                      <span className={`status-pill ${sm.cls}`}>
                        <span className="material-symbols-rounded" style={{ fontSize: 13 }}>{sm.icon}</span>{sm.label}
                      </span>
                      {errorId === a.id && (
                        <span className="cl-rp-err" title="Couldn't open this audit — try again.">
                          <span className="material-symbols-rounded">error</span>
                        </span>
                      )}
                      {a.pdf && (
                        <>
                          <button className="ghostbtn" type="button" onClick={() => view(a.id)} disabled={busyId === a.id}>
                            <span className="material-symbols-rounded">visibility</span>View
                          </button>
                          <button
                            className="primary-btn sm"
                            type="button"
                            onClick={() => download(a.id, "report.pdf", `audit-${a.id}.pdf`)}
                            disabled={busyId === a.id}
                          >
                            <span className="material-symbols-rounded">download</span>PDF
                          </button>
                        </>
                      )}
                      {a.json && (
                        <button
                          className="ghostbtn"
                          type="button"
                          onClick={() => download(a.id, "findings.json", `audit-${a.id}.json`)}
                          disabled={busyId === a.id}
                        >
                          <span className="material-symbols-rounded">data_object</span>JSON
                        </button>
                      )}
                      {a.json && (
                        <button
                          className="ghostbtn"
                          type="button"
                          onClick={() => download(a.id, "sheets/remediation.xlsx", `audit-${a.id}-remediation.xlsx`)}
                          disabled={busyId === a.id}
                        >
                          <span className="material-symbols-rounded">table_view</span>Sheets
                        </button>
                      )}
                      {!a.pdf && !a.json && a.status === "done" && (
                        <span className="cl-rp-size">No files</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
