"use client";

import { useMemo, useState } from "react";
import {
  useActivateSpec,
  useCitationEngineStatus,
  useDeactivateSpec,
  useSpecBoard,
  useSpecFirstLive,
  useVerifySpec,
} from "@/lib/hooks/offpage";
import w from "./Wave4.module.css";

// EARNED AUTOMATION, made visible. The whole citations rebuild pivots on one number —
// how many directories a machine may submit to — and until 2026-09-02 that number
// (zero) appeared NOWHERE while an engine board said "3/5 connected". This panel puts
// the counter first, the specs and their blockers under it, and the engines last,
// framed as what they are: transport.

const DEACTIVATE_REASONS = [
  "drift_detected",
  "stale_unused",
  "submission_failed",
  "operator_disabled",
  "terms_changed",
] as const;

export default function AutomationPanel() {
  const boardQ = useSpecBoard();
  const engineQ = useCitationEngineStatus();
  const verify = useVerifySpec();
  const firstLive = useSpecFirstLive();
  const activate = useActivateSpec();
  const deactivate = useDeactivateSpec();
  const [err, setErr] = useState("");
  const [liveUrlBySpec, setLiveUrlBySpec] = useState<Record<string, string>>({});

  const board = boardQ.data;
  const totalDirectories = useMemo(() => {
    // The denominator is the catalogue; the engine board's headline carries the
    // numerator. We render only what the server states.
    return engineQ.data?.machineSubmittableDirectories ?? board?.active ?? 0;
  }, [engineQ.data, board]);
  void totalDirectories;

  if (boardQ.isError) {
    return (
      <div className={w.step}>
        <div className="op-note crit">
          Couldn&apos;t load the automation board — {(boardQ.error as Error)?.message ?? "retry"}.
        </div>
      </div>
    );
  }
  if (!board) return null;
  // Defensive: a degraded/partial payload must render as "0 earned", never crash.
  const specs = board.specs ?? [];
  const counts = {
    active: board.active ?? 0,
    verifiedNotLive: board.verifiedNotLive ?? 0,
    unverified: board.unverified ?? 0,
    drifted: board.drifted ?? 0,
  };

  return (
    <div className={w.step}>
      <div className={w.stepH}>
        <span className="material-symbols-rounded">smart_toy</span>
        Automation — earned, never assumed
      </div>
      <div className="op-muted" style={{ whiteSpace: "normal", marginBottom: 8 }}>
        <b style={{ fontSize: 18, color: "var(--ink)" }}>
          {counts.active} director{counts.active === 1 ? "y" : "ies"} automated
        </b>{" "}
        · {counts.verifiedNotLive} verified &amp; awaiting a first live listing ·{" "}
        {counts.unverified} drafted · {counts.drifted} drifted. Every directory your team
        finishes by hand can be taught (the queue offers it after each verified
        completion) — this number is the payoff, and it only ever moves on evidence.
      </div>

      {err && <div className="op-note crit">{err}</div>}

      {specs.length > 0 && (
        <div className="tbl-wrap">
          <table className="tbl op-tbl">
            <thead>
              <tr>
                <th>Directory</th>
                <th>State</th>
                <th>Record</th>
                <th>Next step</th>
              </tr>
            </thead>
            <tbody>
              {specs.map((sp) => (
                <tr key={sp.id}>
                  <td className="op-strong">{sp.directoryName}</td>
                  <td>
                    {sp.active ? (
                      <span className="status-pill ok">active</span>
                    ) : sp.drifted ? (
                      <span className="status-pill warn">drifted</span>
                    ) : sp.verified && sp.hasFirstLiveUrl ? (
                      <span className="status-pill info">ready to activate</span>
                    ) : sp.verified ? (
                      <span className="status-pill info">verified</span>
                    ) : (
                      <span className="status-pill mut">draft</span>
                    )}
                  </td>
                  <td className="op-muted" style={{ whiteSpace: "normal", maxWidth: 320 }}>
                    {sp.successCount + sp.failureCount > 0 &&
                      `${sp.successCount} ok / ${sp.failureCount} failed · `}
                    {sp.deactivatedReason && `deactivated: ${sp.deactivatedReason} · `}
                    {sp.blocking.length > 0 ? sp.blocking.join(" · ") : sp.active ? "earning" : ""}
                  </td>
                  <td>
                    {sp.active ? (
                      <select
                        className="op-input"
                        defaultValue=""
                        onChange={(e) => {
                          if (!e.target.value) return;
                          setErr("");
                          deactivate.mutate(
                            { specId: sp.id, reason: e.target.value },
                            { onError: (x) => setErr(`Couldn't deactivate — ${(x as Error).message}`) },
                          );
                          e.target.value = "";
                        }}
                      >
                        <option value="">deactivate…</option>
                        {DEACTIVATE_REASONS.map((r) => (
                          <option key={r} value={r}>{r.replace(/_/g, " ")}</option>
                        ))}
                      </select>
                    ) : !sp.verified ? (
                      <button
                        className="ghostbtn"
                        disabled={verify.isPending}
                        title="Write-once and dated: press only having compared each selector with the live form."
                        onClick={() => {
                          setErr("");
                          verify.mutate(
                            { specId: sp.id },
                            { onError: (x) => setErr(`Verification refused — ${(x as Error).message}`) },
                          );
                        }}
                      >
                        verify (I checked the form)
                      </button>
                    ) : !sp.hasFirstLiveUrl ? (
                      <span style={{ display: "inline-flex", gap: 6 }}>
                        <input
                          className="op-input"
                          style={{ width: 200 }}
                          placeholder="first live listing URL"
                          value={liveUrlBySpec[sp.id] ?? ""}
                          onChange={(e) =>
                            setLiveUrlBySpec((m) => ({ ...m, [sp.id]: e.target.value }))
                          }
                        />
                        <button
                          className="ghostbtn"
                          disabled={!liveUrlBySpec[sp.id]?.trim() || firstLive.isPending}
                          onClick={() => {
                            setErr("");
                            firstLive.mutate(
                              { specId: sp.id, liveUrl: liveUrlBySpec[sp.id].trim() },
                              { onError: (x) => setErr(`Refused — ${(x as Error).message}`) },
                            );
                          }}
                        >
                          record
                        </button>
                      </span>
                    ) : (
                      <button
                        className="primary-btn"
                        disabled={activate.isPending}
                        onClick={() => {
                          setErr("");
                          activate.mutate(sp.id, {
                            onError: (x) => setErr(`Activation refused — ${(x as Error).message}`),
                          });
                        }}
                      >
                        activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {engineQ.data && Array.isArray(engineQ.data.engines) && (
        <details style={{ marginTop: 10 }}>
          <summary className="op-muted" style={{ cursor: "pointer" }}>
            Submission engines ({engineQ.data.connectedCount ?? 0}/{engineQ.data.totalCount ?? 0} configured)
            — engines are transport; the whitelist above is the constraint
          </summary>
          <div style={{ marginTop: 8 }}>
            {engineQ.data.engines.map((e) => (
              <div key={e.key} style={{ display: "flex", gap: 8, alignItems: "baseline", marginTop: 6 }}>
                <span className={`status-pill ${e.connected ? "ok" : "mut"}`}>
                  {e.connected ? "ready" : "off"}
                </span>
                <span className="op-strong">{e.label}</span>
                <span className="op-muted" style={{ whiteSpace: "normal", fontSize: 12 }}>{e.reason}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
