"use client";

import { useState } from "react";
import { DELIVERABLE_COLOR } from "@/lib/client";
import { openFile, downloadFile } from "@/lib/api";
import { useClientDeliverables } from "@/lib/hooks/portalClient";
import ClientHeader from "./ClientHeader";

// Build a safe, human download filename that always carries a .pdf extension and
// stays unique across same-titled rows (title + period). Strips characters
// Windows forbids in filenames (\ / : * ? " < > |).
function buildFilename(title: string, period: string): string {
  const clean = (s: string) => s.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim();
  const base = clean(title);
  const per = clean(period);
  const stem = per && per.toLowerCase() !== "in progress" ? `${base} (${per})` : base;
  return `${stem || "deliverable"}.pdf`;
}

// The Reports section — downloadable deliverables (audits, monthly rollups,
// content & backlink reports). The backend already scopes the list to the
// client's granted, visible deliverables (an ungranted one is hidden by the
// RLS view); ungranted report TYPES surface as locked upsell rows.
export default function ClientReports() {
  const deliverablesQ = useClientDeliverables();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorId, setErrorId] = useState<string | null>(null);

  const available = deliverablesQ.data ?? [];
  // Only "ready" deliverables are downloadable — the backend 404s a download
  // while status === "generating", so an in-progress row must not be counted as
  // "ready" in the header.
  const readyCount = available.filter((d) => d.status === "ready").length;

  async function view(id: string) {
    if (busyId) return;
    setBusyId(id);
    setErrorId(null);
    try {
      await openFile(`/portal/deliverables/${id}/download`);
    } catch {
      setErrorId(id);
    } finally {
      setBusyId(null);
    }
  }

  async function download(id: string, title: string, period: string) {
    if (busyId) return;
    setBusyId(id);
    setErrorId(null);
    try {
      // A blob anchor's `download` attribute wins over the server's
      // Content-Disposition, so the name MUST carry a .pdf extension (else the
      // file saves extension-less and won't open by double-click on Windows).
      // Include the period so two same-titled rows (e.g. two "Monthly SEO
      // Report") don't collide to one filename.
      await downloadFile(`/portal/deliverables/${id}/download`, buildFilename(title, period));
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
            <span className="cl-focus-k">Reports library</span>
            <span className="cl-focus-v">{readyCount} report{readyCount === 1 ? "" : "s"} ready</span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">download</span>Download or view any report
            </span>
          </>
        }
      />

      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Your reports</div>
            <div className="cs">Branded audits and monthly rollups, ready to download.</div>
          </div>
        </div>

        {deliverablesQ.isLoading ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded spin">progress_activity</span>
            <div className="pt-empty-t">Loading your reports…</div>
          </div>
        ) : available.length === 0 ? (
          <div className="pt-empty sm">
            <span className="material-symbols-rounded">summarize</span>
            <div className="pt-empty-t">No reports yet</div>
            <div className="pt-empty-s">Your first report will appear here once it&apos;s generated.</div>
          </div>
        ) : (
          <div className="cl-rp-list">
            {available.map((d) => {
              const color = DELIVERABLE_COLOR[d.kind];
              const generating = d.status === "generating";
              return (
                <div className={`cl-rp-row${generating ? " gen" : ""}`} key={d.id}>
                  <span className="cl-rp-ic" style={{ ["--c" as string]: color }}>
                    <span className="material-symbols-rounded">{d.icon}</span>
                  </span>
                  <div className="cl-rp-main">
                    <div className="cl-rp-t">{d.title}</div>
                    <div className="cl-rp-meta">
                      <span className="cl-rp-kind" style={{ color }}>{d.kind}</span>
                      <span className="dot-sep">·</span>
                      <span>{d.period}</span>
                      <span className="dot-sep">·</span>
                      <span>{d.date}</span>
                    </div>
                  </div>
                  {generating ? (
                    <span className="cl-rp-gen">
                      <span className="material-symbols-rounded spin">progress_activity</span>Generating
                    </span>
                  ) : (
                    <div className="cl-rp-actions">
                      <span className="cl-rp-size">{d.size}</span>
                      {errorId === d.id && (
                        <span className="cl-rp-err" title="Couldn't open this report — try again.">
                          <span className="material-symbols-rounded">error</span>
                        </span>
                      )}
                      <button className="ghostbtn" type="button" onClick={() => view(d.id)} disabled={busyId === d.id}>
                        <span className="material-symbols-rounded">visibility</span>View
                      </button>
                      <button className="primary-btn sm" type="button" onClick={() => download(d.id, d.title, d.period)} disabled={busyId === d.id}>
                        <span className="material-symbols-rounded">download</span>Download
                      </button>
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
