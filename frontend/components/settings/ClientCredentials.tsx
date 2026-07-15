"use client";

import { useState } from "react";
import { useStore } from "@/lib/store";
import { Switch, PasswordField } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;
type Cred = { admin: string; pass: string; twoFA: boolean };

export default function ClientCredentials({ onLog }: { onLog: LogFn }) {
  const { clients } = useStore();
  const [creds, setCreds] = useState<Record<string, Cred>>(() =>
    Object.fromEntries(clients.map((c) => [c.id, { admin: c.portal.admin, pass: c.portal.pass, twoFA: c.portal.twoFA }]))
  );
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [savedId, setSavedId] = useState<string | null>(null);

  function edit(id: string, patch: Partial<Cred>) {
    setCreds((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
    setDirty((prev) => ({ ...prev, [id]: true }));
  }

  function save(id: string, name: string) {
    setDirty((prev) => ({ ...prev, [id]: false }));
    setSavedId(id);
    setTimeout(() => setSavedId((s) => (s === id ? null : s)), 1600);
    onLog("updated portal credentials for", name, "Client access");
  }

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
          const cr = creds[c.id];
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
                  <input id={`u-${c.id}`} value={cr.admin} onChange={(e) => edit(c.id, { admin: e.target.value })} spellCheck={false} autoComplete="off" />
                </div>
                <div className="fld">
                  <label htmlFor={`p-${c.id}`}>Admin password</label>
                  <PasswordField id={`p-${c.id}`} value={cr.pass} onChange={(v) => edit(c.id, { pass: v })} />
                </div>
                <div className="cc-2fa">
                  <span className="cc-2fa-l">Require 2FA</span>
                  <Switch checked={cr.twoFA} onChange={(v) => edit(c.id, { twoFA: v })} label={`Require 2FA for ${c.cn}`} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
