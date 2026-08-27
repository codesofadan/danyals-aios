"use client";

import { useState } from "react";
import { useAddRankKeywords, type RankCadence, type RankDevice, type RankEngine } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Rank Tracker — subscribe keywords to scheduled position checks. This opens a
 *  STANDING bill (every check is a metered SERP pull), so the backend refuses
 *  with a 402 when the projection would breach the client's budget — that
 *  refusal renders here verbatim rather than being retried or softened. */
export default function RankTrackerActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [keywords, setKeywords] = useState("");
  const [cadence, setCadence] = useState<RankCadence>("weekly");
  const [engine, setEngine] = useState<RankEngine>("google");
  const [device, setDevice] = useState<RankDevice>("desktop");
  const [targetUrl, setTargetUrl] = useState("");
  const add = useAddRankKeywords();

  const list = keywords.split("\n").map((k) => k.trim()).filter(Boolean);
  const canSubmit = !!clientId && list.length > 0 && !add.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    add.mutate({
      client_id: clientId, keywords: list, cadence, engine, device,
      target_url: targetUrl.trim() || undefined,
    });
  };

  return (
    <ActionCard
      title="Track keywords"
      subtitle="Subscribe keywords to scheduled rank checks for a client — a standing metered cost."
      icon="query_stats"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <div className="fld-row">
          <ClientSelect value={clientId} onChange={setClientId} />
          <div className="fld">
            <label>Cadence</label>
            <select value={cadence} onChange={(e) => setCadence(e.target.value as RankCadence)}>
              <option value="weekly">Weekly</option>
              <option value="daily">Daily</option>
            </select>
          </div>
        </div>
        <div className="fld" style={{ marginTop: 10 }}>
          <label>Keywords — one per line</label>
          <textarea
            rows={4}
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder={"emergency plumber austin\nwater heater repair austin"}
          />
        </div>
        <div className="fld-row" style={{ marginTop: 10 }}>
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
          <div className="fld">
            <label>Target URL (optional)</label>
            <input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://client.com/service" />
          </div>
        </div>
        <button type="button" className="primary-btn wide" style={{ marginTop: 12 }} onClick={submit} disabled={!canSubmit}>
          <span className="material-symbols-rounded">add</span>
          {add.isPending ? "Subscribing…" : `Track ${list.length || ""} keyword${list.length === 1 ? "" : "s"}`}
        </button>
        <ToolActionResult
          error={add.error}
          success={add.data ? `${add.data.keywords.length} keyword(s) subscribed. ${add.data.projection.message}` : null}
        />
        <PermNote>Needs a lead role. If the standing cost would breach the client&apos;s budget the backend refuses with the exact projection.</PermNote>
      </form>
    </ActionCard>
  );
}
