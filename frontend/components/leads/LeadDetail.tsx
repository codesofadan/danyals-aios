"use client";

// One free-audit lead, in full - the funnel's dead end, opened.
//
// /admin/pipeline was terminal: a row, two download buttons, nothing else. The
// backend has always returned the WHOLE report for a lead's token (status,
// report.html, PDF, findings.json); this page puts it at a URL, so "look at
// what this prospect's audit found" is a link a teammate can be sent.
//
// WHAT IS DELIBERATELY ABSENT: convert-to-client and assign. The backend has no
// lead-mutation route - leads are read-only by design today - and a button that
// fakes a capability is exactly what this rebuild removes. When a conversion
// route lands, its actions belong in this header.

import Link from "next/link";
import { useCallback, useState } from "react";
import { useLeads, type PublicAuditLead } from "@/lib/hooks/leads";
import { downloadFile, getReportHtml } from "@/lib/api";
import { formatWhen, relativeTime } from "@/lib/format";
import DetailShell from "@/components/ui/DetailShell";
import EmptyState from "@/components/ui/EmptyState";
import ReportViewer from "@/components/report/ReportViewer";

const STATUS_CLS: Record<PublicAuditLead["status"], string> = {
  queued: "mut", running: "info", done: "ok", failed: "crit",
};

export default function LeadDetail({ token }: { token: string }) {
  const leadsQ = useLeads();
  const [viewing, setViewing] = useState(false);
  const lead = leadsQ.data?.find((l) => l.report_token === token);
  const loadReport = useCallback(
    () => getReportHtml(`/public/audits/${token}/report.html`),
    [token],
  );

  if (leadsQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load the lead</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/pipeline">Back to Pipeline</Link></div>
      </section>
    );
  }
  if (leadsQ.isLoading) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading lead…</div>;
  }
  if (!lead) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">No lead for this token</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/pipeline">Back to Pipeline</Link></div>
      </section>
    );
  }

  return (
    <>
      <DetailShell
        eyebrow="Pipeline · free-audit lead"
        title={lead.email}
        statusPill={<span className={`status-pill ${STATUS_CLS[lead.status]}`}>{lead.status}</span>}
        facts={[
          { label: "Site", value: lead.url },
          { label: "Score", value: lead.score ?? "—" },
          { label: "Source", value: lead.source || "landing page" },
          { label: "Captured", value: `${formatWhen(lead.created_at)} (${relativeTime(lead.created_at)})` },
          ...(lead.error ? [{ label: "Error", value: lead.error }] : []),
        ]}
        actions={
          <>
            {lead.has_report && (
              <button type="button" className="primary-btn" onClick={() => setViewing(true)}>
                <span className="material-symbols-rounded">visibility</span>View report
              </button>
            )}
            {lead.has_pdf && (
              <button
                type="button" className="ghostbtn"
                onClick={() => downloadFile(`/public/audits/${token}/report.pdf`, `${lead.url}-audit.pdf`)}
              >
                <span className="material-symbols-rounded">download</span>PDF
              </button>
            )}
            <button
              type="button" className="ghostbtn"
              onClick={() => downloadFile(`/public/audits/${token}/findings.json`, `${lead.url}-findings.json`)}
            >
              <span className="material-symbols-rounded">data_object</span>findings.json
            </button>
          </>
        }
        tabs={[{ key: "report", label: "Report", icon: "fact_check" }]}
      >
        {() =>
          lead.has_report ? (
            <section className="card" style={{ padding: "var(--s-7)" }}>
              <div className="cs" style={{ maxWidth: 560 }}>
                The full engine report for {lead.url} — the same document the PDF is
                rendered from. Open it with <b>View report</b> above.
              </div>
            </section>
          ) : (
            <EmptyState
              icon="hourglass_top"
              title={lead.status === "failed" ? "The audit failed" : "No report yet"}
              hint={
                lead.status === "failed"
                  ? lead.error || "The engine did not produce a report for this run."
                  : "The report appears here once the audit finishes."
              }
            />
          )
        }
      </DetailShell>
      {viewing && (
        <ReportViewer
          load={loadReport}
          label={`${lead.url} — free audit`}
          onClose={() => setViewing(false)}
          onDownloadPdf={
            lead.has_pdf
              ? () => downloadFile(`/public/audits/${token}/report.pdf`, `${lead.url}-audit.pdf`)
              : undefined
          }
        />
      )}
    </>
  );
}
