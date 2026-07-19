"use client";

import { useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import { usePlanWeb2 } from "@/lib/hooks/offpage";
import { LIVE_WEB2_PLATFORMS, PLATFORM_META, type Web2Platform } from "@/lib/offpage";

export default function Web2PlanModal({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const clientOptions = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);
  const [clientId, setClientId] = useState("");
  const [platform, setPlatform] = useState<Web2Platform>("WordPress.com");
  const [anchor, setAnchor] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [pageType, setPageType] = useState<"service" | "blog" | "local">("blog");

  const plan = usePlanWeb2();
  const [planned, setPlanned] = useState(false);

  const canPlan = !!clientId && anchor.trim().length > 1 && targetUrl.trim().startsWith("http");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canPlan) return;
    plan.mutate(
      { clientId, platform, anchor: anchor.trim(), targetUrl: targetUrl.trim(), pageType },
      { onSuccess: () => setPlanned(true) },
    );
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">Plan a Web 2.0 property</div>
            <div className="modal-s">
              Drafts a branded article carrying ONE editorial backlink. It parks at
              &ldquo;needs review&rdquo; — nothing publishes until a lead approves it below.
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
              Queued — the write worker is drafting the article now. Check back under
              &ldquo;Needs review&rdquo; to approve or reject it.
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
            <div className="fld-row">
              <div className="fld">
                <label>Platform (choose for footprint diversity)</label>
                <select value={platform} onChange={(e) => setPlatform(e.target.value as Web2Platform)}>
                  {LIVE_WEB2_PLATFORMS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div className="fld">
                <label>Page type</label>
                <select value={pageType} onChange={(e) => setPageType(e.target.value as "service" | "blog" | "local")}>
                  <option value="blog">Blog</option>
                  <option value="service">Service</option>
                  <option value="local">Local</option>
                </select>
              </div>
            </div>
            <div className="fld">
              <label>Anchor text (branded/natural — not exact-match commercial)</label>
              <input value={anchor} onChange={(e) => setAnchor(e.target.value)} placeholder="gentle dental cleanings" />
            </div>
            <div className="fld">
              <label>Target URL (the client page this backlink points to)</label>
              <input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://client.example/services" />
            </div>
            <div className="op-muted">
              Publishing to <b>{platform}</b>{" "}
              <span className="op-plat-ic" style={{ background: PLATFORM_META[platform].c, display: "inline-flex", verticalAlign: "middle" }}>
                <span className="material-symbols-rounded" style={{ fontSize: 14 }}>{PLATFORM_META[platform].icon}</span>
              </span>{" "}
              requires a per-account credential already saved in the vault, or the draft holds at
              &ldquo;needs review&rdquo; until one is added.
            </div>
            <div className="modal-f">
              <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
              <button type="submit" className="primary-btn" disabled={!canPlan || plan.isPending}>
                {plan.isPending ? "Queuing…" : "Plan property"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
