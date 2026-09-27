"use client";

import { useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import {
  useCreateWeb2Campaign,
  usePlanWeb2Broadcast,
  useWeb2ConnectionPlan,
} from "@/lib/hooks/offpage";
import { WEB2_ALL_PLATFORMS, type Web2BroadcastPlan } from "@/lib/offpage";
import Web2PlatformPicker from "./Web2PlatformPicker";

/**
 * Compose once, publish everywhere — with the fan-out shown BEFORE anything is paid for.
 *
 * WHY THIS IS NOT "ONE POST SENT TO N PLATFORMS". A measured run of the real generator
 * put the same subject on thirty platforms and produced thirty byte-identical articles
 * (body r = 1.000). The similarity gate then blocked all thirty — after thirty metered
 * drafting runs had been billed. So one subject fans out into VARIANTS: each placement
 * gets its own shape (a 900-word article on Ghost, a 29-word note on Bluesky), its own
 * angle on the subject, and a rotated framework.
 *
 * WHY PLAN AND COMMIT ARE TWO BUTTONS. The plan writes nothing — no draft, no property,
 * no spend. The alternative is discovering at the review gate that nine of the twenty
 * platforms you picked were excluded, having already paid for twenty drafting runs.
 * Excluded platforms are RENDERED with their reasons rather than dropped: a selection
 * quietly shrunk from twenty to six is a lie an operator finds weeks later in a report.
 *
 * WHAT "PUBLISH" HONESTLY MEANS HERE. Committing queues the drafts and hands them to the
 * campaign pipeline — every property still stops at the review gate, where a lead reads
 * it and approves or rejects. Nothing on this screen puts an unread article on a live
 * site, and the button does not claim it does.
 */

type Step = "compose" | "platforms" | "review";

const STEP_LABEL: Record<Step, string> = {
  compose: "Step 1 of 3 · What the broadcast is about",
  platforms: "Step 2 of 3 · Where it goes",
  review: "Step 3 of 3 · Read the fan-out, then commit",
};

/** `article` / `note` / `snippet` / `profile` — the field that decides whether a
 *  placement is a blog post or a 300-character note, which is a difference in KIND. */
const SHAPE_META: Record<string, { label: string; cls: string }> = {
  article: { label: "Article", cls: "ok" },
  note: { label: "Note", cls: "info" },
  snippet: { label: "Snippet", cls: "warn" },
  profile: { label: "Profile", cls: "mut" },
};

function lines(value: string): string[] {
  return value.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 20);
}

