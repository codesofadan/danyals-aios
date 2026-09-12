"use client";

import { useEffect, useMemo, useState } from "react";

import { useClients } from "@/lib/hooks/clients";
import {
  useApproveWeb2,
  useCheckWeb2Anchor,
  usePlanWeb2,
  useSyndicateWeb2,
  useWeb2Draft,
} from "@/lib/hooks/offpage";

/**
 * Write one Web 2.0 article, start to finish, in three steps.
 *
 * THE FLOW, and why it is this order (owner instruction, 2026-09-12):
 *
 *   1. CLIENT   — everything downstream is scoped to it, including which platforms
 *                 exist, so nothing can be asked before it is known.
 *   2. BRIEF    — the questions the WRITER needs: topic, anchor, link target, page
 *                 type, proof points. No platform question: see step 3.
 *   3. READ IT, — the drafted article in full, then where it goes. A review gate where
 *      THEN       the reviewer never saw the prose is not a review gate; the old flow
 *      SEND       approved a table row carrying a platform name and a status pill.
 *
 * THE TWO DESTINATIONS ARE NOT ALTERNATIVES, which is why step 3 does not advance.
 * "Publish to direct API" and "Forward to extension" both stay available after either
 * is used: the same article can go out through a connected platform AND be handed to
 * an operator for a second one. That is two placements and two links from one piece of
 * prose. A four-step flow that closed on the first choice made the second unreachable.
 * The second send is a SYNDICATION (`/syndicate`), not a second approval - one row
 * holds one platform and one status, so it cannot be both published on Ghost and
 * awaiting an operator on Medium.
 *
 * WHY THE PLATFORM IS NOT ASKED IN STEP 2. It used to be, from a grid of ninety, and it
 * was the wrong question at the wrong time: the operator had to choose a home for an
 * article that did not exist yet. The server now picks the strongest platform open for
 * the client, and the real decision — who publishes it — is step 4, where there is
 * something to read and the choice is between two concrete outcomes.
 *
 * STEP 3 CAN END BADLY, AND SAYS SO. A write can fail (a provider 402, an outage) and a
 * draft can come back carrying `[NEEDS: ...]` gaps, which the writer emits when it had
 * no first-hand grounding. Both are rendered: a failed row shows its recorded reason,
 * and a gapped draft is still approvable but says plainly that it will publish a
 * placeholder. Neither is hidden behind a spinner that never resolves.
 */

type Step = "client" | "brief" | "review";

