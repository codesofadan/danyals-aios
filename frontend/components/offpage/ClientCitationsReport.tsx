"use client";

import { useMemo, useState } from "react";
import { useCitationGap } from "@/lib/hooks/offpage";
import { SKIP_REASON_LABEL, type CitationSkipReason } from "@/lib/offpage";

// THE DELIVERABLE. A client asking "what did we get?" is answered here with the only
// currency this module deals in: fetch-verified public URLs they can open and track
// themselves — plus an honest account of what is still in motion and what was NOT
// built, by name and reason. This is the page that closes "we got the live URL so we
// can track it". Print-clean; CSV for the spreadsheet people.

export default function ClientCitationsReport({ clientId }: { clientId: string }) {
  const gapQ = useCitationGap(clientId);
  const gap = gapQ.data;
  const [copied, setCopied] = useState<"csv" | "summary" | null>(null);

  const inMotion = useMemo(() => {
    const by = gap?.bySubmitStatus ?? {};
    return {
      team: by["ready_for_human"] ?? 0,
      sent: (by["submitted"] ?? 0) + (by["queued"] ?? 0) + (by["submitting"] ?? 0),
      attention: (by["drifted"] ?? 0) + (by["delisted"] ?? 0) + (by["failed"] ?? 0) + (by["blocked"] ?? 0),
    };
  }, [gap?.bySubmitStatus]);

  const skipsByReason = useMemo(() => {
    const out = new Map<string, string[]>();
    for (const s of gap?.skipped ?? []) {
      const label = SKIP_REASON_LABEL[s.reason as CitationSkipReason] ?? s.reason;
      out.set(label, [...(out.get(label) ?? []), s.directory]);
    }
    return [...out.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [gap?.skipped]);

  async function copyCsv() {
    if (!gap) return;
    const lines = [
      "directory,url,status",
      ...gap.liveUrls.map((u) => `"${u.directory.replace(/"/g, '""')}","${u.url}","live — verified on the page"`),
      ...(gap.skipped ?? []).map(
        (s) => `"${s.directory.replace(/"/g, '""')}","","not built: ${(SKIP_REASON_LABEL[s.reason as CitationSkipReason] ?? s.reason).replace(/"/g, '""')}"`,
      ),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied("csv");
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  async function copySummary() {
    if (!gap) return;
    const text = [
      `Citation listings report — ${gap.client} (${new Date().toLocaleDateString()})`,
      "",
      `Live listings: ${gap.liveUrls.length}. Each URL below was fetched by our system and found to carry the business's name and its phone or address — you can open and track every one.`,
      ...gap.liveUrls.map((u) => `  • ${u.directory}: ${u.url}`),
      "",
      `In progress: ${inMotion.team} being finished by hand by our team · ${inMotion.sent} submitted and awaiting the directory's confirmation.`,
      "",
      `Not built (${gap.skipped.length} directories), and why:`,
      ...skipsByReason.map(([label, names]) => `  • ${names.length} × ${label}`),
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied("summary");
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  if (gapQ.isLoading) return <div className="op-muted">Building the report…</div>;
  if (gapQ.isError || !gap) {
    return (
      <div className="op-note crit">
        Couldn&apos;t build the report — {(gapQ.error as Error)?.message ?? "try again"}.
      </div>
    );
  }

  return (
    <div>
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <div className="ct">{gap.client} — citation listings</div>
            <div className="cs">
              {new Date().toLocaleDateString()} · every &quot;live&quot; URL below was fetched and
              found to carry this business&apos;s name and its phone or address. Nothing on
              this page is asserted.
            </div>
          </div>
          <div className="op-toolset">
            <button className="ghostbtn" onClick={copyCsv}>
              <span className="material-symbols-rounded">{copied === "csv" ? "check" : "table"}</span>
              {copied === "csv" ? "Copied" : "Copy as CSV"}
            </button>
            <button className="ghostbtn" onClick={copySummary}>
              <span className="material-symbols-rounded">{copied === "summary" ? "check" : "content_copy"}</span>
              {copied === "summary" ? "Copied" : "Copy summary"}
            </button>
          </div>
        </div>

        <h3 style={{ margin: "10px 0 6px" }}>Live listings — {gap.liveUrls.length}</h3>
        {gap.liveUrls.length === 0 ? (
          <div className="op-muted">
            None verified live yet. Listings appear here the moment their public URL is
            fetched and matched — never before.
          </div>
        ) : (
          <div className="tbl-wrap">
            <table className="tbl op-tbl">
              <thead>
                <tr><th>Directory</th><th>Public URL</th><th>Status</th></tr>
              </thead>
              <tbody>
                {gap.liveUrls.map((u, i) => (
                  <tr key={i}>
                    <td className="op-strong">{u.directory}</td>
                    <td>
                      <a className="op-url" href={u.url} target="_blank" rel="noreferrer" style={{ wordBreak: "break-all", whiteSpace: "normal" }}>
                        {u.url}
                      </a>
                    </td>
                    <td><span className="status-pill ok">live — verified on the page</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <h3 style={{ margin: "16px 0 6px" }}>In progress</h3>
        <div className="op-muted" style={{ whiteSpace: "normal" }}>
          {inMotion.team} being finished by hand by the team · {inMotion.sent} submitted
          and awaiting the directory&apos;s confirmation
          {inMotion.attention > 0 && (
            <> · {inMotion.attention} need attention (drifted, delisted, failed, or on hold)</>
          )}
          .
        </div>

        <h3 style={{ margin: "16px 0 6px" }}>
          Not built — {gap.skipped.length} directories, and why
        </h3>
        {skipsByReason.length === 0 ? (
          <div className="op-muted">Nothing was skipped for this client.</div>
        ) : (
          skipsByReason.map(([label, names]) => (
            <div key={label} className="op-muted" style={{ whiteSpace: "normal", marginTop: 4 }}>
              <b>{names.length}×</b> {label}: {names.slice(0, 10).join(", ")}
              {names.length > 10 ? ` +${names.length - 10} more` : ""}
            </div>
          ))
        )}
      </section>
    </div>
  );
}
