"use client";

import { useState } from "react";
import { providers, type ProviderId, type Scope } from "@/lib/vault";

export type NewKey = {
  provider: ProviderId;
  label: string;
  value: string;
  scope: Scope;
};

export default function AddKeyForm({ onAdd }: { onAdd: (k: NewKey) => void }) {
  const [provider, setProvider] = useState<ProviderId>("serper");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [scope, setScope] = useState<Scope>("Agency-global");
  const [shown, setShown] = useState(false);

  const valid = label.trim().length > 1 && value.trim().length > 3;

  function submit() {
    if (!valid) return;
    onAdd({ provider, label: label.trim(), value: value.trim(), scope });
    setLabel("");
    setValue("");
    setShown(false);
  }

  return (
    <section className="card kv-add">
      <div className="card-h">
        <div>
          <div className="ct">Add / connect key</div>
          <div className="cs">Store a new credential in the encrypted vault.</div>
        </div>
      </div>

      <div className="fld-row">
        <div className="fld">
          <label htmlFor="kv-provider">Provider</label>
          <select id="kv-provider" value={provider} onChange={(e) => setProvider(e.target.value as ProviderId)}>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="kv-scope">Scope</label>
          <select id="kv-scope" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
            <option value="Agency-global">Agency-global</option>
            <option value="Per-site">Per-site</option>
          </select>
        </div>
      </div>

      <div className="fld">
        <label htmlFor="kv-label">Key label</label>
        <input
          id="kv-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. Serper.dev · Staging"
          spellCheck={false}
          autoComplete="off"
        />
      </div>

      <div className="fld">
        <label htmlFor="kv-value">Key value</label>
        <div className="kv-passwrap">
          <input
            id="kv-value"
            type={shown ? "text" : "password"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste the secret — encrypted on save"
            spellCheck={false}
            autoComplete="new-password"
          />
          <button
            type="button"
            className="kv-pf-btn"
            onClick={() => setShown((s) => !s)}
            title={shown ? "Hide" : "Reveal"}
            aria-label={shown ? "Hide value" : "Reveal value"}
          >
            <span className="material-symbols-rounded">{shown ? "visibility_off" : "visibility"}</span>
          </button>
        </div>
        <div className="fld-hint">
          <span className="material-symbols-rounded" style={{ fontSize: 14, verticalAlign: "-2px" }}>lock</span>{" "}
          Encrypted at rest in Supabase Vault — never stored in plaintext or logs.
        </div>
      </div>

      <button className="primary-btn wide" disabled={!valid} onClick={submit}>
        <span className="material-symbols-rounded">add</span>Add to vault
      </button>
    </section>
  );
}
