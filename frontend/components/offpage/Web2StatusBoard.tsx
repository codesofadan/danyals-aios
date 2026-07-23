"use client";

// Wave 4: the Web 2.0 + citation-engine API STATUS BOARD. Each platform / engine reads
// CONNECTED (a real vault credential or a configured key is present) vs MISSING, with the
// exact reason and an honest note that even a connected provider can be refused by the
// EXTERNAL API. Reads /citation-builder/web2-status + /engine-status; degrades cleanly.

import { useCitationEngineStatus, useWeb2Status } from "@/lib/hooks/offpage";
import w from "./Wave4.module.css";

function StatusDot({ connected, draftOnly }: { connected: boolean; draftOnly?: boolean }) {
  const cls = draftOnly ? w.dotMut : connected ? w.dotOn : w.dotOff;
  return <span className={`${w.dot} ${cls}`} aria-hidden />;
}

export default function Web2StatusBoard() {
  const web2Q = useWeb2Status();
  const engineQ = useCitationEngineStatus();
  const web2 = web2Q.data;
  const engines = engineQ.data;

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
      {web2 && (
        <div className={w.board}>
          {web2.platforms.map((p) => (
            <div key={p.platform} className={w.card}>
              <div className={w.cardHead}>
                <span className={w.cardName}>{p.platform}</span>
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
          ))}
        </div>
      )}

      {/* Citation submission engines */}
      <div className={w.rollup} style={{ marginTop: 20 }}>
        <span><b>Citation engines</b> - direct APIs, the Apify fallback, the solver &amp; bot</span>
        {engines && (
          <span><b>{engines.connectedCount}</b> connected · {engines.totalCount} engines</span>
        )}
      </div>

      {engineQ.isLoading && <div className="op-muted">Loading engine status…</div>}
      {engineQ.isError && (
        <div className="op-muted">
          Couldn&apos;t load engine status - {(engineQ.error as Error)?.message ?? "try again"}.
        </div>
      )}
      {engines && (
        <div className={w.board}>
          {engines.engines.map((e) => (
            <div key={e.key} className={w.card}>
              <div className={w.cardHead}>
                <span className={w.cardName}>{e.label}</span>
                <span>
                  <StatusDot connected={e.connected} />
                  <span className={`status-pill ${e.connected ? "ok" : "warn"}`} style={{ marginLeft: 6 }}>
                    {e.connected ? "Connected" : "Missing"}
                  </span>
                </span>
              </div>
              <div className={w.reason}>{e.reason}</div>
              {e.requiredConfig.length > 0 && (
                <div className={w.meta}>Needs: {e.requiredConfig.join(", ")}</div>
              )}
              {e.externalNote && <div className={w.external}>{e.externalNote}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
