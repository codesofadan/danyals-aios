"use client";

// Wave 4: the Web 2.0 + citation-engine API STATUS BOARD. Each platform / engine reads
// CONNECTED (a real vault credential or a configured key is present) vs MISSING, with the
// exact reason and an honest note that even a connected provider can be refused by the
// EXTERNAL API. Reads /citation-builder/web2-status + /engine-status; degrades cleanly.

import { useWeb2Status } from "@/lib/hooks/offpage";
import { PLATFORM_ISSUES, type Web2Platform } from "@/lib/offpage";
import w from "./Wave4.module.css";

function StatusDot({ connected, draftOnly }: { connected: boolean; draftOnly?: boolean }) {
  const cls = draftOnly ? w.dotMut : connected ? w.dotOn : w.dotOff;
  return <span className={`${w.dot} ${cls}`} aria-hidden />;
}

export default function Web2StatusBoard() {
  const web2Q = useWeb2Status();
  const web2 = web2Q.data;

  return (
    <div>
      {/* Web 2.0 publishing platforms */}
      <div className={w.rollup}>
        <span>
          <b>Web 2.0 publishing</b> - per-client credentials live in the vault
        </span>
        {web2 && (
          <span>
            <b>{web2.connectedCount}</b> connected · <b>{web2.liveCount}</b> live-capable ·{" "}
            {web2.totalCount} platforms
          </span>
        )}
      </div>

      {web2Q.isLoading && <div className="op-muted">Loading platform status…</div>}
      {web2Q.isError && (
        <div className="op-muted">
          Couldn&apos;t load Web 2.0 status - {(web2Q.error as Error)?.message ?? "try again"}. Every
          platform is treated as MISSING until it loads.
        </div>
      )}
      {/* This board answers "which credentials exist in the vault?" — an integrations
          question. "Which platforms may THIS client use, and why not?" is a different
          question, answered per client on the platform board inside One property / New
          campaign. Rendering all ~54 credential slots open here made the two easy to
          confuse, so the full grid is behind a fold. */}
      <div className="op-muted" style={{ margin: "6px 0 10px" }}>
        Per-client availability, reasons, and setup guides live on the platform board —
        open <b>One property</b> or <b>New campaign</b> and choose the client.
      </div>
      {web2 && (
        <details>
          <summary className="op-muted" style={{ cursor: "pointer", marginBottom: 8 }}>
            Show all {web2.totalCount} platform credential slots
          </summary>
        <div className={w.board}>
          {web2.platforms.map((p) => {
            const issue = PLATFORM_ISSUES[p.platform as Web2Platform];
            return (
            <div key={p.platform} className={w.card}>
              <div className={w.cardHead}>
                <span className={w.cardName}>
                  {p.platform}
                  {issue && (
                    <span
                      title={issue}
                      aria-label={`Not connected: ${issue}`}
                      style={{ color: "#e0293a", marginLeft: 4, fontWeight: 700, cursor: "help" }}
                    >
                      *
                    </span>
                  )}
                </span>
                <span>
                  <StatusDot connected={p.connected} draftOnly={p.draftOnly} />
                  <span
                    className={`status-pill ${p.draftOnly ? "mut" : p.connected ? "ok" : "warn"}`}
                    style={{ marginLeft: 6 }}
                  >
                    {p.draftOnly ? "Draft-only" : p.connected ? "Connected" : "Missing"}
                  </span>
                </span>
              </div>
              <div className={w.reason}>{p.reason}</div>
              {!p.draftOnly && (
                <div className={w.meta}>
                  Needs: {p.requiredFields.join(", ") || "a platform token"} · vault{" "}
                  <code>{p.vaultProvider}</code>
                </div>
              )}
              {p.externalNote && <div className={w.external}>{p.externalNote}</div>}
            </div>
            );
          })}
        </div>
        </details>
      )}

      {/* The citation-engine board MOVED (2026-09-02) to the Citations page's
          Automation panel, where the earned-whitelist headline gives it context. It
          lived here under a tab named "API status" on the Web 2.0 page — the one
          screen that could answer "can citations submit?" was inside a different
          module, behind a name that mentioned neither. */}
      <div className="op-muted" style={{ marginTop: 20 }}>
        Citation submission engines now live on{" "}
        <a className="op-url" href="/admin/citations">the Citations page</a> under
        Automation — beside the earned-spec whitelist that actually governs them.
      </div>
    </div>
  );
}
