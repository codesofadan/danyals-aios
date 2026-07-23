"use client";

import { useMemo, useState } from "react";
import { downloadFile } from "@/lib/api";
import { useLeads, type LeadStatus, type PublicAuditLead } from "@/lib/hooks/leads";

const STATUS_META: Record<LeadStatus, { pill: string; label: string; icon: string }> = {
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

// "2026-07-23T14:03:00Z" → "23 Jul, 14:03" (best-effort; falls back to the raw string).
function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function LeadsWorkspace() {
  const leadsQ = useLeads();
  const rows = useMemo(() => leadsQ.data ?? [], [leadsQ.data]);

  const [statusFilter, setStatusFilter] = useState<"all" | LeadStatus>("all");
  const [q, setQ] = useState("");

  const kpis = useMemo(() => {
    const done = rows.filter((r) => r.status === "done");
    const scored = done.filter((r) => r.score !== null) as (PublicAuditLead & { score: number })[];
    const avg = scored.length
      ? Math.round(scored.reduce((s, r) => s + r.score, 0) / scored.length)
      : 0;
    return {
      total: rows.length,
      done: done.length,
      inFlight: rows.filter((r) => r.status === "queued" || r.status === "running").length,
      failed: rows.filter((r) => r.status === "failed").length,
      avgScore: avg,
    };
  }, [rows]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (statusFilter === "all" || r.status === statusFilter) &&
        (needle === "" ||
          r.email.toLowerCase().includes(needle) ||
          r.url.toLowerCase().includes(needle)),
    );
  }, [rows, statusFilter, q]);

  return (
    <>
      <div className="lead-kpis">
        <div className="kpi">
          <div className="lab">Total leads</div>
          <div className="lead-kpi-n">{kpis.total}</div>
          <div className="kpi-sub">emails captured by the free-audit funnel</div>
        </div>
        <div className="kpi">
          <div className="lab">Completed</div>
          <div className="lead-kpi-n">{kpis.done}</div>
          <div className="kpi-sub">report generated &amp; ready to view</div>
        </div>
        <div className="kpi">
          <div className="lab">In progress</div>
          <div className="lead-kpi-n">{kpis.inFlight}</div>
          <div className="kpi-sub">queued or running right now</div>
        </div>
        <div className="kpi">
          <div className="lab">Avg score</div>
          <div className="lead-kpi-n">{kpis.avgScore || "—"}</div>
          <div className="kpi-sub">{kpis.failed} failed run{kpis.failed === 1 ? "" : "s"}</div>
        </div>
      </div>

      <div className="row-single">
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Free-Audit Leads</div>
              <div className="cs">
                Every email + URL submitted on the public landing page — one free audit per email
              </div>
            </div>
            <div className="tools">
              <input
                className="lead-search"
                placeholder="Search email or URL…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
          </div>

          <div className="lead-filters">
            <div className="seg">
              {(["all", "done", "running", "queued", "failed"] as const).map((s) => (
                <button
                  key={s}
                  className={statusFilter === s ? "on" : undefined}
                  onClick={() => setStatusFilter(s)}
                >
                  {s === "all" ? "All" : STATUS_META[s].label}
                </button>
              ))}
            </div>
            <button
              className="ghostbtn"
              onClick={() => leadsQ.refetch()}
              disabled={leadsQ.isFetching}
            >
              <span className="material-symbols-rounded">refresh</span>
              {leadsQ.isFetching ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          <div className="lead-tbl-wrap">
            <table className="lead-tbl">
              <thead>
                <tr>
                  <th>Lead</th>
                  <th>Target URL</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th className="num">Score</th>
                  <th>Captured</th>
                  <th>Report</th>
                </tr>
              </thead>
              <tbody>
                {leadsQ.isLoading && (
                  <tr>
                    <td colSpan={7} className="lead-empty">
                      Loading leads…
                    </td>
                  </tr>
                )}
                {leadsQ.isError && !leadsQ.isLoading && (
                  <tr>
                    <td colSpan={7} className="lead-empty">
                      Couldn&apos;t load leads — {(leadsQ.error as Error)?.message ?? "try again"}.
                    </td>
                  </tr>
                )}
                {!leadsQ.isLoading &&
                  !leadsQ.isError &&
                  shown.map((r) => {
                    const sm = STATUS_META[r.status];
                    return (
                      <tr key={r.id}>
                        <td>
                          <a className="lead-email" href={`mailto:${r.email}`}>
                            {r.email}
                          </a>
                          {r.status === "failed" && r.error && (
                            <div className="lead-err" title={r.error}>
                              {r.error}
                            </div>
                          )}
                        </td>
                        <td>
                          <a
                            className="lead-url"
                            href={/^https?:\/\//.test(r.url) ? r.url : `https://${r.url}`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <span className="material-symbols-rounded">link</span>
                            {r.url}
                          </a>
                        </td>
                        <td>
                          <span className="lead-src">{r.source}</span>
                        </td>
                        <td>
                          <span className={`status-pill ${sm.pill}`}>
                            <span
                              className={`material-symbols-rounded${r.status === "running" ? " lead-spin" : ""}`}
                            >
                              {sm.icon}
                            </span>
                            {sm.label}
                          </span>
                        </td>
                        <td className="num">
                          {r.score === null ? (
                            <span className="lead-dash">—</span>
                          ) : (
                            <span className={`lead-score ${scoreClass(r.score)}`}>{r.score}</span>
                          )}
                        </td>
                        <td className="lead-when">{fmtWhen(r.created_at)}</td>
                        <td>
                          <button
                            className="lead-dl"
                            title={r.has_pdf ? "Download the report PDF" : "No PDF yet"}
                            disabled={!r.has_pdf}
                            onClick={() =>
                              downloadFile(
                                `/public/audits/${encodeURIComponent(r.report_token)}/report.pdf`,
                                `free-audit-${r.url.replace(/[^a-z0-9]+/gi, "-")}.pdf`,
                              )
                            }
                          >
                            <span className="material-symbols-rounded">picture_as_pdf</span>
                            PDF
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                {!leadsQ.isLoading && !leadsQ.isError && shown.length === 0 && (
                  <tr>
                    <td colSpan={7} className="lead-empty">
                      {rows.length === 0
                        ? "No free audits yet — leads land here as visitors submit the landing-page form."
                        : "No leads match this filter."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