export default function Web2BroadcastComposer({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];

  const [step, setStep] = useState<Step>("compose");
  const [clientId, setClientId] = useState("");
  const [subject, setSubject] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [anchorText, setAnchorText] = useState("");
  const [all, setAll] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acknowledged, setAcknowledged] = useState(false);
  const [plan, setPlan] = useState<Web2BroadcastPlan | null>(null);
  const [error, setError] = useState("");
  const [committed, setCommitted] = useState("");

  const planM = usePlanWeb2Broadcast();
  const createCampaign = useCreateWeb2Campaign();
  // Readiness is a fact about the client, and it belongs in front of the operator at the
  // moment they pick "All" — not after a plan comes back with half the list excluded.
  const connectionQ = useWeb2ConnectionPlan(clientId || undefined);

  const anchors = useMemo(() => lines(anchorText), [anchorText]);
  const canCompose = !!clientId && subject.trim().length >= 3 && !!targetUrl.trim();
  const canPlan = canCompose && (all || selected.size > 0);

  function toggle(platformKey: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(platformKey)) next.delete(platformKey);
      else next.add(platformKey);
      return next;
    });
    // Ticking a platform by hand is a narrower intention than All, so All releases
    // rather than silently overriding what was just clicked.
    setAll(false);
  }

  function requestPlan() {
    setError("");
    setCommitted("");
    planM.mutate(
      {
        clientId,
        subject: subject.trim(),
        targetUrl: targetUrl.trim(),
        platforms: all ? [WEB2_ALL_PLATFORMS] : [...selected],
        anchors,
      },
      {
        onSuccess: (data) => {
          setPlan(data);
          setStep("review");
        },
        onError: (err) => setError((err as Error)?.message ?? "Could not build the plan."),
      },
    );
  }

  function commit() {
    if (!plan || plan.posts.length === 0) return;
    setError("");
    createCampaign.mutate(
      {
        clientId,
        title: plan.subject,
        articleCount: plan.posts.length,
        // ONE DISTINCT TOPIC PER PLACEMENT, taken straight from the plan. This is the
        // whole reason the plan exists: the campaign route refuses a reused topic, and
        // the per-platform angles are what make these N genuinely different articles
        // rather than N copies the similarity gate will block.
        topics: plan.posts.map((p) => p.topic),
        platforms: plan.posts.map((p) => p.platform),
        anchors,
        targetUrl: targetUrl.trim(),
        pacing: "drip",
        acknowledgePlatformAdvisories: acknowledged,
      },
      {
        onSuccess: (campaign) => {
          setCommitted(
            `Queued ${plan.posts.length} placement(s) as “${campaign.title || plan.subject}”. ` +
            "Each one is drafted, then waits at the review gate for a lead to read it.",
          );
        },
        onError: (err) => setError((err as Error)?.message ?? "Could not queue the campaign."),
      },
    );
  }

  return (
    // Self-wrapped in `.tw` because the overlay styles are scoped `.tw .modal-scrim`
    // in globals.css and the ADMIN LAYOUT DOES NOT PROVIDE ONE. Without it this
    // renders inline as a card in the page flow — visibly a modal that is not one,
    // with the table it covers still scrolling underneath. Same fix as
    // CitationCampaignModal, which carries the same note.
    <div className="tw">
      <div className="modal-scrim" onClick={onClose}>
        <div className="modal wide" onClick={(e) => e.stopPropagation()}>
          <div className="modal-h">
            <div>
              <div className="modal-t">Write once, publish everywhere</div>
              <div className="modal-s">{STEP_LABEL[step]}</div>
            </div>
            <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
              <span className="material-symbols-rounded" aria-hidden="true">close</span>
            </button>
          </div>

          <div className="wiz-body">
            {error && <div className="note bad" style={{ marginBottom: 12 }}>{error}</div>}

            {/* ---- Step 1: the subject ------------------------------------- */}
            {step === "compose" && (
              <>
                <div className="fld">
                  <label htmlFor="bc-client">Client</label>
                  <select
                    id="bc-client"
                    value={clientId}
                    onChange={(e) => { setClientId(e.target.value); setPlan(null); }}
                  >
                    <option value="">Choose a client…</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>{c.cn}</option>
                    ))}
                  </select>
                </div>

                <div className="fld">
                  <label htmlFor="bc-subject">What is this broadcast about?</label>
                  <input
                    id="bc-subject"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="Emergency drain unblocking in Leeds"
                    maxLength={200}
                  />
                  <div className="fld-hint">
                    ONE subject. Each platform gets its own angle on it — the same text sent
                    to thirty platforms produced thirty identical articles when this was
                    measured, and the similarity gate blocked every one of them after they
                    had all been paid for.
                  </div>
                </div>

                <div className="fld">
                  <label htmlFor="bc-target">The page every placement links to</label>
                  <input
                    id="bc-target"
                    value={targetUrl}
                    onChange={(e) => setTargetUrl(e.target.value)}
                    placeholder="https://leedsdrainage.co.uk/emergency"
                  />
                </div>

                <div className="fld">
                  <label htmlFor="bc-anchors">Anchor text — one per line (optional)</label>
                  <textarea
                    id="bc-anchors"
                    rows={3}
                    value={anchorText}
                    onChange={(e) => setAnchorText(e.target.value)}
                    placeholder={"Leeds Drainage Co\nemergency drain help in Leeds\nhttps://leedsdrainage.co.uk"}
                  />
                  <div className="fld-hint">
                    Left blank, the brand name is used. An exact-match commercial anchor is
                    refused before it can be chosen, and the refusal is reported rather than
                    quietly swapped — otherwise the same list comes back next time.
                  </div>
                </div>

                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                  <button
                    type="button" className="primary-btn" disabled={!canCompose}
                    onClick={() => setStep("platforms")}
                  >
                    Choose platforms
                    <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
                  </button>
                </div>
              </>
            )}

            {/* ---- Step 2: where it goes ----------------------------------- */}
            {step === "platforms" && (
              <>
                {/* ALL IS A DELIBERATE CHOICE, not the absence of one. The server refuses an
                    empty list rather than reading it as everything: "none chosen" and
                    "everywhere" are different intentions, and a blank must never mean the
                    second. So All is its own explicit control. */}
                <label
                  className={`chip${all ? " on" : ""}`}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "12px 14px",
                    marginBottom: 12, width: "100%",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={all}
                    onChange={(e) => { setAll(e.target.checked); if (e.target.checked) setSelected(new Set()); }}
                    style={{ width: 16, height: 16 }}
                  />
                  <span>
                    <b>All platforms this client can publish to</b>
                    <div className="fld-hint" style={{ marginTop: 2 }}>
                      Everything open for {clients.find((c) => c.id === clientId)?.cn ?? "this client"} right now.
                      Platforms that cannot take it are listed with a reason in the next step — never dropped silently.
                    </div>
                  </span>
                </label>

                {connectionQ.data && (
                  <div className="fld-hint" style={{ marginBottom: 10 }}>
                    {connectionQ.data.summary}
                  </div>
                )}

                <div className="fld-hint" style={{ marginBottom: 8 }}>
                  Or tick them individually:
                </div>
                <Web2PlatformPicker
                  clientId={clientId || undefined}
                  selected={selected}
                  onToggle={toggle}
                  acknowledged={acknowledged}
                  onAcknowledgedChange={setAcknowledged}
                  hint={(n) =>
                    all
                      ? `All ${n} open platform(s) selected.`
                      : `${selected.size} of ${n} open platform(s) selected.`
                  }
                />

                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={() => setStep("compose")}>
                    Back
                  </button>
                  <button
                    type="button" className="primary-btn"
                    disabled={!canPlan || planM.isPending}
                    onClick={requestPlan}
                    title="Shows exactly what each platform would receive. Nothing is drafted, published or billed by this step."
                  >
                    <span className="material-symbols-rounded" aria-hidden="true">preview</span>
                    {planM.isPending ? "Working it out…" : "Show me what goes where"}
                  </button>
                </div>
              </>
            )}

            {/* ---- Step 3: the fan-out ------------------------------------- */}
            {step === "review" && plan && (
              <>
                <div className="fld-hint" style={{ marginBottom: 10 }}>{plan.summary}</div>

                {plan.notes.map((note, i) => (
                  <div key={i} className="note" style={{ marginBottom: 8 }}>{note}</div>
                ))}

                {plan.posts.length === 0 ? (
                  <div className="op-empty">
                    Nothing can go out for this selection. The reasons are listed below —
                    each one names what would have to change.
                  </div>
                ) : (
                  <div className="tbl-wrap">
                    <table className="tbl op-tbl">
                      <thead>
                        <tr>
                          <th>Platform</th>
                          <th>Gets</th>
                          <th>Its angle on the subject</th>
                          <th>Framework</th>
                          <th>Anchor</th>
                        </tr>
                      </thead>
                      <tbody>
                        {plan.posts.map((post) => {
                          const shape = SHAPE_META[post.shape] ?? { label: post.shape, cls: "mut" };
                          return (
                            <tr key={post.platform}>
                              <td className="op-strong">{post.platform}</td>
                              <td>
                                <span className={`status-pill ${shape.cls}`}>{shape.label}</span>
                                {post.wordTarget > 0 && (
                                  <span className="op-muted" style={{ marginLeft: 6 }}>
                                    ~{post.wordTarget} words
                                  </span>
                                )}
                              </td>
                              <td>{post.angle || post.topic}</td>
                              <td className="op-muted">{post.framework || "—"}</td>
                              <td><span className="op-anchor">{post.anchor}</span></td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* EXCLUSIONS ARE PART OF THE ANSWER, not a footnote. This is the list that
                    used to be discovered at the review gate, after the drafting had been
                    billed for platforms that were never going to receive anything. */}
                {plan.excluded.length > 0 && (
                  <details open style={{ marginTop: 14 }}>
                    <summary style={{ cursor: "pointer", fontWeight: 700 }}>
                      {plan.excluded.length} selected platform(s) will receive nothing
                    </summary>
                    <div className="tbl-wrap" style={{ marginTop: 8 }}>
                      <table className="tbl op-tbl">
                        <thead>
                          <tr><th>Platform</th><th>Why not</th></tr>
                        </thead>
                        <tbody>
                          {plan.excluded.map((row) => (
                            <tr key={row.platform}>
                              <td className="op-strong">{row.platform}</td>
                              <td>{row.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )}

                {committed ? (
                  <div
                    className="op-flash"
                    style={{ position: "static", display: "block", marginTop: 14 }}
                  >
                    <span className="material-symbols-rounded" aria-hidden="true">task_alt</span> {committed}
                  </div>
                ) : (
                  <div className="fld-hint" style={{ marginTop: 14 }}>
                    Committing queues <b>{plan.posts.length}</b> drafting run(s). Each placement
                    is written, then <b>held at the review gate</b> until a lead reads it and
                    approves — nothing here publishes an unread article.
                  </div>
                )}

                <div className="modal-f" style={{ flexWrap: "wrap", gap: 8 }}>
                  <button
                    type="button" className="ghostbtn"
                    onClick={() => { setStep("platforms"); setCommitted(""); }}
                  >
                    Back
                  </button>
                  {committed ? (
                    <button type="button" className="primary-btn" onClick={onClose}>
                      Done
                    </button>
                  ) : (
                    <button
                      type="button" className="primary-btn"
                      disabled={plan.posts.length === 0 || createCampaign.isPending}
                      onClick={commit}
                    >
                      <span className="material-symbols-rounded" aria-hidden="true">rocket_launch</span>
                      {createCampaign.isPending
                        ? "Queueing…"
                        : `Queue ${plan.posts.length} placement(s)`}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
