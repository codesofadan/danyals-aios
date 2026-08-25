"use client";

// ============================================================
// The page pivot - every crawled URL with its own issue counts.
//
// This is the view that answers "which pages are worst", which the cause-level
// list deliberately cannot: a cause spans pages, so the per-page picture has to
// be reconstructed from the other side. Worst first.
//
// "Health" is CRITICAL-only. Including major issues returned 0% of pages healthy
// on a real 197-page site - every page carried something - so the column could
// not discriminate. A page missing an alt attribute is not an unhealthy page.
// ============================================================

import type { AuditPage } from "@/lib/auditAltitude";

export default function AuditPagesTable({ pages }: { pages: AuditPage[] }) {
  if (!pages.length) {
    return (
      <div className="alt-empty">
        <span className="material-symbols-rounded">description</span>
        <p>No crawled pages recorded for this audit.</p>
      </div>
    );
  }
  return (
    <div className="alt-tbl-wrap">
      <table className="alt-tbl">
        <thead>
          <tr>
            <th>URL</th>
            <th>Template</th>
            <th className="num">HTTP</th>
            <th className="num">Words</th>
            <th className="num">Issues</th>
            <th className="num">Critical</th>
            <th className="num">Major</th>
            <th>Health</th>
          </tr>
        </thead>
        <tbody>
          {pages.map((p) => (
            <tr key={p.url} className={p.health_pass ? "" : "bad"}>
              <td className="alt-url">
                <a href={p.url} target="_blank" rel="noreferrer noopener">
                  {p.url}
                </a>
              </td>
              <td className="alt-mono">{p.template_id || "-"}</td>
              <td className="num">{p.http_status ?? "-"}</td>
              <td className="num">{p.word_count?.toLocaleString() ?? "-"}</td>
              <td className="num">{p.issues_total.toLocaleString()}</td>
              <td className="num t-crit">{p.issues_critical || ""}</td>
              <td className="num t-warn">{p.issues_major || ""}</td>
              <td>
                <span className={`alt-health ${p.health_pass ? "ok" : "bad"}`}>
                  {p.health_pass ? "clear" : "critical"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
