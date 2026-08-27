"use client";

import { useState } from "react";
import { downloadFile } from "@/lib/api";
import { useRunKeywordResearch } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** The IN half that was missing: fire a research run from a seed term. The paid
 *  provider pull happens in the worker behind the cost gate; the route answers
 *  202 immediately, so the honest promise here is "accepted", not "done" — and
 *  a spend-gate block holds silently server-side, which the note admits. */
function ResearchRunCard({ accent }: ToolActionProps) {
  const [seed, setSeed] = useState("");
  const [clientId, setClientId] = useState("");
  const [geo, setGeo] = useState("");
  const run = useRunKeywordResearch();

  const canSubmit = seed.trim().length > 0 && !run.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    run.mutate({ seed: seed.trim(), client_id: clientId || undefined, geo: geo.trim() || undefined });
  };

  return (
    <ActionCard
      title="Run keyword research"
      subtitle="Expand a seed term into the keyword bank — volume, difficulty, intent, winnability."
      icon="travel_explore"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <div className="fld-row">
          <div className="fld">
            <label>Seed term</label>
            <input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="emergency plumber" />
          </div>
          <ClientSelect value={clientId} onChange={setClientId} label="Client (optional)" allowNone />
          <div className="fld">
            <label>Geo (optional)</label>
            <input value={geo} onChange={(e) => setGeo(e.target.value)} placeholder="us" />
          </div>
        </div>
        <button type="button" className="primary-btn wide" style={{ marginTop: 12 }} onClick={submit} disabled={!canSubmit}>
          <span className="material-symbols-rounded">travel_explore</span>
          {run.isPending ? "Queuing…" : "Run research"}
        </button>
        <ToolActionResult
          error={run.error}
          success={run.data ? `Research on “${run.data.seed}” accepted — keywords trickle into the bank as the run completes.` : null}
        />
        <PermNote>Needs a lead role. If the spend gate blocks the run, it holds server-side without an error — check the bank if nothing lands.</PermNote>
      </form>
    </ActionCard>
  );
}

/** Keyword Research — export the keyword bank as a CSV (the OUT half of the CSV
 *  import). Fetches the bearer-authed `GET /keyword-research/keywords/export.csv`
 *  and hands the browser the blob, the same idiom as the audit CSV pack downloads.
 *  Optionally narrowed to one client; the backend caps the file at 5,000 rows. */
export default function KeywordResearchActions(props: ToolActionProps) {
  return (
    <>
      <ResearchRunCard {...props} />
      <ExportCard {...props} />
    </>
  );
}

function ExportCard({ accent }: ToolActionProps) {
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
