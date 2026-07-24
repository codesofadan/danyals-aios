"use client";

import { useState } from "react";
import { useAnalyzePage } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** On-Page Optimizer — queue a page for analysis (POST /on-page/analyze). The URL
 *  is SSRF-validated server-side; recommendations land on the board below. */
export default function OnPageActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [keyword, setKeyword] = useState("");
  const analyze = useAnalyzePage();

  const canRun = !!clientId && pageUrl.trim().length > 3 && !analyze.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canRun) return;
    analyze.mutate({
      client_id: clientId,
      page_url: pageUrl.trim(),
      target_keyword: keyword.trim() || undefined,
    });
  };

  return (
    <ActionCard
      title="Analyze a page"
      subtitle="Score one page and generate on-page fix recommendations."
      icon="tune"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <ClientSelect value={clientId} onChange={setClientId} />
        <div className="fld">
          <label>Page URL</label>
          <input
            placeholder="https://northpeakdental.com/services/implants"
            value={pageUrl}
            onChange={(e) => setPageUrl(e.target.value)}
          />
        </div>
        <div className="fld">
          <label>Target keyword (optional)</label>
          <input
            placeholder="dental implants"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canRun}>
          <span className="material-symbols-rounded">tune</span>
          {analyze.isPending ? "Queuing…" : "Analyze page"}
        </button>
      </form>
      <ToolActionResult
        error={analyze.error}
        success={
          analyze.isSuccess
            ? `Analysis ${analyze.data.code} queued — recommendations will appear once it finishes.`
            : null
        }
      />
      <PermNote>Analysis only reads the page; it needs the run-audits permission.</PermNote>
    </ActionCard>
  );
}
