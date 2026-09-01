"use client";

import { useMemo, useState } from "react";
import {
  useCampaignRollup,
  useCitationCampaigns,
} from "@/lib/hooks/offpage";
import {
  ROLLUP_GROUPS,
  blockedReasonLabel,
  citationStatusMeta,
  type RollupGroup,
} from "@/lib/citationStatus";
import w from "./Wave4.module.css";

// The Track step: what actually happened to the campaign the operator just approved.
//
// This board exists because on 2026-09-01 a campaign's 45 rows were refused within a
// second and the operator had NOWHERE to see it — the batch had no id, no rollup, and
// the only table in sight was a 50-row global list. The rollup is computed live from
// the citation rows (GET /citation-builder/campaigns/{id}) and polls at the
// CitationAuditProgress cadence while anything is still moving.

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function CampaignBoard({ clientId }: { clientId?: string }) {
  const campaignsQ = useCitationCampaigns(clientId);
  const campaigns = campaignsQ.data ?? [];
  // Newest first from the API; the operator can flip to an older one.
  const [picked, setPicked] = useState<string>("");
  const campaignId = picked || campaigns[0]?.id;
  const rollupQ = useCampaignRollup(campaignId);
  const roll = rollupQ.data;

  const groups = useMemo(() => {
    const counts = new Map<RollupGroup, number>();
    for (const [status, n] of Object.entries(roll?.byStatus ?? {})) {
      const g = citationStatusMeta(status).group;
      counts.set(g, (counts.get(g) ?? 0) + n);
    }
    return counts;
  }, [roll?.byStatus]);

  if (!clientId) return null;
  if (!campaignsQ.isLoading && campaigns.length === 0) return null;

  const moving = (roll?.byStatus["queued"] ?? 0) + (roll?.byStatus["submitting"] ?? 0);
  const teamCount = roll?.byStatus["ready_for_human"] ?? 0;

  return (
    <div className={w.step}>
      <div className={w.stepH} style={{ flexWrap: "wrap" }}>
        <span className="material-symbols-rounded">monitoring</span>
        Track — the latest build
        {campaigns.length > 1 && (
          <select
            className="op-input"
            style={{ marginLeft: "auto", maxWidth: 260 }}
            value={campaignId ?? ""}
            onChange={(e) => setPicked(e.target.value)}
          >
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {when(c.createdAt)} · {c.queued} queued
              </option>
            ))}
          </select>
        )}
      </div>

      {rollupQ.isError && (
        <div className="op-note crit">
          Couldn&apos;t load the campaign board — {(rollupQ.error as Error)?.message ?? "retry shortly"}.
        </div>
      )}
      {!roll && rollupQ.isLoading && <div className="op-muted">Loading the board…</div>}

      {roll && (
        <>
          <div className="op-muted" style={{ marginBottom: 8 }}>
            Queued {when(roll.createdAt)} · {roll.queued} of {roll.requested} selected
            directories queued
            {roll.estimatedCost > 0
              ? ` · estimated fees $${roll.estimatedCost.toFixed(2)}`
              : " · no fees estimated"}
            . <b>Live means fetched and matched — nothing here is asserted.</b>
          </div>

          <div className={w.stats}>
            {ROLLUP_GROUPS.map((g) => (
              <div className={w.stat} key={g}>
                <div className={w.statNum}>{groups.get(g) ?? 0}</div>
                <div className={w.statLbl}>{g}</div>
              </div>
            ))}
          </div>

          {roll.stuck > 0 && (
            <div className="op-note crit" style={{ marginTop: 8 }}>
              {roll.stuck} row{roll.stuck === 1 ? " has" : "s have"} sat unmoved past the
              staleness threshold — usually no worker is consuming the queue. Run
              scripts/dev-doctor.sh (or check Operations) before reading anything else
              on this board as truth.
            </div>
          )}

          {moving > 0 && (
            <div className="op-muted" style={{ marginTop: 6 }}>
              {moving} still being classified — this board refreshes itself every few
              seconds until they settle.
            </div>
          )}

          {teamCount > 0 && (
            <div className="op-toolset" style={{ marginTop: 10 }}>
              <a
                className="primary-btn"
                href={`/admin/citations/queue?client=${encodeURIComponent(clientId)}`}
                style={{ textDecoration: "none" }}
              >
                <span className="material-symbols-rounded">play_arrow</span>
                Work the queue ({teamCount} waiting for this client)
              </a>
            </div>
          )}

          {Object.keys(roll.byBlockedReason).length > 0 && (
            <div style={{ marginTop: 10 }}>
              {Object.entries(roll.byBlockedReason)
                .sort((a, b) => b[1] - a[1])
                .map(([code, n]) => (
                  <div key={code} className="op-muted" style={{ marginTop: 4, fontSize: 12.5 }}>
                    <b>{n}×</b> {blockedReasonLabel(code)}
                  </div>
                ))}
            </div>
          )}

          {roll.liveUrls.length > 0 && (
            <>
              <div className="op-muted" style={{ marginTop: 10 }}>
                Live listings from this build — each URL was fetched and found to carry
                the business:
              </div>
              {roll.liveUrls.map((u, i) => (
                <div key={i} className={w.urlRow}>
                  <span className="status-pill ok">{citationStatusMeta(u.status).label}</span>
                  <a className="op-url" href={u.url} target="_blank" rel="noreferrer">
                    {u.directory} <span className="material-symbols-rounded">open_in_new</span>
                  </a>
                </div>
              ))}
            </>
          )}

          <details style={{ marginTop: 10 }}>
            <summary className="op-muted" style={{ cursor: "pointer" }}>
              Every directory in this build ({roll.rows.length})
            </summary>
            <div className="tbl-wrap" style={{ marginTop: 8 }}>
              <table className="tbl op-tbl">
                <thead>
                  <tr>
                    <th>Directory</th>
                    <th>Status</th>
                    <th>Why / detail</th>
                    <th>Live URL</th>
                  </tr>
                </thead>
                <tbody>
                  {roll.rows.map((r) => {
                    const meta = citationStatusMeta(r.submitStatus);
                    return (
                      <tr key={r.id}>
                        <td className="op-strong">{r.directory}</td>
                        <td>
                          <span className={`status-pill ${meta.tone}`}>{meta.label}</span>
                        </td>
                        <td className="op-muted" style={{ whiteSpace: "normal", maxWidth: 420 }}>
                          {r.blockedReason
                            ? blockedReasonLabel(r.blockedReason)
                            : r.detail || meta.meaning}
                        </td>
                        <td>
                          {r.liveUrl ? (
                            <a className="op-url" href={r.liveUrl} target="_blank" rel="noreferrer">
                              open <span className="material-symbols-rounded">open_in_new</span>
                            </a>
                          ) : (
                            <span className="op-muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>

          {roll.skipped.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="op-muted" style={{ cursor: "pointer" }}>
                Not attempted in this build: {roll.skipped.length} — and why
              </summary>
              <div style={{ marginTop: 6 }}>
                {roll.skipped.slice(0, 40).map((sk, i) => (
                  <div key={i} className="op-muted" style={{ fontSize: 12.5, marginTop: 2 }}>
                    <b>{sk.directory}</b> — {sk.detail || sk.reason}
                  </div>
                ))}
                {roll.skipped.length > 40 && (
                  <div className="op-muted" style={{ marginTop: 4 }}>
                    +{roll.skipped.length - 40} more in the campaign record.
                  </div>
                )}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}
