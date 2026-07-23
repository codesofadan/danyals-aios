"use client";

import { useMemo } from "react";
import { useAudits } from "@/lib/hooks/audits";
import { downloadFile } from "@/lib/api";

// Reports library: every audit that has a STORED report file, listed and downloadable
// straight from the Reports tab. Data + files are the REAL /audits endpoints (GET
// /audits and the guarded /audits/{id}/report.pdf | /findings.json downloads) - no
// seed, no demo. An audit shows here once its worker has stored the artifacts.
export default function ReportsLibrary() {
  const auditsQ = useAudits();
  const rows = useMemo(
    () => (auditsQ.data ?? []).filter((a) => a.pdf || a.json),
    [auditsQ.data],
  );

  const muted: React.CSSProperties = { padding: "2rem 1rem", textAlign: "center", color: "var(--muted)" };

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Reports library</div>
          <div className="cs">Generated audit reports with a stored file - download the PDF or the findings JSON.</div>
        </div>
      </div>
      {auditsQ.isLoading ? (
        <div style={muted}>Loading reports...</div>
      ) : rows.length === 0 ? (
        <div style={muted}>No stored reports yet. Run an audit and its PDF appears here once generated.</div>
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
              {rows.map((a) => (
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
