"use client";

// One free-audit lead, in full - the funnel's dead end, opened.
//
// /admin/leads was terminal: a row, two download buttons, nothing else. The
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
import { useLead, type PublicAuditLead } from "@/lib/hooks/leads";
import { downloadFile, getReportHtml } from "@/lib/api";
import { formatWhen, relativeTime } from "@/lib/format";
import DetailShell from "@/components/ui/DetailShell";
import EmptyState from "@/components/ui/EmptyState";
import ReportViewer from "@/components/report/ReportViewer";

const STATUS_CLS: Record<PublicAuditLead["status"], string> = {
  queued: "mut", running: "info", done: "ok", failed: "crit",
};

export default function LeadDetail({ token }: { token: string }) {
  // Read by token, not by scanning the newest page of the inbox: an older lead's
  // link used to resolve to "no lead for this token" while its report existed.
  const leadQ = useLead(token);
  const [viewing, setViewing] = useState(false);
  const lead = leadQ.data;
  const loadReport = useCallback(
    () => getReportHtml(`/public/audits/${token}/report.html`),
    [token],
  );

  if (leadQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load the lead</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/leads">Back to Pipeline</Link></div>
      </section>
    );
  }
  if (leadQ.isLoading) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading lead…</div>;
  }
  if (!lead) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">No lead for this token</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/leads">Back to Pipeline</Link></div>
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
            {/* The client-facing page. The audit has published one all along and the
                operator had no route to it -- so the artifact meant for the lead was
                the one thing this screen could not hand them. */}
            {lead.publicSlug && (
              <a
                className="ghostbtn"
                href={`/leads/${lead.publicSlug}`}
                target="_blank"
                rel="noopener noreferrer"
                title={`Open the shareable report page (/leads/${lead.publicSlug})`}
              >
                <span className="material-symbols-rounded">public</span>Public page
                <span className="material-symbols-rounded">open_in_new</span>
              </a>
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
