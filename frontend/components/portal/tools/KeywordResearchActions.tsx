"use client";

import { useState } from "react";
import { downloadFile } from "@/lib/api";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Keyword Research — export the keyword bank as a CSV (the OUT half of the CSV
 *  import). Fetches the bearer-authed `GET /keyword-research/keywords/export.csv`
 *  and hands the browser the blob, the same idiom as the audit CSV pack downloads.
 *  Optionally narrowed to one client; the backend caps the file at 5,000 rows. */
export default function KeywordResearchActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  const exportCsv = async () => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const qs = clientId ? `?clientId=${encodeURIComponent(clientId)}` : "";
      await downloadFile(`/keyword-research/keywords/export.csv${qs}`, "keywords.csv");
      setDone(true);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ActionCard
      title="Export keywords"
      subtitle="Download the keyword bank as a CSV — keyword, volume, difficulty, intent, winnability, CPC."
      icon="download"
      accent={accent}
    >
      <div className="fld-row">
        <ClientSelect value={clientId} onChange={setClientId} label="Client (optional)" allowNone />
      </div>
      <button type="button" className="primary-btn wide" onClick={() => void exportCsv()} disabled={busy}>
        <span className="material-symbols-rounded">download</span>
        {busy ? "Exporting…" : "Export CSV"}
      </button>
      <ToolActionResult
        error={error}
        success={done ? "CSV downloaded — up to 5,000 keywords, best opportunities first." : null}
      />
      <PermNote>Anyone granted the Keyword Research tool can export; leave the client blank for the whole bank.</PermNote>
    </ActionCard>
  );
}
