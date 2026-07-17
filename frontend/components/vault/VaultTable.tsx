"use client";

import { useState } from "react";
import { providerById, STATUS_META, type VaultKey } from "@/lib/vault";
import { useRevealVaultKey } from "@/lib/hooks/vault";

type Props = {
  keys: VaultKey[];
  onRotate: (id: string) => void;
};

export default function VaultTable({ keys, onRotate }: Props) {
  // The list never carries a secret (reveal is a separate owner-only call). We
  // fetch a plaintext value ON DEMAND and hold it ONLY in transient local state
  // keyed by id — never in the Query cache, never persisted. A row is "revealed"
  // iff its id is present in `secrets`.
  const reveal = useRevealVaultKey();
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const anyRevealed = Object.keys(secrets).length > 0;

  function hide(id: string) {
    setSecrets((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  function toggle(k: VaultKey) {
    if (secrets[k.id] !== undefined) {
      hide(k.id);
      return;
    }
    setPendingId(k.id);
    setError(null);
    reveal.mutate(k.id, {
      onSuccess: (res) => setSecrets((prev) => ({ ...prev, [k.id]: res.secret })),
      onError: (e) => setError((e as Error)?.message ?? "Couldn't reveal that key."),
      onSettled: () => setPendingId(null),
    });
  }

  async function copy(k: VaultKey) {
    const value = secrets[k.id];
    if (value === undefined) return; // can only copy a secret that's been revealed
    try {
      await navigator.clipboard.writeText(value);
      setCopied(k.id);
      setTimeout(() => setCopied((c) => (c === k.id ? null : c)), 1400);
    } catch {
      /* clipboard blocked — no-op */
    }
  }

  return (
    <div className="kv-table-panel">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">vpn_key</span>
          {keys.length} key{keys.length === 1 ? "" : "s"} · masked by default · reveal is local to this session
        </div>
        <button
          className="ghostbtn"
          disabled={!anyRevealed}
          onClick={() => setSecrets({})}
          title="Hide every revealed key"
        >
          <span className="material-symbols-rounded">visibility_off</span>Mask all
        </button>
      </div>

      {error && (
        <div className="panel-hint" role="alert" style={{ padding: "0 4px 8px", color: "var(--warn, #d9822b)" }}>
          <span className="material-symbols-rounded">error</span>{error}
        </div>
      )}

      <div className="tbl-wrap">
        <table className="tbl kv-tbl">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Key label</th>
              <th>Value</th>
              <th>Scope</th>
              <th>Status</th>
              <th>Last rotated</th>
              <th className="num">Actions</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const p = providerById[k.provider];
              const st = STATUS_META[k.status];
              const show = secrets[k.id] !== undefined;
              const loading = pendingId === k.id;
              return (
                <tr key={k.id}>
                  <td>
                    <div className="kv-prov">
                      <span className="kv-prov-ic" style={{ background: `${p.c}22`, color: p.c }}>
                        <span className="material-symbols-rounded">{p.icon}</span>
                      </span>
                      <div>
                        <div className="kv-prov-n">{p.name}</div>
                        <div className="kv-prov-c">{p.category}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="kv-label">{k.label}</div>
                    {k.site && <div className="kv-sub">{k.site}</div>}
                  </td>
                  <td>
                    <code className={`kv-secret${show ? " shown" : ""}`}>
                      {show ? secrets[k.id] : k.masked}
                    </code>
                  </td>
                  <td>
                    <span className={`kv-scope${k.scope === "Per-site" ? " site" : ""}`}>
                      <span className="material-symbols-rounded">
                        {k.scope === "Per-site" ? "public_off" : "public"}
                      </span>
                      {k.scope}
                    </span>
                  </td>
                  <td>
                    <span className={`kv-st ${st.cls}`}>{st.label}</span>
                  </td>
                  <td>
                    <span className="kv-rot">{k.rotated}</span>
                  </td>
                  <td className="num">
                    <div className="kv-actions">
                      <button
                        className={`kv-iconbtn${show ? " on" : ""}`}
                        onClick={() => toggle(k)}
                        disabled={loading}
                        title={show ? "Hide value" : "Reveal value"}
                        aria-label={show ? "Hide value" : "Reveal value"}
                      >
                        <span className={`material-symbols-rounded${loading ? " spin" : ""}`}>
                          {loading ? "progress_activity" : show ? "visibility_off" : "visibility"}
                        </span>
                      </button>
                      <button
                        className="kv-iconbtn"
                        onClick={() => onRotate(k.id)}
                        title="Rotate key"
                        aria-label="Rotate key"
                      >
                        <span className="material-symbols-rounded">cached</span>
                      </button>
                      <button
                        className={`kv-iconbtn${copied === k.id ? " ok" : ""}`}
                        onClick={() => copy(k)}
                        disabled={!show}
                        title="Copy value"
                        aria-label="Copy value"
                      >
                        <span className="material-symbols-rounded">
                          {copied === k.id ? "check" : "content_copy"}
                        </span>
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
