"use client";

import { useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import {
  useCreateWeb2Campaign,
  useEstimateWeb2Campaign,
} from "@/lib/hooks/offpage";
import { type Web2PacingMode } from "@/lib/offpage";
import Web2PlatformPicker from "./Web2PlatformPicker";
import { useWeb2ClientIdentity } from "@/lib/hooks/offpage";

/**
 * Build a whole Web 2.0 campaign in one pass: client -> topics -> platforms -> pacing
 * -> QUOTE -> create.
 *
 * Two things about this screen are deliberate and are the reason it replaced the old
 * "plan property" modal.
 *
 * ONE DISTINCT TOPIC PER ARTICLE. The old modal fanned a single anchor across every
 * platform, which produces byte-identical articles (measured: resemblance 1.000) - the
 * duplicate-content behaviour the similarity gate now blocks one property at a time. So
 * topics are entered as a list and the count is derived from it; the operator cannot
 * accidentally ask for thirty copies of one article.
 *
 * THE QUOTE COMES BEFORE THE COMMIT. Thirty articles is thirty metered drafting runs and,
 * at the default pacing, about a month of publishing. Both facts are shown before the
 * create button does anything, because an operator who learns the timeline afterwards has
 * been misled by the tool.
 */
export default function Web2CampaignWizard({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const clientOptions = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);

  const [clientId, setClientId] = useState("");
  const [title, setTitle] = useState("");
  const [topicsText, setTopicsText] = useState("");
  const [anchorsText, setAnchorsText] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  // Fixed: approved campaigns publish as fast as the safety caps allow.
  const pacing: Web2PacingMode = "immediate";
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [proof, setProof] = useState("");
  // A SECOND grounding input, not a nicety. The generator asks for two different things
  // and gaps on each separately: `proofPoints` answers "why choose us" (real projects,
  // results, credentials) and `uniqueData` answers "what makes this different" (something
  // only this client knows). Collecting only the first left every UI-built campaign
  // holding at review with an unfillable gap - measured on a real client draft.
  const [uniqueData, setUniqueData] = useState("");
  // One answer covering every advisory platform in THIS campaign. Cleared whenever the
  // client or the platform set changes, so it can never outlive what it answered for.
  const [ackAdvisories, setAckAdvisories] = useState(false);
  const [created, setCreated] = useState<{ id: string; total: number } | null>(null);
  const [error, setError] = useState("");
  // The inputs AS THEY WERE when the quote was taken. Without this the operator can
  // quote three articles, add seven more topics, press Create, and get ten - while the
  // screen still shows the three-article price and finish date. The thing they approved
  // must be the thing that gets created, so a quote is invalidated the moment any input
  // that shaped it changes.
  const [quotedSignature, setQuotedSignature] = useState<string | null>(null);

  // The client's STANDING brief. The server already falls back to it, so leaving these
  // blank is safe; showing what will be used stops the operator wondering whether the
  // draft will be grounded.
  const identityQ = useWeb2ClientIdentity(clientId || undefined);

  const estimate = useEstimateWeb2Campaign();
  const create = useCreateWeb2Campaign();

  const topics = lines(topicsText);
  const anchors = lines(anchorsText);
  const proofLines = lines(proof);
  const canQuote =
    !!clientId && topics.length > 0 && selected.size > 0 && targetUrl.trim().startsWith("http");

  function toggle(platform: string) {
    // Changing the platform set retracts the acknowledgement: it answered a specific
    // list of warnings, and a different list is a different question.
    setAckAdvisories(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(platform)) next.delete(platform);
      else next.add(platform);
      return next;
    });
  }

  function body() {
    return {
      clientId,
      title: title.trim(),
      // The count IS the number of topics. Deriving it rather than asking separately is
      // what makes "thirty copies of one article" unrepresentable in this UI.
      articleCount: topics.length,
      topics,
      platforms: Array.from(selected),
      anchors,
      targetUrl: targetUrl.trim(),
      pacing,
      proofPoints: proofLines.slice(0, 12),
      uniqueData: lines(uniqueData).slice(0, 12),
      acknowledgePlatformAdvisories: ackAdvisories,
    };
  }

  // What the quote actually PROMISES: how many properties, on which platforms, at
  // what pace, for whom. Those decide the price and the finish date.
  //
  // The signature used to be the whole body, so editing the title or a proof point
  // invalidated a perfectly good quote and re-disabled Create - the operator had to
  // re-quote to change a word. Anchors and the target URL change what is created but
  // not what the quote claims, so they are out too. The guarded lie is "quote three,
  // create ten", and that remains impossible: count derives from topics, which is in.
  function quoteSignature() {
    return JSON.stringify({
      clientId,
      articleCount: topics.length,
      topics,
      platforms: Array.from(selected).sort(),
      pacing,
    });
  }

  async function quote() {
    setError("");
    try {
      await estimate.mutateAsync(body());
      setQuotedSignature(quoteSignature());
    } catch (e) {
      setQuotedSignature(null);
      setError(messageOf(e));
    }
  }

  async function commit() {
    setError("");
    try {
      const campaign = await create.mutateAsync(body());
      setCreated({ id: campaign.id, total: campaign.total });
    } catch (e) {
      setError(messageOf(e));
    }
  }

  // A quote only counts while the inputs it PRICED still match.
  const quoteIsCurrent = quotedSignature !== null && quotedSignature === quoteSignature();
  const quoted = quoteIsCurrent ? estimate.data : undefined;
  const quoteWentStale = quotedSignature !== null && !quoteIsCurrent;

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">New Web 2.0 campaign</div>
            <div className="modal-s">
              One distinct article per topic, each carrying a single editorial backlink.
              Nothing publishes until a lead approves.
            </div>
          </div>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        {created ? (
          <div className="wiz-body">
            <div className="op-flash" style={{ position: "static" }}>
              <span className="material-symbols-rounded">task_alt</span>
              Campaign created — {created.total} propert{created.total === 1 ? "y" : "ies"} queued.
              The write worker is drafting; each one parks at &ldquo;needs review&rdquo; for approval.
            </div>
            <div className="modal-f">
              <button className="primary-btn" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <div className="wiz-body">
            <div className="fld">
              <label>Client</label>
              <select value={clientId} onChange={(e) => { setClientId(e.target.value); setSelected(new Set()); setAckAdvisories(false); }}>
                <option value="">Choose a client…</option>
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.cn}</option>
                ))}
              </select>
              <div className="fld-hint">
                The client decides which platforms are available. Eligibility is computed from
                the client&rsquo;s declared topical scope (set on the client record; new clients
                default to the topic-agnostic set) against each platform&rsquo;s own posting rules —
                a local trade and a software company do not get the same list.
              </div>
            </div>

            <div className="fld">
              <label>Campaign name</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Autumn authority push" />
              <div className="fld-hint">
                Your own label for this batch, so it is findable later in the campaign list. It is
                never shown to the client and never published.
              </div>
            </div>

            <div className="fld">
              <label>Topics — one per line, one article each</label>
              <textarea
                rows={6}
                value={topicsText}
                onChange={(e) => setTopicsText(e.target.value)}
                placeholder={"emergency drain unblocking\ngutter cleaning in winter\nwhat a CCTV drain survey shows"}
              />
              <div className="fld-hint">
                <b>{topics.length}</b> article{topics.length === 1 ? "" : "s"}. Each topic becomes its
                own article — reusing a topic across platforms produces identical articles, which is
                refused.
              </div>
            </div>

            <div className="fld">
              <label>Anchor text options — one per line</label>
              <textarea
                rows={3}
                value={anchorsText}
                onChange={(e) => setAnchorsText(e.target.value)}
                placeholder={"Leeds Drainage\nthe drainage team\nour emergency callout"}
              />
              <div className="fld-hint">
                Rotated across the campaign. Keep them branded and natural — an exact-match
                commercial anchor repeated across properties is the clearest footprint there is.
              </div>
            </div>

            <div className="fld">
              <label>Target URL</label>
              <input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://client.example/services" />
              <div className="fld-hint">
                The page on the client&rsquo;s own site that every article links to — one editorial
                link each. Point it at the page you actually want to rank, not the homepage, unless
                the homepage is the target.
              </div>
            </div>

            {/* Platform board — server-computed per client, nothing hidden. */}
            <div className="fld">
              <label style={{ margin: 0 }}>Platforms</label>
              <Web2PlatformPicker
                clientId={clientId || undefined}
                selected={selected}
                onToggle={toggle}
                acknowledged={ackAdvisories}
                onAcknowledgedChange={setAckAdvisories}
                hint={(eligibleCount) => (
                  <div className="fld-hint">
                    <b>{selected.size}</b> of {eligibleCount} eligible selected. Spreading across
                    more platforms finishes sooner <em>and</em> leaves a lighter footprint.
                  </div>
                )}
                emptyEligibleHint={
                  // "0 of 0 eligible selected" over an empty grid is not an explanation.
                  // Nothing here is broken - this client has no CONNECTED account on any
                  // platform it is allowed to use. The lists below say which fix applies.
                  <div className="fld-hint">
                    <b>No platform is ready for this client yet.</b> If platforms this
                    client may use are listed below, add an account under <b>Accounts</b>{" "}
                    with this client selected — that is a ten-minute fix, not a bug.
                  </div>
                }
              />
            </div>

            {/* The pace SELECTOR is gone by decision (2026-08-29): approved campaigns
                publish automatically. Offering "drip" while the release tick is not
                running would have been the worst of both — the operator picks a schedule
                and the properties then sit unpublished forever. The safety caps still
                apply; they are what pace it now, not a dropdown.

                UPDATE (owner decision, same day): approved campaigns publish EVERY
                property immediately. A future `scheduled_for` handed the property to a
                release tick that nothing in this deployment runs, so it parked the work
                rather than pacing it - 1 property of N published and N were paid for. */}
            <div className="fld">
              <label>Proof &amp; first-hand experience — one per line</label>
              <textarea rows={3} value={proof} onChange={(e) => setProof(e.target.value)}
                placeholder={"Cleared 400 blocked drains across Leeds in 2025\n24-hour callout, no weekend surcharge"} />
              <div className="fld-hint">
                Without real proof the writer leaves <code>[NEEDS:]</code> gaps and the draft holds at
                review, un-publishable.
                {!proof.trim() && (identityQ.data?.proofPoints?.length ?? 0) > 0 && (
                  <>
                    {" "}Leave blank and this client&rsquo;s stored brief is used:{" "}
                    <b>{identityQ.data!.proofPoints.length} point(s)</b> already on file.
                  </>
                )}
              </div>
            </div>

            <div className="fld">
              <label>What only this client knows — one per line</label>
              <textarea rows={3} value={uniqueData} onChange={(e) => setUniqueData(e.target.value)}
                placeholder={"Across 40 audits, the bottleneck teams named was the real one 3 times in 10\nOur audit returns in ten minutes; the industry norm is two to three weeks"} />
              <div className="fld-hint">
                The <b>differentiation</b> angle. Proof above answers &ldquo;why choose them&rdquo;; this
                answers &ldquo;what makes this different&rdquo; — a separate <code>[NEEDS:]</code> gap,
                and the one that most often holds a draft at review.
                {!uniqueData.trim() && (identityQ.data?.uniqueData?.length ?? 0) > 0 && (
                  <>
                    {" "}Leave blank and this client&rsquo;s stored brief is used:{" "}
                    <b>{identityQ.data!.uniqueData.length} on file</b>.
                  </>
                )}
              </div>
            </div>

            {error && (
              <div className="op-flash" style={{ position: "static", background: "#fee2e2", color: "#991b1b" }}>
                <span className="material-symbols-rounded">error</span>
                {error}
              </div>
            )}

            {quoted && (
              <div className="fld" style={{ borderTop: "1px solid var(--line, #e5e7eb)", paddingTop: 12 }}>
                <label>Quote</label>
                <div className="fld-hint">
                  <b>{quoted.count}</b> propert{quoted.count === 1 ? "y" : "ies"} · about{" "}
                  <b>${quoted.estimatedCostUsd.toFixed(2)}</b> in drafting ·{" "}
                  {quoted.projectedCompletion
                    ? <>last one publishes <b>{new Date(quoted.projectedCompletion).toLocaleDateString()}</b></>
                    : <>all are <b>queued the moment you approve</b> — they go out as fast as the publish worker runs</>}
                </div>
                {quoted.notes.length > 0 && (
                  <ul style={{ margin: "8px 0 0 16px" }} className="fld-hint">
                    {quoted.notes.map((n, i) => <li key={i} style={{ marginBottom: 4 }}>{n}</li>)}
                  </ul>
                )}
              </div>
            )}

            <div className="modal-f">
              <button type="button" className="ghost-btn" onClick={quote}
                disabled={!canQuote || estimate.isPending}>
                {estimate.isPending ? "Pricing…" : "Get quote"}
              </button>
              <button type="button" className="primary-btn" onClick={commit}
                disabled={!quoted || create.isPending}>
                {create.isPending ? "Creating…" : `Create ${quoted?.count ?? ""} propert${quoted?.count === 1 ? "y" : "ies"}`}
              </button>
            </div>
            {/* Name the REAL reason Create is disabled. "Get a quote first" is only
                true when a quote is actually obtainable; when there are no eligible
                platforms or a required field is empty, it sends the operator to a
                button that is disabled for a different reason again. */}
            {!quoted && (
              <div className="fld-hint" style={{ textAlign: "right" }}>
                {!canQuote
                  ? selected.size === 0
                    ? "Choose at least one platform above — if none are offered, connect an account under Accounts first."
                    : topics.length === 0
                      ? "Add at least one topic — one per line."
                      : !targetUrl.trim().startsWith("http")
                        ? "Add the target URL these properties will link to."
                        : "Choose a client to continue."
                  : quoteWentStale
                    ? "The campaign changed since that quote — get a new one so the price and finish date match what will actually be created."
                    : "Get a quote first — it shows the cost and the finish date before anything is created."}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function lines(value: string): string[] {
  return value.split("\n").map((l) => l.trim()).filter(Boolean);
}

/** Surface the server's own refusal text - it explains WHAT to change. */
function messageOf(e: unknown): string {
  const detail = (e as { body?: { error?: { message?: string } } })?.body?.error?.message;
  if (detail) return detail;
  return e instanceof Error ? e.message : "Something went wrong.";
}
