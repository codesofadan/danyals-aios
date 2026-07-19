"use client";

import { useState } from "react";
import Link from "next/link";
import { DELIVERABLE_COLOR } from "@/lib/client";
import { clientReports } from "@/lib/data";
import { openFile, downloadFile } from "@/lib/api";
import { useClientDeliverables } from "@/lib/hooks/portalClient";
import { useClient } from "./ClientContext";
import ClientHeader from "./ClientHeader";

// The Reports section — downloadable deliverables (audits, monthly rollups,
// content & backlink reports). The backend already scopes the list to the
// client's granted, visible deliverables (an ungranted one is hidden by the
// RLS view); ungranted report TYPES surface as locked upsell rows.
export default function ClientReports() {
  const { isGranted } = useClient();
  const deliverablesQ = useClientDeliverables();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errorId, setErrorId] = useState<string | null>(null);

  const available = deliverablesQ.data ?? [];
  // Report surfaces not in the client's plan — an upsell to "request access".
  const lockedTypes = clientReports.filter((r) => !isGranted(r.key)).map((r) => r.key);

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

  async function download(id: string, title: string) {
    if (busyId) return;
    setBusyId(id);
    setErrorId(null);
    try {
      await downloadFile(`/portal/deliverables/${id}/download`, title);
    } catch {
      setErrorId(id);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="tw cl">
      <ClientHeader
        eyebrow=""
        focus={
          <>
            <span className="cl-focus-k">Reports library</span>
            <span className="cl-focus-v">{available.length} reports ready</span>
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
            <div className="pt-empty-s">Your first report will appear here once it's generated.</div>
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
                      <button className="primary-btn sm" type="button" onClick={() => download(d.id, d.title)} disabled={busyId === d.id}>
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

      {lockedTypes.length > 0 && (
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Available on request</div>
              <div className="cs">Reports outside your current plan — ask your account manager to enable them.</div>
            </div>
          </div>
          <div className="cl-rp-locked">
            {lockedTypes.map((key) => {
              const meta = clientReports.find((r) => r.key === key);
              if (!meta) return null;
              return (
                <div className="cl-rp-lockrow" key={key}>
                  <span className="cl-rp-lockic material-symbols-rounded">lock</span>
                  <div className="cl-rp-main">
                    <div className="cl-rp-t">{meta.label}</div>
                    <div className="cl-rp-meta">{meta.desc}</div>
                  </div>
                  <Link href="/client/requests" className="ghostbtn">
                    <span className="material-symbols-rounded">lock_open</span>Request
                  </Link>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
