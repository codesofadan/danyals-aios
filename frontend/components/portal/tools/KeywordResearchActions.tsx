"use client";

import { useState } from "react";
import { useRunKeywordResearch } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Keyword Research — run a cost-gated research pass for a seed keyword
 *  (POST /keyword-research/research). Results trickle into the bank below. */
export default function KeywordResearchActions({ accent }: ToolActionProps) {
  const [seed, setSeed] = useState("");
  const [clientId, setClientId] = useState("");
  const [geo, setGeo] = useState("");
  const run = useRunKeywordResearch();

  const canRun = seed.trim().length > 1 && !run.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canRun) return;
    run.mutate({
      seed: seed.trim(),
      client_id: clientId || undefined,
      geo: geo.trim() || undefined,
    });
  };

  return (
    <ActionCard
      title="Research keywords"
      subtitle="Fetch, classify & cluster a seed into the keyword bank."
      icon="search"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <div className="fld">
          <label>Seed keyword</label>
          <input
            placeholder="dental implants"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
          />
        </div>
        <div className="fld-row">
          <ClientSelect value={clientId} onChange={setClientId} label="Client (optional)" allowNone />
          <div className="fld">
            <label>Geo (optional)</label>
            <input placeholder="Karachi, PK" value={geo} onChange={(e) => setGeo(e.target.value)} />
          </div>
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canRun}>
          <span className="material-symbols-rounded">search</span>
          {run.isPending ? "Queuing…" : "Research keywords"}
        </button>
      </form>
      <ToolActionResult
        error={run.error}
        success={
          run.isSuccess
            ? `Research queued for "${run.data.seed}". New keywords will appear in the bank as the run completes.`
            : null
        }
      />
      <PermNote>Running research needs owner / admin / manager access and spends metered budget.</PermNote>
    </ActionCard>
  );
}
