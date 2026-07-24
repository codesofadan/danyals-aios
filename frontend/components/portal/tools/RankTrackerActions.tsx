"use client";

import { useState } from "react";
import {
  useAddRankKeywords,
  type RankCadence,
  type RankDevice,
  type RankEngine,
} from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Rank Tracker — subscribe keyword(s) to nightly rank tracking for a client
 *  (POST /rank-tracker/keywords). The response carries the standing monthly bill
 *  the add signs the client up to; a budget breach comes back as a 402. */
export default function RankTrackerActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [keywords, setKeywords] = useState("");
  const [cadence, setCadence] = useState<RankCadence>("weekly");
  const [engine, setEngine] = useState<RankEngine>("google");
  const [device, setDevice] = useState<RankDevice>("desktop");
  const add = useAddRankKeywords();

  const parsed = keywords
    .split(/[\n,]/)
    .map((k) => k.trim())
    .filter(Boolean);
  const canRun = !!clientId && parsed.length > 0 && !add.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canRun) return;
    add.mutate(
      { client_id: clientId, keywords: parsed, cadence, engine, device },
      { onSuccess: () => setKeywords("") },
    );
  };

  return (
    <ActionCard
      title="Track keywords"
      subtitle="Subscribe keywords to nightly rank checks for a client."
      icon="add"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <ClientSelect value={clientId} onChange={setClientId} />
        <div className="fld">
          <label>Keywords (one per line, or comma-separated)</label>
          <textarea
            rows={3}
            placeholder={"dental implants karachi\nbest dentist near me"}
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
          />
        </div>
        <div className="fld-row">
          <div className="fld">
            <label>Cadence</label>
            <select value={cadence} onChange={(e) => setCadence(e.target.value as RankCadence)}>
              <option value="weekly">Weekly</option>
              <option value="daily">Daily (7× cost)</option>
            </select>
          </div>
          <div className="fld">
            <label>Engine</label>
            <select value={engine} onChange={(e) => setEngine(e.target.value as RankEngine)}>
              <option value="google">Google</option>
              <option value="bing">Bing</option>
            </select>
          </div>
          <div className="fld">
            <label>Device</label>
            <select value={device} onChange={(e) => setDevice(e.target.value as RankDevice)}>
              <option value="desktop">Desktop</option>
              <option value="mobile">Mobile</option>
              <option value="tablet">Tablet</option>
            </select>
          </div>
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canRun}>
          <span className="material-symbols-rounded">add</span>
          {add.isPending
            ? "Adding…"
            : parsed.length > 0
              ? `Track ${parsed.length} keyword${parsed.length === 1 ? "" : "s"}`
              : "Track keywords"}
        </button>
      </form>
      <ToolActionResult
        error={add.error}
        success={
          add.isSuccess
            ? `Now tracking ${add.data.keywords.length} keyword(s). ${add.data.projection.message}`
            : null
        }
      />
      <PermNote>
        Tracking is a standing per-client cost — adding needs owner / admin / manager access.
      </PermNote>
    </ActionCard>
  );
}
