"use client";

import { useState } from "react";
import { clientDirectory, TIER_COLOR, type ClientRecord, type SubStatus } from "@/lib/data";

type Mode = "info" | "portal";

const STATUS_META: Record<SubStatus, { label: string; cls: string }> = {
  active: { label: "Active", cls: "ok" },
  trial: { label: "Trial", cls: "info" },
  past_due: { label: "Past due", cls: "warn" },
  paused: { label: "Paused", cls: "mut" },
};

function ContactCell({ c }: { c: ClientRecord["contact"] }) {
  return (
    <div className="cd-contact">
      <span className="av" style={{ background: c.c }}>{c.init}</span>
      <div className="cd-cmeta">
        <div className="cd-cname">{c.name}</div>
        <div className="cd-crole">{c.role}</div>
      </div>
    </div>
  );
}

function PassCell({ pass }: { pass: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="pass-cell">
      <code className="pass-val">{shown ? pass : "•".repeat(pass.length)}</code>
      <button
        className="pass-eye"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide admin password" : "Reveal admin password"}
        title={shown ? "Hide" : "Reveal"}
      >
        <span className="material-symbols-rounded">{shown ? "visibility_off" : "visibility"}</span>
      </button>
    </div>
  );
}

export default function ClientDirectory() {
  const [mode, setMode] = useState<Mode>("info");

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client Directory</div>
          <div className="cs">
            {mode === "info"
              ? "Account details, primary contact & subscription"
              : "Portal logins & admin credentials · handle with care"}
          </div>
        </div>
        <div className="tools">
          <div className="seg" role="tablist" aria-label="Directory view">
            <button
              role="tab"
              aria-selected={mode === "info"}
              className={mode === "info" ? "on" : undefined}
              onClick={() => setMode("info")}
            >
              Client Info
            </button>
            <button
              role="tab"
              aria-selected={mode === "portal"}
              className={mode === "portal" ? "on" : undefined}
              onClick={() => setMode("portal")}
            >
              Portal Access
            </button>
          </div>
        </div>
      </div>

      {mode === "portal" && (
        <div className="sec-note">
          <span className="material-symbols-rounded">lock</span>
          Admin passes are masked by default — reveal only when needed. Actions are recorded in the activity log.
        </div>
      )}

      <div className="cd-wrap">
        {mode === "info" ? (
          <table className="cd-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Primary contact</th>
                <th>Subscription</th>
                <th className="num">Sites</th>
                <th className="num">MRR</th>
              </tr>
            </thead>
            <tbody>
              {clientDirectory.map((c) => {
                const sm = STATUS_META[c.status];
                return (
                  <tr key={c.id}>
                    <td>
                      <div className="cd-client">
                        <div className="cd-name">{c.cn}</div>
                        <div className="cd-meta">{c.industry} · since {c.since}</div>
                      </div>
                    </td>
                    <td><ContactCell c={c.contact} /></td>
                    <td>
                      <div className="cd-sub">
                        <span className="tier-chip sm" style={{ color: TIER_COLOR[c.tier], borderColor: TIER_COLOR[c.tier] }}>{c.tier}</span>
                        <span className={`status-pill ${sm.cls}`}>{sm.label}</span>
                        <span className="cd-renew">Renews {c.renews}</span>
                      </div>
                    </td>
                    <td className="num">{c.sites}</td>
                    <td className="num mrr">{c.mrr ? `$${c.mrr.toLocaleString()}` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <table className="cd-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Admin login</th>
                <th>Admin pass</th>
                <th className="num">Seats</th>
                <th>2FA</th>
                <th>Last login</th>
              </tr>
            </thead>
            <tbody>
              {clientDirectory.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="cd-client">
                      <div className="cd-name">{c.cn}</div>
                      <div className="cd-meta">{c.contact.name}</div>
                    </div>
                  </td>
                  <td><code className="login-val">{c.portal.admin}</code></td>
                  <td><PassCell pass={c.portal.pass} /></td>
                  <td className="num">{c.portal.seats}</td>
                  <td>
                    {c.portal.twoFA ? (
                      <span className="fa-badge on"><span className="material-symbols-rounded">verified_user</span>On</span>
                    ) : (
                      <span className="fa-badge off"><span className="material-symbols-rounded">gpp_maybe</span>Off</span>
                    )}
                  </td>
                  <td className="last">{c.portal.lastLogin}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="cd-foot">
        <span>{clientDirectory.length} featured accounts</span>
        <span className="cd-foot-hint">Toggle to {mode === "info" ? "Portal Access" : "Client Info"} for {mode === "info" ? "admin credentials" : "account details"}</span>
      </div>
    </section>
  );
}
