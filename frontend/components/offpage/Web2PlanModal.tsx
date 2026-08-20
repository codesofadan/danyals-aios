"use client";

import { useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import { usePlanWeb2 } from "@/lib/hooks/offpage";
import { LIVE_WEB2_PLATFORMS, PLATFORM_META, type Web2Platform } from "@/lib/offpage";

export default function Web2PlanModal({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const clientOptions = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);
  const [clientId, setClientId] = useState("");
  // Multi-select: the module's whole point is to fan ONE article out to EVERY live web2
  // property in one click (footprint diversity), so default to ALL platforms selected.
  const [platforms, setPlatforms] = useState<Set<Web2Platform>>(() => new Set(LIVE_WEB2_PLATFORMS));
  const [anchor, setAnchor] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [pageType, setPageType] = useState<"service" | "blog" | "local">("blog");
  const [proof, setProof] = useState("");

  const plan = usePlanWeb2();
  const [planned, setPlanned] = useState(false);
  const [plannedCount, setPlannedCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const allOn = platforms.size === LIVE_WEB2_PLATFORMS.length;
  const canPlan = !!clientId && platforms.size > 0 && anchor.trim().length > 1 && targetUrl.trim().startsWith("http");
  const proofLines = proof.split("\n").map((l) => l.trim()).filter(Boolean);

  function toggleAll() {
    setPlatforms(allOn ? new Set() : new Set(LIVE_WEB2_PLATFORMS));
  }
  function togglePlatform(p: Web2Platform) {
    setPlatforms((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      return next;
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canPlan || submitting) return;
    const chosen = Array.from(platforms);
    setSubmitting(true);
    // One plan per selected platform — a branded article + one editorial backlink each.
    const results = await Promise.allSettled(
      chosen.map((platform) =>
        plan.mutateAsync({
          clientId, platform, anchor: anchor.trim(), targetUrl: targetUrl.trim(), pageType,
          proofPoints: proofLines.slice(0, 12),
        }),
      ),
    );
    setSubmitting(false);
    setPlannedCount(results.filter((r) => r.status === "fulfilled").length);
    setPlanned(true);
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">Plan Web 2.0 properties</div>
            <div className="modal-s">
              Fans ONE branded article — each carrying a single editorial backlink — out to every
              selected platform. They park at &ldquo;needs review&rdquo;; nothing publishes until a lead approves.
            </div>
          </div>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        {planned ? (
          <div className="wiz-body">
            <div className="op-flash" style={{ position: "static" }}>
              <span className="material-symbols-rounded">task_alt</span>
              Queued {plannedCount} propert{plannedCount === 1 ? "y" : "ies"} — the write worker is drafting now.
              Check &ldquo;Needs review&rdquo; to approve or reject each one.
            </div>
            <div className="modal-f">
              <button className="primary-btn" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <form className="wiz-body" onSubmit={submit}>
            <div className="fld">
              <label>Client</label>
              <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
                <option value="">Choose a client…</option>
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.cn}</option>
                ))}
              </select>
            </div>

            {/* Platforms — multi-select, all-on by default; one click to select/clear all */}
            <div className="fld">
              <div className="w2-plat-head">
                <label style={{ margin: 0 }}>Platforms — one article published to each</label>
                <button type="button" className="w2-selall" onClick={toggleAll}>
                  <span className="material-symbols-rounded">{allOn ? "remove_done" : "done_all"}</span>
                  {allOn ? "Clear all" : "Select all"}
                </button>
              </div>
              <div className="w2-plat-grid">
                {LIVE_WEB2_PLATFORMS.map((p) => {
                  const on = platforms.has(p);
                  return (
                    <button type="button" key={p} onClick={() => togglePlatform(p)}
                      className={`w2-plat${on ? " on" : ""}`} aria-pressed={on}>
                      <span className="op-plat-ic" style={{ background: PLATFORM_META[p].c }}>
                        <span className="material-symbols-rounded" style={{ fontSize: 14 }}>{PLATFORM_META[p].icon}</span>
                      </span>
                      <span className="w2-plat-name">{p}</span>
                      <span className="material-symbols-rounded w2-plat-check">
                        {on ? "check_circle" : "radio_button_unchecked"}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="fld-hint">
                <b>{platforms.size}</b> of {LIVE_WEB2_PLATFORMS.length} platforms — {platforms.size === LIVE_WEB2_PLATFORMS.length
                  ? "publishing to all of them in one go."
                  : "one branded article + one editorial backlink each."}
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
              <input value={anchor} onChange={(e) => setAnchor(e.target.value)} placeholder="gentle dental cleanings" />
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
            <div className="op-muted">
              Each platform needs its own account credential saved in the vault; any platform without one
              simply holds its draft at &ldquo;needs review&rdquo; until a credential is added — the rest still queue.
            </div>
            <div className="modal-f">
              <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
              <button type="submit" className="primary-btn" disabled={!canPlan || submitting}>
                {submitting ? "Queuing…" : `Plan ${platforms.size} propert${platforms.size === 1 ? "y" : "ies"}`}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
