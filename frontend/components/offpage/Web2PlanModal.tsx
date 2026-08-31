"use client";

import { useEffect, useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import { useCheckWeb2Anchor, usePlanWeb2, useWeb2PlatformBoard } from "@/lib/hooks/offpage";
import { PLATFORM_ISSUES, PLATFORM_META, type Web2Platform } from "@/lib/offpage";

// Build ONE Web 2.0 property.
//
// THREE DEFECTS THIS CLOSES, all of which produced the same symptom — "Single Property
// is not working" — from different directions:
//
//  1. IT REPORTED SUCCESS FOR TOTAL FAILURE. The submit fanned one request per selected
//     platform through `Promise.allSettled`, counted only the fulfilled ones, and then
//     showed the success panel unconditionally. Every request could 422 and the
//     operator still read "Queued 0 properties — the write worker is drafting now."
//     Rejections were never inspected and `plan.isError` was never rendered.
//
//  2. IT OFFERED PLATFORMS THE SERVER REFUSES. The picker listed a static client-side
//     constant of ~54 platforms, while the backend 422s per platform on
//     `not_connected` / `not_eligible` computed from the client's actual credentials.
//     Almost every selection failed — invisibly, because of (1). The campaign wizard
//     already did this correctly against `GET /offpage/web2/platform-board`; this modal
//     was simply never migrated.
//
//  3. EVERY ARTICLE WAS WRITTEN ABOUT ITS OWN LINK TEXT. No `topic` was ever sent, so
//     `plan_web2` fell back to `topic = anchor`.
//
// It is now genuinely SINGLE. The fan-out was the cause, not just the reporting
// surface: one modal quietly issuing N metered writes cannot report N outcomes in one
// boolean. Multi-platform is what New campaign already does properly — distinct topic
// per article, framework rotation, and a cost quote before it commits.
export default function Web2PlanModal({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const clientOptions = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);
  const [clientId, setClientId] = useState("");
  const [platform, setPlatform] = useState<string>("");
  const [topic, setTopic] = useState("");
  const [anchor, setAnchor] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [pageType, setPageType] = useState<"service" | "blog" | "local">("blog");
  const [proof, setProof] = useState("");

  const boardQ = useWeb2PlatformBoard(clientId || undefined);
  const board = useMemo(() => boardQ.data ?? [], [boardQ.data]);
  // Two DIFFERENT problems, so two lists — the same split the campaign wizard makes.
  // `not_connected` is a missing credential an operator fixes in ten minutes;
  // `not_eligible` is a judgement about this client that no credential changes.
  const eligible = board.filter((r) => r.status === "eligible");
  const needsAccount = board.filter((r) => r.status === "not_connected");
  const blocked = board.filter((r) => r.status === "not_eligible");

  const plan = usePlanWeb2();
  const anchorCheck = useCheckWeb2Anchor();
  const [anchorVerdict, setAnchorVerdict] = useState<{ allowed: boolean; reason: string; suggestion: string } | null>(null);
  const [created, setCreated] = useState<{ id: string; platform: string } | null>(null);

  // Changing the client re-scopes the board, so a platform chosen for the previous
  // client must not survive — it may not even be offered to this one.
  useEffect(() => { setPlatform(""); }, [clientId]);
  // Any edit invalidates a verdict about the old text.
  useEffect(() => { setAnchorVerdict(null); }, [anchor, targetUrl, topic, clientId]);

  const proofLines = proof.split("\n").map((l) => l.trim()).filter(Boolean);
  const anchorRefused = anchorVerdict !== null && !anchorVerdict.allowed;
  const canPlan =
    !!clientId && !!platform && topic.trim().length > 2 &&
    anchor.trim().length > 1 && targetUrl.trim().startsWith("http") && !anchorRefused;

  // Check the anchor when the operator leaves the field: a refusal then costs nothing,
  // where the same refusal at submit used to arrive as a swallowed 422.
  function verifyAnchor() {
    if (!clientId || anchor.trim().length < 2) return;
    anchorCheck.mutate(
      { clientId, anchor: anchor.trim(), targetUrl: targetUrl.trim(), topic: topic.trim() },
      { onSuccess: (v) => setAnchorVerdict({ allowed: v.allowed, reason: v.reason, suggestion: v.suggestion }) },
    );
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canPlan || plan.isPending) return;
    // ONE request, one outcome. The success panel is reachable only from a resolved
    // promise carrying a real property id.
    plan.mutate(
      {
        clientId, platform: platform as Web2Platform, anchor: anchor.trim(),
        targetUrl: targetUrl.trim(), pageType, topic: topic.trim(),
        proofPoints: proofLines.slice(0, 12),
      },
      { onSuccess: (row) => setCreated({ id: row.id, platform: row.platform }) },
    );
  }

  const issue = platform ? PLATFORM_ISSUES[platform as Web2Platform] : undefined;

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">Build one Web 2.0 property</div>
            <div className="modal-s">
              One branded article carrying a single editorial backlink. It parks at
              &ldquo;needs review&rdquo;; nothing publishes until a lead approves it.
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
              Queued <b>{created.platform}</b> — the write worker is drafting now.
              Check &ldquo;Needs review&rdquo; to approve or reject it.
            </div>
            <div className="modal-f">
              <button className="primary-btn" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <form className="wiz-body" onSubmit={submit}>
            <div className="fld">
              <label>Client</label>
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
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.cn}</option>
                ))}
              </select>
            </div>

            {/* Platform — exactly what the SERVER says this client may publish to. */}
            <div className="fld">
              <label style={{ margin: 0 }}>Platform</label>
              {!clientId ? (
                <div className="fld-hint">Choose a client to see which platforms they may publish to.</div>
              ) : boardQ.isLoading ? (
                <div className="fld-hint">Loading the platform board…</div>
              ) : boardQ.isError ? (
                <div className="fld-hint" style={{ color: "var(--warn)" }} role="alert">
                  Couldn&apos;t load the platform board — {(boardQ.error as Error)?.message ?? "try again"}.
                </div>
              ) : (
                <>
                  {eligible.length === 0 ? (
                    <div className="fld-hint" style={{ color: "var(--warn)" }}>
                      No platform is currently available for this client. Connect an account
                      below, then come back — planning against an unavailable platform is
                      refused by the server.
                    </div>
                  ) : (
                    <div className="w2-plat-grid">
                      {eligible.map((row) => {
                        const key = row.platform ?? row.name;
                        const on = platform === key;
                        const meta = PLATFORM_META[key as Web2Platform];
                        const flagged = PLATFORM_ISSUES[key as Web2Platform];
                        return (
                          <button
                            type="button" key={key} onClick={() => setPlatform(key)}
                            className={`w2-plat${on ? " on" : ""}`} aria-pressed={on}
                            title={flagged ?? undefined}
                          >
                            <span className="op-plat-ic" style={{ background: meta?.c ?? "#64748b" }}>
                              <span className="material-symbols-rounded" style={{ fontSize: 14 }}>
                                {meta?.icon ?? "public"}
                              </span>
                            </span>
                            <span className="w2-plat-name">
                              {row.name}
                              {/* A house account that exists but cannot publish, flagged
                                  where it is CHOSEN — it used to appear only on the
                                  API-status board, which nobody reads while planning. */}
                              {flagged && <span style={{ color: "#92400e" }}> *</span>}
                            </span>
                            <span className="material-symbols-rounded w2-plat-check">
                              {on ? "check_circle" : "radio_button_unchecked"}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {issue && (
                    <div className="fld-hint" style={{ color: "#92400e", marginTop: 6 }}>
                      ⚠ {issue}
                    </div>
                  )}
                  <div className="fld-hint">
                    Building on more than one platform? Use <b>New campaign</b> — it takes a
                    distinct topic per article and rotates the writing framework, so the
                    properties are not near-identical.
                  </div>

                  {needsAccount.length > 0 && (
                    <details className="fld-hint" style={{ marginTop: 8 }} open={eligible.length === 0}>
                      <summary>
                        {needsAccount.length} more platform(s) this client may use — connect an account
                      </summary>
                      <ul style={{ margin: "8px 0 0 16px" }}>
                        {needsAccount.map((row) => (
                          <li key={row.name} style={{ marginBottom: 8 }}>
                            <b>{row.name}</b>
                            {row.setupCost && !/^free/i.test(row.setupCost) && (
                              <span style={{ color: "#92400e" }}> — {row.setupCost}</span>
                            )}
                            {row.setupBlocker && (
                              <div style={{ color: "#92400e", marginTop: 2 }}>⚠ {row.setupBlocker}</div>
                            )}
                            {row.setupSteps && <div style={{ marginTop: 2 }}>{row.setupSteps}</div>}
                            {row.setupUrl && (
                              <div style={{ marginTop: 2 }}>
                                <a href={row.setupUrl} target="_blank" rel="noopener noreferrer">
                                  {row.setupUrl}
                                </a>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

                  {blocked.length > 0 && (
                    <details className="fld-hint" style={{ marginTop: 8 }}>
                      <summary>{blocked.length} platform(s) not available for this client — why</summary>
                      <ul style={{ margin: "8px 0 0 16px" }}>
                        {blocked.map((row) => (
                          <li key={row.name} style={{ marginBottom: 4 }}>
                            <b>{row.name}</b> — {row.reason}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
            </div>

            <div className="fld">
              <label>Topic — what the article is about</label>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="what a CCTV drain survey actually shows"
              />
              <div className="fld-hint">
                Not the same thing as the anchor. With no topic the writer was handed the
                LINK TEXT as its subject, so every property was an article about its own
                anchor.
              </div>
            </div>

            <div className="fld">
              <label>Page type</label>
              <select value={pageType} onChange={(e) => setPageType(e.target.value as "service" | "blog" | "local")}>
                <option value="blog">Blog</option>
                <option value="service">Service</option>
                <option value="local">Local</option>
              </select>
            </div>

            <div className="fld">
              <label>Anchor text (branded/natural — not exact-match commercial)</label>
              <input
                value={anchor}
                onChange={(e) => setAnchor(e.target.value)}
                onBlur={verifyAnchor}
                placeholder="gentle dental cleanings"
                aria-invalid={anchorRefused || undefined}
              />
              {anchorCheck.isPending && <div className="fld-hint">Checking the anchor…</div>}
              {anchorRefused && (
                <div className="fld-hint" style={{ color: "var(--warn)" }} role="alert">
                  {anchorVerdict?.reason}
                  {anchorVerdict?.suggestion && <> — try instead: <b>{anchorVerdict.suggestion}</b></>}
                </div>
              )}
              {anchorVerdict?.allowed && (
                <div className="fld-hint" style={{ color: "var(--ok)" }}>This anchor is fine.</div>
              )}
            </div>

            <div className="fld">
              <label>Target URL (the client page this backlink points to)</label>
              <input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://client.example/services" />
            </div>

            <div className="fld">
              <label>Proof &amp; first-hand experience (one per line)</label>
              <textarea rows={3} value={proof} onChange={(e) => setProof(e.target.value)}
                placeholder={"Real projects, results, credentials — the writer grounds against these.\ne.g. Rebuilt 40 storm-damaged roofs in 2025\ne.g. 25-year workmanship warranty"} />
              {proofLines.length === 0 && (
                <div className="fld-hint" style={{ color: "var(--warn)" }}>
                  Without proof the draft holds at review on [NEEDS:] gaps — add at least one line.
                </div>
              )}
            </div>

            {/* The failure that used to be invisible. */}
            {plan.isError && (
              <div className="login-error" role="alert">
                <span className="material-symbols-rounded">error</span>
                Nothing was queued — {(plan.error as Error)?.message ?? "the server refused it"}.
              </div>
            )}

            <div className="modal-f">
              <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
              <button type="submit" className="primary-btn" disabled={!canPlan || plan.isPending}>
                {plan.isPending ? "Queuing…" : "Build this property"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
