"use client";

import { useMemo, useState } from "react";
import { PLATFORM_META, type Web2PipelineStatus, type Web2Platform, type Web2Verified } from "@/lib/offpage";
import { useApproveWeb2, useWeb2, useWeb2Placements } from "@/lib/hooks/offpage";
import { useClients } from "@/lib/hooks/clients";
import Web2CampaignBoard from "./Web2CampaignBoard";
import Web2AccountBoard from "./Web2AccountBoard";
import Web2PlacementTable from "./Web2PlacementTable";
import Web2CampaignWizard from "./Web2CampaignWizard";
import Web2PlanModal from "./Web2PlanModal";
import Web2StatusBoard from "./Web2StatusBoard";
import ReadMore from "@/components/ui/ReadMore";

type FilterKey = "all" | Web2Verified;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "verified", label: "Verified" },
  { key: "pending", label: "Pending" },
];

const PIPELINE_META: Record<Web2PipelineStatus, { label: string; cls: string }> = {
  draft: { label: "Drafting", cls: "mut" },
  needs_review: { label: "Needs review", cls: "warn" },
  publishing: { label: "Publishing", cls: "info" },
  published: { label: "Published", cls: "ok" },
  failed: { label: "Failed", cls: "op-crit" },
  rejected: { label: "Rejected", cls: "mut" },
};

