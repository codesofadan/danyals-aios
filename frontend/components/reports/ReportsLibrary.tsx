"use client";

import { useMemo } from "react";
import { useAudits } from "@/lib/hooks/audits";
import { useGeneratedReports } from "@/lib/hooks/reports";
import { downloadFile } from "@/lib/api";

// Reports library: the REAL, downloadable reports the platform has produced — no seed,
// no demo. Two sources, both live:
//   1. Autonomous monthly SEO reports the scheduled job generates + stores
//      (GET /reports/generated, downloaded as JSON).
//   2. Every audit that has a stored report file (the weekly audit-refresh cron and any
//      hand-run audit) — the guarded /audits/{id}/report.pdf | /findings.json downloads.
export default function ReportsLibrary() {
  const generatedQ = useGeneratedReports();
  const auditsQ = useAudits();
  const reports = generatedQ.data ?? [];
  const audits = useMemo(
    () => (auditsQ.data ?? []).filter((a) => a.pdf || a.json),
    [auditsQ.data],
  );

  const muted: React.CSSProperties = {
    padding: "1.25rem 1rem",
    textAlign: "center",
    color: "var(--muted)",
  };

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Reports library</div>
          <div className="cs">
            Autonomous monthly SEO reports and generated audit reports — download the file.
          </div>
        </div>
      </div>

      {/* Autonomous monthly SEO reports (produced on a schedule, stored, downloadable). */}
      <div className="rp-lib-sub">Monthly SEO reports</div>
      {generatedQ.isLoading ? (
        <div style={muted}>Loading reports...</div>
      ) : reports.length === 0 ? (
        <div style={muted}>
          No monthly reports yet. The scheduled report job generates one per active client and
          it appears here.
        </div>
      ) : (
        <div className="tbl-wrap rp-tbl-wrap">
          <table className="tbl rp-tbl">
            <thead>
              <tr>
                <th>Client</th>
                <th>Report</th>
                <th>Period</th>
                <th>Summary</th>
                <th>When</th>
                <th className="rp-act-col">Download</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td className="rp-client">{r.client}</td>
                  <td>{r.title}</td>
                  <td>{r.period}</td>
                  <td className="rp-last">{r.headline || "—"}</td>
                  <td className="rp-last">{r.when}</td>
                  <td className="rp-act-col">
                    <button
                      type="button"
                      className="ghostbtn"
                      onClick={() =>
                        downloadFile(`/reports/generated/${r.id}/download`, `report-${r.id}.json`)
                      }
                    >
                      <span className="material-symbols-rounded">data_object</span>JSON
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Generated audit reports (weekly audit-refresh cron + hand-run audits). */}
      <div className="rp-lib-sub">Audit reports</div>
      {auditsQ.isLoading ? (
        <div style={muted}>Loading reports...</div>
      ) : audits.length === 0 ? (
        <div style={muted}>No stored audit reports yet. An audit&apos;s PDF appears here once generated.</div>
      ) : (
        <div className="tbl-wrap rp-tbl-wrap">
          <table className="tbl rp-tbl">
            <thead>
              <tr>
                <th>Client</th>
                <th>Site</th>
                <th>Tier</th>
                <th className="num">Score</th>
                <th>When</th>
                <th className="rp-act-col">Download</th>
              </tr>
            </thead>
            <tbody>
              {audits.map((a) => (
                <tr key={a.id}>
                  <td className="rp-client">{a.client}</td>
                  <td className="rp-mono">{a.url}</td>
                  <td>{a.tier}</td>
                  <td className="num">{a.score ?? "-"}</td>
                  <td className="rp-last">{a.when}</td>
                  <td className="rp-act-col">
                    {a.pdf && (
                      <button
                        type="button"
                        className="ghostbtn"
                        onClick={() => downloadFile(`/audits/${a.id}/report.pdf`, `audit-${a.id}.pdf`)}
                      >
                        <span className="material-symbols-rounded">picture_as_pdf</span>PDF
                      </button>
                    )}
                    {a.json && (
                      <button
                        type="button"
                        className="ghostbtn"
                        onClick={() => downloadFile(`/audits/${a.id}/findings.json`, `audit-${a.id}.json`)}
                      >
                        <span className="material-symbols-rounded">data_object</span>JSON
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
