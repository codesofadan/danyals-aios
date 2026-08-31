"use client";

import { useState } from "react";

import { useApproveWeb2Campaign, useCampaignPlacements, useWeb2Campaigns } from "@/lib/hooks/offpage";
import QueryGuard from "@/components/ui/QueryGuard";
import Web2PlacementTable from "./Web2PlacementTable";
import type { Web2CampaignHold, Web2CampaignStatus } from "@/lib/offpage";

/**
 * The campaign board: what was asked for, what has actually gone live, and what it cost.
 *
 * The one thing this screen must never do is round a partial delivery up to "done". A
 * campaign that asked for thirty properties and published twenty-eight is DEGRADED, and
 * the server labels it so - the same rule the content dispatcher enforces, and the same
 * defect P0-4 removed elsewhere in this codebase: a green tick over work that reached
 * nobody. So the progress line always shows published-of-total rather than a percentage
 * that reads like success, and `degraded` gets its own colour rather than sharing one
 * with `completed`.
 *
 * The same rule applies one level up, to the board itself. It handled `isLoading` and
 * an empty list but not a FAILED read, and `q.data ?? []` makes those two identical:
 * a dead `/offpage/web2/campaigns` printed "No Web 2.0 campaigns yet", telling an
 * operator their client's work had never been requested. QueryGuard now takes the
 * loading and failure branches; the empty copy still speaks for a real empty board.
 */
export default function Web2CampaignBoard({ clientId }: { clientId?: string }) {
  const q = useWeb2Campaigns(clientId);
  const approve = useApproveWeb2Campaign();
  const [held, setHeld] = useState<Web2CampaignHold[]>([]);
  const [note, setNote] = useState("");
  // Click a campaign to open its placement report - the "where are my links?" answer.
  const [openId, setOpenId] = useState<string | null>(null);
  const placements = useCampaignPlacements(openId);
  const campaigns = q.data ?? [];

  async function decide(campaignId: string, action: "approve" | "reject") {
    setNote("");
    setHeld([]);
    try {
      const result = await approve.mutateAsync({ campaignId, action });
      setHeld(result.held);
      setNote(
        action === "reject"
          ? `Rejected ${result.rejected} propert${result.rejected === 1 ? "y" : "ies"}.`
          : result.held.length
            // Never round a partial approval up to success: name what did not go.
            ? `Approved ${result.approved}; ${result.held.length} held for a duplicate-content collision.`
            : `Approved ${result.approved} propert${result.approved === 1 ? "y" : "ies"}.`,
      );
    } catch (e) {
      setNote((e as Error)?.message ?? "Could not apply that decision.");
    }
  }

  return (
    <QueryGuard queries={[q]} label="campaigns" minHeight={96}>
      {!campaigns.length ? (
        <div className="op-empty">
          No Web 2.0 campaigns yet. A campaign turns one request — &ldquo;thirty blog
          posts&rdquo; — into that many distinct articles, each on its own property.
        </div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl op-tbl">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Client</th>
                <th>Status</th>
                <th>Live</th>
                <th>Platforms</th>
                <th>Pace</th>
                <th>Next publish</th>
                <th>Spend</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id} className="w2-row" onClick={() => setOpenId(openId === c.id ? null : c.id)} style={{ cursor: "pointer" }}>
                  <td>{c.title || "Web 2.0 campaign"}</td>
                  <td>{c.client}</td>
                  <td><StatusPill status={c.status} /></td>
                  <td>
                    {/* published-of-total, never a bare percentage: "93%" reads as success
                        when two of a client's properties never went out. */}
                    <b>{c.published}</b> of {c.total}
                  </td>
                  <td>{c.platforms.length}</td>
                  {/* Historical only: new campaigns publish automatically, so this
                      just records how an older one was created. */}
                  <td className="op-muted">{c.pacing === "drip" ? "Drip (legacy)" : "Auto"}</td>
                  <td>{c.nextPublish ? new Date(c.nextPublish).toLocaleDateString() : "—"}</td>
                  <td>{money(c.spentUsd)}</td>
                  <td>
                    {c.status === "needs_approval" ? (
                      // stopPropagation: the row itself opens the report, so without this a
                      // click on Approve would also toggle the drawer under the operator.
                      <span className="op-auth" onClick={(e) => e.stopPropagation()}>
                        <button
                          className="op-act"
                          disabled={approve.isPending}
                          onClick={() => void decide(c.id, "approve")}
                        >
                          Approve all
                        </button>
                        <button
                          className="op-act"
                          disabled={approve.isPending}
                          onClick={() => void decide(c.id, "reject")}
                        >
                          Reject
                        </button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {openId && (
            <div style={{ marginTop: 14 }}>
              <div className="fld-hint" style={{ marginBottom: 6 }}>
                <b>Placement report</b> — every article in this campaign, where it lives, and whether
                the link is genuinely on the page. Click a campaign row again to close.
              </div>
              <Web2PlacementTable
                placements={placements.data ?? []}
                loading={placements.isLoading}
                emptyHint="This campaign has no placements yet — they appear as the writer drafts them."
              />
            </div>
          )}
          {note && <div className="fld-hint" style={{ marginTop: 8 }}>{note}</div>}
          {held.length > 0 && (
            <div className="fld-hint" style={{ marginTop: 8 }}>
              <b>Held — these were not approved:</b>
              <ul style={{ margin: "6px 0 0 18px" }}>
                {held.map((h) => (
                  <li key={h.web2Id}>
                    {h.topic || h.web2Id} on {h.platform} — {h.reason}
                  </li>
                ))}
              </ul>
              Redraft the held properties, then approve the campaign again; the rest are already away.
            </div>
          )}
          {campaigns.some((c) => c.status === "degraded") && (
            <div className="fld-hint" style={{ marginTop: 8 }}>
              A <b>degraded</b> campaign finished with properties that never published. Open it to
              see which ones and why — they are not counted as delivered.
            </div>
          )}
        </div>
      )}
    </QueryGuard>
  );
}

const LABELS: Record<Web2CampaignStatus, string> = {
  draft: "Draft",
  planning: "Drafting",
  needs_approval: "Awaiting approval",
  scheduled: "Scheduled",
  running: "Publishing",
  completed: "Completed",
  degraded: "Degraded",
  cancelled: "Cancelled",
};

// `degraded` deliberately does NOT share a tone with `completed` - the whole point of
// that status is that it is not success, so it takes the critical variant.
const TONES: Record<Web2CampaignStatus, string> = {
  draft: "mut",
  planning: "info",
  needs_approval: "warn",
  scheduled: "info",
  running: "info",
  completed: "ok",
  degraded: "crit",
  cancelled: "mut",
};

function StatusPill({ status }: { status: Web2CampaignStatus }) {
  return <span className={`status-pill ${TONES[status]}`}>{LABELS[status]}</span>;
}

function money(value: number): string {
  return value > 0 ? `$${value.toFixed(2)}` : "—";
}
