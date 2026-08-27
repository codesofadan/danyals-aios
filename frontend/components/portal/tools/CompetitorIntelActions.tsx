"use client";

import { useState } from "react";
import { useAddCompetitor, useAnalyzeCompetitor } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Competitor Intel — two real actions: put a rival domain under tracking (a free
 *  ledger row), then fire a paid gap analysis against a tracked competitor's code.
 *  Adding hands you the code and arms the analyze card with it. */
export default function CompetitorIntelActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [domain, setDomain] = useState("");
  const [label, setLabel] = useState("");
  const [code, setCode] = useState("");
  const add = useAddCompetitor();
  const analyze = useAnalyzeCompetitor();

  const submitAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId || !domain.trim() || add.isPending) return;
    add.mutate(
      { client_id: clientId, domain: domain.trim(), label: label.trim() || undefined },
      { onSuccess: (c) => setCode(c.code) },
    );
  };

  return (
    <>
      <ActionCard
        title="Track a competitor"
        subtitle="Add a rival domain to a client's watchlist — its code then drives analyses."
        icon="visibility"
        accent={accent}
      >
        <form onSubmit={submitAdd}>
          <div className="fld-row">
            <ClientSelect value={clientId} onChange={setClientId} />
            <div className="fld">
              <label>Competitor domain</label>
              <input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="rivalplumbing.com" />
            </div>
            <div className="fld">
              <label>Label (optional)</label>
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Main local rival" />
            </div>
          </div>
          <button type="button" className="primary-btn wide" style={{ marginTop: 12 }} onClick={submitAdd} disabled={!clientId || !domain.trim() || add.isPending}>
            <span className="material-symbols-rounded">add</span>
            {add.isPending ? "Adding…" : "Track competitor"}
          </button>
          <ToolActionResult
            error={add.error}
            success={add.data ? `${add.data.domain} tracked as ${add.data.code} — armed below for analysis.` : null}
          />
        </form>
      </ActionCard>

      <ActionCard
        title="Run a gap analysis"
        subtitle="Queue a paid content/keyword gap run against a tracked competitor."
        icon="compare_arrows"
        accent={accent}
        paidAction
      >
        <div className="fld">
          <label>Competitor code</label>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="From the table below, e.g. CMP-0004" />
        </div>
        <button
          type="button" className="primary-btn wide" style={{ marginTop: 12 }}
          onClick={() => code.trim() && analyze.mutate(code.trim())}
          disabled={!code.trim() || analyze.isPending}
        >
          <span className="material-symbols-rounded">play_arrow</span>
          {analyze.isPending ? "Queuing…" : "Analyze"}
        </button>
        <ToolActionResult
          error={analyze.error}
          success={analyze.data ? `Analysis queued for ${analyze.data.code} — results land in the readout when it finishes.` : null}
        />
        <PermNote>The backlink-gap portion is honestly empty until a competitor backlink ingest is funded; keyword/content gaps are real.</PermNote>
      </ActionCard>
    </>
  );
}
