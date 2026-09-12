"use client";

import { useMemo, useState } from "react";
import {
  PLATFORM_META,
  type Web2Mechanism,
  type Web2PipelineStatus,
  type Web2Platform,
  type Web2Verified,
} from "@/lib/offpage";
import {
  useApproveWeb2,
  useWeb2,
  useWeb2Catalog,
  useWeb2Placements,
} from "@/lib/hooks/offpage";
import { useClients } from "@/lib/hooks/clients";
import Web2AccountBoard from "./Web2AccountBoard";
import Web2PlacementTable from "./Web2PlacementTable";
import Web2ArticleWizard from "./Web2ArticleWizard";
import Web2StatusBoard from "./Web2StatusBoard";
import ReadMore from "@/components/ui/ReadMore";

type FilterKey = "all" | Web2Verified;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "verified", label: "Verified" },
  { key: "pending", label: "Pending" },
];

/** Sentinel for the Accounts view's client select. `""` means "not chosen yet" and
 *  HOUSE means "deliberately agency-owned" — two different things that used to share
 *  the empty string, which is how the UI's default became its riskiest option. */
const HOUSE = "__house__";

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
  const [view, setView] = useState<"ledger" | "links" | "accounts" | "status">("ledger");
  const web2Q = useWeb2();
  const web2Properties = web2Q.data ?? [];
  const approve = useApproveWeb2();
  const [showPlan, setShowPlan] = useState(false);
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

  // WHICH ROUTE APPROVAL WILL TAKE, named before the operator commits.
  //
  // `approve_web2` already branches on the 0135 capability lane: an API-lane platform
  // is enqueued for the publish worker, while an extension-lane one is parked at
  // `publish_method='extension'` and enqueues NOTHING — the parked row IS the
  // operator's placement task. Both outcomes arrived behind one button labelled
  // "Approve", so the operator could not tell whether pressing it published an
  // article or handed them work; a parked row then looked like a publish that had
  // stalled. The lane is a fact about the platform, so it is read from the catalogue
  // rather than guessed from the row (whose `publishMethod` is only set BY approval).
  const catalogQ = useWeb2Catalog();
  const laneOf = useMemo(() => {
    const map = new Map<string, Web2Mechanism>();
    for (const p of catalogQ.data?.platforms ?? []) map.set(p.name, p.mechanism);
    return map;
  }, [catalogQ.data]);

  const rows = useMemo(
    () => web2Properties.filter((w) => filter === "all" || w.verified === filter),
    [web2Properties, filter],
  );
  const needsReviewCount = web2Properties.filter((w) => w.status === "needs_review").length;
  // A flagged placement waiting on a DELIBERATE second decision. Held per-property, so
  // acknowledging one collision can never wave through another.
  const [pendingAck, setPendingAck] = useState<{ id: string; message: string } | null>(null);

  function act(
    id: string,
    action: "approve" | "reject",
    acknowledgeSimilarity = false,
    destination?: "connected" | "extension",
  ) {
    approve.mutate(
      { id, action, acknowledgeSimilarity, destination },
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
          {/* THE PRIMARY DOOR (2026-09-12). One article, start to finish, in four
              steps: client -> brief -> read it -> choose where it publishes. It is the
              primary button because it is what an operator does most, and because it is
              the only path where the approver has actually READ the article. */}
          <button
            className="primary-btn" onClick={() => setShowPlan(true)}
            title="Write one article: pick the client, brief the writer, read what it wrote, then publish by API or hand it to the extension."
          >
            <span className="material-symbols-rounded">edit_note</span>
            Write a new Web 2.0 article
          </button>
        </div>
      </div>

      <div className="w2-tabs">
        <div className="seg">
          <button className={view === "ledger" ? "on" : undefined} onClick={() => setView("ledger")}>Placements</button>
          <button className={view === "links" ? "on" : undefined} onClick={() => setView("links")}>Links built</button>
          <button className={view === "accounts" ? "on" : undefined} onClick={() => setView("accounts")}>Accounts</button>
            <button className={view === "status" ? "on" : undefined} onClick={() => setView("status")}>Integrations</button>
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
            {/* HOUSE IS THE EXCEPTION, NOT THE DEFAULT. This select used to open on
                "House (agency-shared)", and the register form derives ownership from
                exactly that — so the easiest path through the UI produced a house
                account for a platform that cannot use one. Worse, a house account is
                the shared-footprint shape R2-06 spent a migration removing: one login
                behind every client is one suspension away from taking them all down,
                and per-client copies let a platform enumerate the client base from a
                single ban. So the first option is a PROMPT: the operator states whose
                account this is before the form can derive anything. */}
            <select
              id="w2-accounts-client"
              value={accountsClientId}
              onChange={(e) => setAccountsClientId(e.target.value)}
              style={{ minWidth: 240 }}
            >
              <option value="">Choose whose account…</option>
              {clientList.map((c) => (
                <option key={c.id} value={c.id}>{c.cn}</option>
              ))}
              <option value={HOUSE}>House (agency-shared) — Telegra.ph only</option>
            </select>
            <span className="cs" style={{ flexBasis: "100%" }}>
              {accountsClientId === HOUSE
                ? "House accounts are shared across every client, so one suspension takes them all down. Only a platform where publishing implies no durable identity — Telegra.ph and the like — should use one."
                : accountsClientId
                  ? "New accounts here are owned by this client, which is what almost every platform requires."
                  : "Pick a client to see and register accounts they own. Almost every platform needs a per-client account; House is for the few where publishing carries no durable identity."}
            </span>
          </div>
          {accountsClientId === "" ? (
            <div className="op-empty">
              Choose a client above to see the accounts they own and register new ones.
              Accounts are per-client by default because that is what the platforms
              require — and because it keeps one client&apos;s suspension from becoming
              everyone&apos;s.
            </div>
          ) : (
            <Web2AccountBoard
              clientId={accountsClientId === HOUSE ? undefined : accountsClientId}
            />
          )}
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
      {showPlan && <Web2ArticleWizard onClose={() => setShowPlan(false)} />}
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
                  // An extension-lane row parked at `publishing` is waiting for an
                  // OPERATOR's placement session (0136), not for the publish worker —
                  // labelling it "Publishing" would promise a worker that never comes.
                  const pipeline =
                    w.status === "publishing" && w.publishMethod === "extension"
                      ? { label: "Operator placement", cls: "warn" }
                      : PIPELINE_META[w.status] ?? { label: w.status, cls: "mut" };
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
                          (() => {
                            // THE CONTENT IS WRITTEN. The only question left is where it
                            // goes, so BOTH routes are offered explicitly rather than one
                            // "Approve" that silently picked for you. The platform's own
                            // lane decides which is the default action — but either is
                            // reachable, and the server retargets the row if the lead
                            // chooses the route its current platform cannot serve.
                            const lane = laneOf.get(w.platform);
                            const native = lane === "extension" ? "extension" : "connected";
                            return (
                              <div className="op-toolset" style={{ gap: 6, flexWrap: "wrap" }}>
                                <button
                                  className={native === "connected" ? "op-act update" : "ghostbtn"}
                                  onClick={() => act(w.id, "approve", false, "connected")}
                                  disabled={approve.isPending}
                                  title="Publishes the approved article through a connected platform's API and returns the live URL. If this row's platform has no connected account, it is moved to one that does."
                                >
                                  <span className="material-symbols-rounded">publish</span>
                                  Publish to connected
                                </button>
                                <button
                                  className={native === "extension" ? "op-act update" : "ghostbtn"}
                                  onClick={() => act(w.id, "approve", false, "extension")}
                                  disabled={approve.isPending}
                                  title="Hands the approved article to an operator: it appears in the extension's Web 2.0 tab as copy-blocks, they publish it in their own logged-in session and paste the public URL back."
                                >
                                  <span className="material-symbols-rounded">extension</span>
                                  Forward to extension
                                </button>
                                <button className="ghostbtn" onClick={() => act(w.id, "reject")} disabled={approve.isPending}>
                                  <span className="material-symbols-rounded">close</span>Reject
                                </button>
                              </div>
                            );
                          })()
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
