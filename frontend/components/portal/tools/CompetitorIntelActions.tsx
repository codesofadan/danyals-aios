"use client";

import { useState } from "react";
import { useAddCompetitor, useAnalyzeCompetitor } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Competitor Intel — track a competitor domain (POST /competitor-intel/competitors)
 *  then fire a gap analysis against it (POST .../{code}/analyze). The client's own
 *  positions come free from the Rank Tracker; only the rival's side is bought. */
export default function CompetitorIntelActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [domain, setDomain] = useState("");
  const [label, setLabel] = useState("");
  const add = useAddCompetitor();
  const analyze = useAnalyzeCompetitor();

  const canAdd = !!clientId && domain.trim().length > 2 && !add.isPending;
  const added = add.data ?? null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canAdd) return;
    add.mutate(
      { client_id: clientId, domain: domain.trim(), label: label.trim() || undefined },
      { onSuccess: () => setDomain("") },
    );
  };

  return (
    <ActionCard
      title="Track a competitor"
      subtitle="Add a rival domain, then run a keyword-gap analysis against it."
      icon="insights"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <ClientSelect value={clientId} onChange={setClientId} />
        <div className="fld-row">
          <div className="fld">
            <label>Competitor domain</label>
            <input
              placeholder="brightsmile.com"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            />
          </div>
          <div className="fld">
            <label>Label (optional)</label>
            <input
              placeholder="Bright Smile Dental"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canAdd}>
          <span className="material-symbols-rounded">add</span>
          {add.isPending ? "Adding…" : "Track competitor"}
        </button>
      </form>

      {added && (
        <div className="fld" style={{ marginTop: 14 }}>
          <label>Now analyze {added.domain}</label>
          <button
            type="button"
            className="primary-btn"
            onClick={() => analyze.mutate(added.code)}
            disabled={analyze.isPending}
          >
            <span className="material-symbols-rounded">query_stats</span>
            {analyze.isPending ? "Queuing…" : "Run gap analysis"}
          </button>
        </div>
      )}

      <ToolActionResult
        error={add.error ?? analyze.error}
        success={
          analyze.isSuccess
            ? "Gap analysis queued — the rival's keyword gaps will appear once it finishes."
            : add.isSuccess && added
              ? `Now tracking ${added.domain}. Run a gap analysis to compare it against the client.`
              : null
        }
      />
      <PermNote>Adding a competitor and running analysis need owner / admin / manager access.</PermNote>
    </ActionCard>
  );
}