export default function Web2Tab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const [view, setView] = useState<"ledger" | "campaigns" | "links" | "accounts" | "status">("ledger");
  const web2Q = useWeb2();
  const web2Properties = web2Q.data ?? [];
  const approve = useApproveWeb2();
  const [showPlan, setShowPlan] = useState(false);
  const [showCampaign, setShowCampaign] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  // WHOSE accounts the Accounts view is showing and registering.
  //
  // This board used to be mounted with no clientId at all, and the register form
  // derives ownership from exactly that: `ownership: clientId ? "per_client" :
  // "house"`. So every account registered through the UI was a HOUSE account - and
  // a house account only satisfies a house-tier platform, of which there is exactly
  // one (Telegra.ph). WordPress.com, Blogger, Tumblr and the eleven developer
  // platforms are all per_client tier, so they could never reach "eligible" no
  // matter how many accounts were added here; a per_client account could only be
  // created from the CLI. That is why both Create Property buttons were disabled:
  // eligibility requires a connected account, and the UI could not produce one.
  const clientsQ = useClients();
  const clientList = clientsQ.data ?? [];
  const [accountsClientId, setAccountsClientId] = useState("");

  const rows = useMemo(
    () => web2Properties.filter((w) => filter === "all" || w.verified === filter),
    [web2Properties, filter],
  );
  const needsReviewCount = web2Properties.filter((w) => w.status === "needs_review").length;
  // A flagged placement waiting on a DELIBERATE second decision. Held per-property, so
  // acknowledging one collision can never wave through another.
  const [pendingAck, setPendingAck] = useState<{ id: string; message: string } | null>(null);

  function act(id: string, action: "approve" | "reject", acknowledgeSimilarity = false) {
    approve.mutate(
      { id, action, acknowledgeSimilarity },
      {
        onSuccess: () => {
          setPendingAck(null);
          setFlash(action === "approve" ? "Approved — publishing now." : "Rejected.");
          window.setTimeout(() => setFlash(null), 3200);
        },
        onError: (err) => {
          const message = (err as Error)?.message ?? "try again";
          // THE ONLY 409 THE OPERATOR CAN CLEAR THEMSELVES. The approve route raises
          // three different conflicts and only this one is acknowledgeable: a gate that
          // could not RUN, and a hard block while enforcement is on, both require a
          // re-draft and must never be offered an override. The server names the
          // acknowledgement in exactly the case where it is allowed, so that is what is
          // matched — not the status code, which is 409 for all three.
          if (action === "approve" && message.includes("acknowledgeSimilarity")) {
            setPendingAck({ id, message });
            return;
          }
          setFlash(`${action === "approve" ? "Approve" : "Reject"} failed — ${message}.`);
          window.setTimeout(() => setFlash(null), 3200);
        },
      },
    );
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">rocket_launch</span>
          Branded articles published via official platform APIs — links re-checked by the link
          monitor after publish.
        </div>
        {/* ACTIONS only. The view tabs moved to their own row below: navigation and
            actions were sharing one flex line with two segmented controls and two
            buttons, which crowded on any laptop-width screen. */}
        <div className="op-toolset">
          <button className="ghost-btn" onClick={() => setShowPlan(true)}>
            <span className="material-symbols-rounded">add</span>
            Single property
          </button>
          <button className="primary-btn" onClick={() => setShowCampaign(true)}>
            <span className="material-symbols-rounded">campaign</span>
            New campaign
          </button>
        </div>
      </div>

      <div className="w2-tabs">
        <div className="seg">
          <button className={view === "ledger" ? "on" : undefined} onClick={() => setView("ledger")}>Placements</button>
          <button className={view === "campaigns" ? "on" : undefined} onClick={() => setView("campaigns")}>Campaigns</button>
          <button className={view === "links" ? "on" : undefined} onClick={() => setView("links")}>Links built</button>
          <button className={view === "accounts" ? "on" : undefined} onClick={() => setView("accounts")}>Accounts</button>
            <button className={view === "status" ? "on" : undefined} onClick={() => setView("status")}>API status</button>
        </div>
        {view === "ledger" && (
          <div className="seg w2-tabs-right">
            {FILTERS.map((f) => (
              <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {view === "campaigns" && <Web2CampaignBoard />}
      {view === "links" && <LinksBuilt />}
      {view === "accounts" && (
        <>
          <div
            style={{
              display: "flex", alignItems: "center", gap: 10,
              flexWrap: "wrap", margin: "14px 0 4px",
            }}
          >
            <label htmlFor="w2-accounts-client" style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)" }}>
              Accounts for
            </label>
            <select
              id="w2-accounts-client"
              value={accountsClientId}
              onChange={(e) => setAccountsClientId(e.target.value)}
              style={{ minWidth: 240 }}
            >
              <option value="">House (agency-shared)</option>
              {clientList.map((c) => (
                <option key={c.id} value={c.id}>{c.cn}</option>
              ))}
            </select>
            <span className="cs" style={{ flexBasis: "100%" }}>
              {accountsClientId
                ? "New accounts here are owned by this client, which is what most platforms require."
                : "House accounts are shared across clients. Only Telegra.ph accepts one — pick a client for every other platform."}
            </span>
          </div>
          <Web2AccountBoard clientId={accountsClientId || undefined} />
        </>
      )}
      {view === "status" && <Web2StatusBoard />}

      {view === "ledger" && needsReviewCount > 0 && (
        <div className="op-flash" style={{ position: "static" }}>
          <span className="material-symbols-rounded">hourglass_top</span>
          {needsReviewCount} propert{needsReviewCount > 1 ? "ies" : "y"} awaiting a lead&apos;s review below.
        </div>
      )}
      {pendingAck && (
        <div
          className="op-flash"
          style={{ position: "static", background: "#fef3c7", color: "#92400e", display: "block" }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            The similarity gate flagged this placement
          </div>
          <div style={{ marginBottom: 8 }}>{pendingAck.message}</div>
          <div style={{ marginBottom: 8, fontSize: "0.9em" }}>
            Open the colliding property and read it. Approving here records that{" "}
            <b>you</b> judged this article genuinely distinct — it does not silence the
            gate for anything else.
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="op-act" onClick={() => act(pendingAck.id, "approve", true)}>
              I have reviewed it — approve anyway
            </button>
            <button className="op-act" onClick={() => setPendingAck(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {showPlan && <Web2PlanModal onClose={() => setShowPlan(false)} />}
      {showCampaign && <Web2CampaignWizard onClose={() => setShowCampaign(false)} />}
      {flash && (
        <div className="op-flash">
          <span className="material-symbols-rounded">task_alt</span>{flash}
        </div>
      )}

      {view === "ledger" && (
      <div className="tbl-wrap">
        <table className="tbl op-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Platform</th>
              <th>Post URL</th>
              <th>Anchor</th>
              <th>Verified</th>
              <th>Stage</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {web2Q.isLoading && (
              <tr><td colSpan={7} className="op-empty">Loading placements…</td></tr>
            )}
            {web2Q.isError && !web2Q.isLoading && (
              <tr><td colSpan={7} className="op-empty">Couldn&apos;t load placements — {(web2Q.error as Error)?.message ?? "try again"}.</td></tr>
            )}
            {!web2Q.isLoading && !web2Q.isError && rows.length > 0 && (
              <ReadMore
                items={rows}
                initialCount={10}
                tableColSpan={7}
                getKey={(w) => w.id}
                renderItem={(w) => {
                  const pm = PLATFORM_META[w.platform as Web2Platform];
                  // Fallback for any status the backend emits that isn't in the map
                  // (e.g. blocked/unchanged/error/skipped) — never crash the page.
                  const pipeline = PIPELINE_META[w.status] ?? { label: w.status, cls: "mut" };
                  return (
                    <tr>
                      <td className="op-strong">{w.client}</td>
                      <td>
                        <span className="op-plat">
                          <span className="op-plat-ic" style={{ background: pm.c }}>
                            <span className="material-symbols-rounded">{pm.icon}</span>
                          </span>
                          {w.platform}
                        </span>
                      </td>
                      <td>
                        {w.postUrl ? (
                          <a
                            className="op-url"
                            href={w.postUrl.startsWith("http") ? w.postUrl : `https://${w.postUrl}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {w.postUrl}<span className="material-symbols-rounded">open_in_new</span>
                          </a>
                        ) : (
                          <span className="op-muted">— not yet published —</span>
                        )}
                      </td>
                      <td><span className="op-anchor">{w.anchor}</span></td>
                      <td>
                        {w.verified === "verified" ? (
                          <span className="status-pill ok">
                            <span className="material-symbols-rounded op-pill-ic">verified</span>Verified
                          </span>
                        ) : (
                          <span className="status-pill info">
                            <span className="material-symbols-rounded op-pill-ic">hourglass_top</span>Pending
                          </span>
                        )}
                      </td>
                      <td>
                        {w.status === "needs_review" ? (
                          <div className="op-toolset" style={{ gap: 6 }}>
                            <button className="op-act update" onClick={() => act(w.id, "approve")} disabled={approve.isPending}>
                              <span className="material-symbols-rounded">check</span>Approve
                            </button>
                            <button className="ghostbtn" onClick={() => act(w.id, "reject")} disabled={approve.isPending}>
                              <span className="material-symbols-rounded">close</span>Reject
                            </button>
                          </div>
                        ) : (
                          <span className={`status-pill ${pipeline.cls}`}>{pipeline.label}</span>
                        )}
                      </td>
                      <td className="op-muted">{w.published}</td>
                    </tr>
                  );
                }}
              />
            )}
            {!web2Q.isLoading && !web2Q.isError && rows.length === 0 && (
              <tr><td colSpan={7} className="op-empty">No placements match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}

/** Every link ever built, across every campaign and client.
 *
 *  Separate from the campaign board because a client's Web 2.0 history is not one
 *  campaign — it includes the single-property builds that predate campaigns, and those
 *  would be invisible in a campaign-scoped view. */
function LinksBuilt() {
  const q = useWeb2Placements();
  const rows = q.data ?? [];
  const live = rows.filter((r) => r.postUrl).length;
  const followed = rows.filter((r) => r.linkFound === true && !r.linkRel.includes("nofollow")).length;
  return (
    <>
      <div className="fld-hint" style={{ marginBottom: 8 }}>
        <b>{rows.length}</b> placement(s) · <b>{live}</b> with a live post ·{" "}
        <b>{followed}</b> with a confirmed followed link. &ldquo;Confirmed&rdquo; means the page was
        fetched and our link was found on it — not merely that the platform accepted the post.
      </div>
      <Web2PlacementTable placements={rows} loading={q.isLoading} />
    </>
  );
}
