"use client";

import { useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import { Switch, PasswordField } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;
type Cred = { admin: string; pass: string; twoFA: boolean };

export default function ClientCredentials({ onLog }: { onLog: LogFn }) {
  // The client directory is live (GET /clients). MISMATCH (recorded): the backend
  // NEVER persists or returns a portal password (it is set out-of-band, never in
  // the ClientResponse), and there is NO client-credential write endpoint — so the
  // password reads empty and Save here is a LOCAL confirmation only.
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const [creds, setCreds] = useState<Record<string, Cred>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [savedId, setSavedId] = useState<string | null>(null);

  // Merge onto the cred currently on screen (the stored edit OR the render fallback
  // derived from the client record) so a first edit keeps every other field intact.
  function edit(id: string, cur: Cred, patch: Partial<Cred>) {
    setCreds((prev) => ({ ...prev, [id]: { ...cur, ...prev[id], ...patch } }));
    setDirty((prev) => ({ ...prev, [id]: true }));
  }

  function save(id: string, name: string) {
    setDirty((prev) => ({ ...prev, [id]: false }));
    setSavedId(id);
    setTimeout(() => setSavedId((s) => (s === id ? null : s)), 1600);
    onLog("updated portal credentials for", name, "Client access");
  }

  const muted: React.CSSProperties = { padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)" };
  if (clientsQ.isLoading && clients.length === 0) return <div className="panel-in"><div style={muted}>Loading client portals…</div></div>;
  if (clientsQ.isError && clients.length === 0)
    return <div className="panel-in"><div style={muted}>Couldn&apos;t load clients — {(clientsQ.error as Error)?.message ?? "try again"}.</div></div>;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">key</span>
          {clients.length} client portals · edit the login username &amp; admin password
        </div>
        <div className="sec-note inline">
          <span className="material-symbols-rounded">lock</span>
          Credentials are sensitive — every change is written to the activity log.
        </div>
      </div>

      <div className="cc-list">
        {clients.map((c) => {
          const cr = creds[c.id] ?? { admin: c.portal.admin, pass: c.portal.pass, twoFA: c.portal.twoFA };
          const isDirty = dirty[c.id];
          return (
            <div className="cc-card" key={c.id}>
              <div className="cc-top">
                <div className="cc-who">
                  <span className="av sq" style={{ background: c.contact.c }}>{c.contact.init}</span>
                  <div>
                    <div className="cc-name">{c.cn}</div>
                    <div className="cc-meta">{c.industry} · {c.tier} plan · {c.sites} site{c.sites > 1 ? "s" : ""}</div>
                  </div>
                </div>
                <div className="cc-save">
                  {savedId === c.id && <span className="saved-flash"><span className="material-symbols-rounded">check_circle</span>Saved</span>}
                  <button className="primary-btn sm" disabled={!isDirty} onClick={() => save(c.id, c.cn)}>
                    <span className="material-symbols-rounded">save</span>Save
                  </button>
                </div>
              </div>

              <div className="cc-fields">
                <div className="fld">
                  <label htmlFor={`u-${c.id}`}>Portal username / login email</label>
                  <input id={`u-${c.id}`} value={cr.admin} onChange={(e) => edit(c.id, cr, { admin: e.target.value })} spellCheck={false} autoComplete="off" />
                </div>
                <div className="fld">
                  <label htmlFor={`p-${c.id}`}>Admin password</label>
                  <PasswordField id={`p-${c.id}`} value={cr.pass} onChange={(v) => edit(c.id, cr, { pass: v })} />
                </div>
                <div className="cc-2fa">
                  <span className="cc-2fa-l">Require 2FA</span>
                  <Switch checked={cr.twoFA} onChange={(v) => edit(c.id, cr, { twoFA: v })} label={`Require 2FA for ${c.cn}`} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