export default function Web2ArticleWizard({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const clients = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);

  const [step, setStep] = useState<Step>("client");
  const [clientId, setClientId] = useState("");
  const [topic, setTopic] = useState("");
  const [anchor, setAnchor] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [pageType, setPageType] = useState<"service" | "blog" | "local">("blog");
  const [proof, setProof] = useState("");
  const [web2Id, setWeb2Id] = useState<string | null>(null);
  /** WHERE THIS ARTICLE HAS BEEN SENT, per lane.
   *
   *  Not one `outcome`: the two destinations are not alternatives. An operator may
   *  want the same article published through a connected API AND handed to the
   *  extension for a second platform - two placements, two links, one piece of prose.
   *  Closing the flow after the first choice made the second one unreachable. */
  const [sent, setSent] = useState<{ connected?: string; extension?: string }>({});
  const [error, setError] = useState("");

  const plan = usePlanWeb2();
  const approve = useApproveWeb2();
  const syndicate = useSyndicateWeb2();
  const anchorCheck = useCheckWeb2Anchor();
  const [anchorVerdict, setAnchorVerdict] = useState<{ allowed: boolean; reason: string; suggestion: string } | null>(null);
  const draftQ = useWeb2Draft(step === "review" ? web2Id : null);
  const draft = draftQ.data;

  // Any edit invalidates a verdict about the old text.
  useEffect(() => { setAnchorVerdict(null); }, [anchor, targetUrl, topic, clientId]);

  const proofLines = proof.split("\n").map((l) => l.trim()).filter(Boolean);
  const anchorRefused = anchorVerdict !== null && !anchorVerdict.allowed;
  const canWrite =
    topic.trim().length > 2 && anchor.trim().length > 1 &&
    targetUrl.trim().startsWith("http") && !anchorRefused;

  const clientName = clients.find((c) => c.id === clientId)?.cn ?? "";

  function verifyAnchor() {
    if (!clientId || anchor.trim().length < 2) return;
    anchorCheck.mutate(
      { clientId, anchor: anchor.trim(), targetUrl: targetUrl.trim(), topic: topic.trim() },
      { onSuccess: (v) => setAnchorVerdict({ allowed: v.allowed, reason: v.reason, suggestion: v.suggestion }) },
    );
  }

  function write() {
    if (!canWrite || plan.isPending) return;
    setError("");
    plan.mutate(
      {
        clientId, anchor: anchor.trim(), targetUrl: targetUrl.trim(),
        pageType, topic: topic.trim(), proofPoints: proofLines.slice(0, 12),
      },
      {
        // The success panel is reachable only from a resolved promise carrying a real
        // property id - never from a settled-but-rejected request.
        onSuccess: (row) => { setWeb2Id(row.id); setStep("review"); },
        onError: (e) => setError((e as Error)?.message ?? "the write could not be queued"),
      },
    );
  }

  const anySent = !!(sent.connected || sent.extension);
  const busy = approve.isPending || syndicate.isPending;

  /** Send this article to one destination. The FIRST call approves the row; a later
   *  call for the other lane syndicates the same approved body as a SECOND placement,
   *  because one row cannot be both published on Ghost and awaiting an operator on
   *  Medium. The step never advances past `review`: both buttons must stay reachable. */
  function decide(destination: "connected" | "extension") {
    if (!web2Id || sent[destination]) return;
    setError("");
    const done = (platform: string) =>
      setSent((prev) => ({ ...prev, [destination]: platform }));
    const fail = (e: unknown) =>
      setError((e as Error)?.message ?? "that destination was refused");

    if (!anySent) {
      approve.mutate(
        { id: web2Id, action: "approve", destination },
        { onSuccess: (row) => done(row.platform), onError: fail },
      );
      return;
    }
    syndicate.mutate({ id: web2Id, destination }, { onSuccess: (row) => done(row.platform), onError: fail });
  }

  function reject() {
    if (!web2Id) return;
    approve.mutate(
      { id: web2Id, action: "reject" },
      { onSuccess: () => onClose(), onError: (e) => setError((e as Error)?.message ?? "reject failed") },
    );
  }

  const STEP_LABEL: Record<Step, string> = {
    client: "1 of 3 · Choose the client",
    brief: "2 of 3 · Brief the writer",
    review: "3 of 3 · Read it, then choose where it goes",
  };

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">Write a new Web 2.0 article</div>
            <div className="modal-s">{STEP_LABEL[step]}</div>
          </div>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        <div className="wiz-body">
          {error && <div className="note bad" style={{ marginBottom: 12 }}>{error}</div>}

          {/* ---------------------------------------------- 1 · the client */}
          {step === "client" && (
            <>
              <div className="fld">
                <label>Which client is this for?</label>
                <select
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  disabled={clientsQ.isError || clientsQ.isLoading}
                >
                  <option value="">
                    {clientsQ.isError
                      ? "Couldn't load clients — try again"
                      : clientsQ.isLoading
                        ? "Loading clients…"
                        : "Choose a client…"}
                  </option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.cn}</option>
                  ))}
                </select>
                <div className="fld-hint">
                  Everything after this is scoped to the client — their business facts
                  ground the article, and their connected accounts decide where it can
                  publish.
                </div>
              </div>
              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                <button
                  type="button" className="primary-btn"
                  disabled={!clientId} onClick={() => setStep("brief")}
                >
                  Continue
                </button>
              </div>
            </>
          )}

          {/* ---------------------------------------------- 2 · the brief */}
          {step === "brief" && (
            <>
              <div className="fld-hint" style={{ marginBottom: 12 }}>
                Writing for <b>{clientName}</b>. The platform is chosen for you — you
                decide where it goes out after you have read it.
              </div>

              <div className="fld">
                <label>Topic — what the article is about</label>
                <input
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="what a CCTV drain survey actually shows"
                />
                <div className="fld-hint">
                  Not the same thing as the anchor. With no topic the writer is handed the
                  LINK TEXT as its subject, and the article ends up about its own anchor.
                </div>
              </div>

              <div className="fld">
                <label>Anchor text — the words that carry the link</label>
                <input
                  value={anchor}
                  onChange={(e) => setAnchor(e.target.value)}
                  onBlur={verifyAnchor}
                  placeholder="gentle dental cleanings"
                />
                {anchorVerdict && !anchorVerdict.allowed && (
                  <div className="note bad" style={{ marginTop: 6 }}>
                    {anchorVerdict.reason}
                    {anchorVerdict.suggestion && (
                      <div style={{ marginTop: 4 }}>Try: <b>{anchorVerdict.suggestion}</b></div>
                    )}
                  </div>
                )}
                {anchorVerdict?.allowed && (
                  <div className="fld-hint" style={{ color: "var(--ok, #1d6a55)" }}>
                    Anchor accepted.
                  </div>
                )}
              </div>

              <div className="fld">
                <label>Link target — the page this should rank</label>
                <input
                  value={targetUrl}
                  onChange={(e) => setTargetUrl(e.target.value)}
                  placeholder="https://client.example/services/drain-surveys"
                />
              </div>

              <div className="fld">
                <label>Page type</label>
                <select value={pageType} onChange={(e) => setPageType(e.target.value as typeof pageType)}>
                  <option value="blog">Blog post</option>
                  <option value="service">Service page</option>
                  <option value="local">Local page</option>
                </select>
              </div>

              <div className="fld">
                <label>Proof points — one per line</label>
                <textarea
                  rows={4}
                  value={proof}
                  onChange={(e) => setProof(e.target.value)}
                  placeholder={"We ran 240 drain surveys in Leeds last year\nOur camera reaches 90m of pipe"}
                />
                <div className="fld-hint">
                  First-hand facts only. Without them the writer marks its gaps with
                  <b> [NEEDS: …]</b> and the draft publishes as a placeholder — so this
                  is the field that decides whether the article is any good.
                </div>
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={() => setStep("client")}>Back</button>
                <button
                  type="button" className="primary-btn"
                  disabled={!canWrite || plan.isPending} onClick={write}
                >
                  {plan.isPending ? "Starting…" : "Generate the article"}
                </button>
              </div>
            </>
          )}

          {/* ---------------------------------------------- 3 · read + approve */}
          {step === "review" && (
            <>
              {/* Still being written. A real state, so it is named rather than shown as
                  an empty page. */}
              {(!draft || draft.status === "draft") && !draftQ.isError && (
                <div className="op-empty">
                  <b>Writing the article…</b>
                  <div className="fld-hint" style={{ marginTop: 6 }}>
                    The writer researches, drafts and self-checks. This takes a few
                    seconds — the page updates itself when it is ready.
                  </div>
                </div>
              )}

              {draftQ.isError && (
                <div className="note bad">
                  Couldn&apos;t load the draft — {(draftQ.error as Error)?.message ?? "try again"}.
                </div>
              )}

              {/* The write FAILED. Its recorded reason is the useful thing - an
                  exhausted provider budget and a network outage send an operator to
                  completely different places. */}
              {draft && draft.status === "failed" && (
                <div className="note bad">
                  <b>The writer could not finish this article.</b>
                  <div style={{ marginTop: 6 }}>{draft.reason || "No reason was recorded."}</div>
                </div>
              )}

              {draft && draft.status === "needs_review" && (
                <>
                  <div className="fld-hint" style={{ marginBottom: 10 }}>
                    Written for <b>{clientName}</b> · platform <b>{draft.platform}</b>
                    {draft.lane === "extension"
                      ? " (extension lane — an operator publishes there by hand)"
                      : " (connected API)"}
                  </div>

                  {draft.needs.length > 0 && (
                    <div className="note" style={{ marginBottom: 10 }}>
                      <b>This draft has {draft.needs.length} unfilled gap(s).</b>
                      <ul style={{ margin: "6px 0 0 18px" }}>
                        {draft.needs.map((n, i) => <li key={i}>{n}</li>)}
                      </ul>
                      <div style={{ marginTop: 6 }}>
                        Publishing it now publishes those markers. Reject, add the missing
                        proof points, and write it again.
                      </div>
                    </div>
                  )}

                  {draft.blocks.map((b) => (
                    <div className="fld" key={b.key}>
                      <label>{b.label}</label>
                      {b.key === "body" ? (
                        <div
                          style={{
                            whiteSpace: "pre-wrap", maxHeight: 340, overflowY: "auto",
                            border: "1px solid var(--line, #d3dbe3)", borderRadius: 6,
                            padding: "10px 12px", fontSize: 14, lineHeight: 1.55,
                          }}
                        >
                          {b.value}
                        </div>
                      ) : (
                        <div style={{ fontWeight: 600, wordBreak: "break-word" }}>{b.value}</div>
                      )}
                    </div>
                  ))}

                  <div className="fld-hint" style={{ marginTop: 14, marginBottom: 6 }}>
                    <b>Where should it go?</b> You can use BOTH — the same article can
                    publish through a connected API and go to an operator for a second
                    platform. That is two placements and two links.
                  </div>

                  {(sent.connected || sent.extension) && (
                    <div className="op-flash" style={{ position: "static", display: "block", marginBottom: 10 }}>
                      {sent.connected && (
                        <div>
                          <b>Publishing to {sent.connected}</b> through its API — the live
                          URL appears in Placements once the post exists and our link has
                          been found on it.
                        </div>
                      )}
                      {sent.extension && (
                        <div style={{ marginTop: sent.connected ? 6 : 0 }}>
                          <b>Handed to the extension for {sent.extension}</b> — it is in the
                          Web 2.0 tab as copy-blocks; the operator pastes the public URL
                          back and the server checks it.
                        </div>
                      )}
                      {sent.connected && sent.extension && (
                        <div style={{ marginTop: 6 }}>
                          Both lanes are done. The similarity gate recorded a verdict on
                          the second placement — the same prose on two platforms is
                          exactly what it watches for.
                        </div>
                      )}
                    </div>
                  )}

                  <div className="modal-f" style={{ flexWrap: "wrap", gap: 8 }}>
                    {/* Reject disappears once anything has gone out: the article is
                        live or queued, and "reject" would claim to undo a publish it
                        cannot reach. */}
                    {!anySent && (
                      <button type="button" className="ghostbtn" onClick={reject} disabled={busy}>
                        Reject
                      </button>
                    )}
                    <button
                      type="button"
                      className={sent.connected ? "ghostbtn" : "primary-btn"}
                      onClick={() => decide("connected")}
                      disabled={busy || !!sent.connected}
                      title={
                        sent.connected
                          ? `Already sent to ${sent.connected}.`
                          : "Publishes through a connected platform's API and returns the live URL. If this platform has no connected account, the article is moved to one that does."
                      }
                    >
                      <span className="material-symbols-rounded">
                        {sent.connected ? "check" : "publish"}
                      </span>
                      {sent.connected ? `Published to ${sent.connected}` : "Publish to direct API"}
                    </button>
                    <button
                      type="button"
                      className={sent.extension ? "ghostbtn" : "primary-btn"}
                      onClick={() => decide("extension")}
                      disabled={busy || !!sent.extension}
                      title={
                        sent.extension
                          ? `Already handed to the extension for ${sent.extension}.`
                          : "Hands the article to an operator: it appears in the extension's Web 2.0 tab as copy-blocks, they publish it in their own logged-in session and paste the public URL back."
                      }
                    >
                      <span className="material-symbols-rounded">
                        {sent.extension ? "check" : "extension"}
                      </span>
                      {sent.extension ? `Sent for ${sent.extension}` : "Forward to extension"}
                    </button>
                    {anySent && (
                      <button type="button" className="ghostbtn" onClick={onClose}>
                        Done
                      </button>
                    )}
                  </div>
                </>
              )}

              {draft && draft.status === "failed" && (
                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={() => setStep("brief")}>
                    Back to the brief
                  </button>
                </div>
              )}
            </>
          )}

        </div>
      </div>
    </div>
  );
}
