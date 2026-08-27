"use client";

import { useState } from "react";
import { useAnalyzePage } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** On-Page Optimizer — queue one page of the client's own site for analysis.
 *  Reads the page (SSRF-validated server-side); no paid provider pull. */
export default function OnPageActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [keyword, setKeyword] = useState("");
  const analyze = useAnalyzePage();

  const canSubmit = !!clientId && pageUrl.trim().length > 0 && !analyze.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    analyze.mutate({
      client_id: clientId, page_url: pageUrl.trim(),
      target_keyword: keyword.trim() || undefined,
    });
  };

  return (
    <ActionCard
      title="Analyze a page"
      subtitle="Queue a page for on-page analysis — checks land in the table below when it finishes."
      icon="plagiarism"
      accent={accent}
    >
      <form onSubmit={submit}>
        <div className="fld-row">
          <ClientSelect value={clientId} onChange={setClientId} />
          <div className="fld">
            <label>Page URL</label>
            <input value={pageUrl} onChange={(e) => setPageUrl(e.target.value)} placeholder="https://client.com/services/repair" />
          </div>
          <div className="fld">
            <label>Target keyword (optional)</label>
            <input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="ac repair dallas" />
          </div>
        </div>
        <button type="button" className="primary-btn wide" style={{ marginTop: 12 }} onClick={submit} disabled={!canSubmit}>
          <span className="material-symbols-rounded">plagiarism</span>
          {analyze.isPending ? "Queuing…" : "Analyze page"}
        </button>
        <ToolActionResult
          error={analyze.error}
          success={analyze.data ? `Analysis ${analyze.data.code} queued.` : null}
        />
        <PermNote>The URL must belong to the client&apos;s site; the server validates it before fetching.</PermNote>
      </form>
    </ActionCard>
  );
}
