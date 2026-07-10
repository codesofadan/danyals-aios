"use client";

import { useState } from "react";
import { providerById, STATUS_META, type VaultKey } from "@/lib/vault";

type Props = {
  keys: VaultKey[];
  onRotate: (id: string) => void;
};

export default function VaultTable({ keys, onRotate }: Props) {
  // Reveal + copy state are client-side only; nothing leaves the browser.
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const anyRevealed = Object.values(revealed).some(Boolean);

  const toggle = (id: string) =>
    setRevealed((prev) => ({ ...prev, [id]: !prev[id] }));

  async function copy(k: VaultKey) {
    try {
      await navigator.clipboard.writeText(k.secret);
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
          onClick={() => setRevealed({})}
          title="Hide every revealed key"
        >
          <span className="material-symbols-rounded">visibility_off</span>Mask all
        </button>
      </div>

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
              const show = !!revealed[k.id];
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
                      {show ? k.secret : k.masked}
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
                        onClick={() => toggle(k.id)}
                        title={show ? "Hide value" : "Reveal value"}
                        aria-label={show ? "Hide value" : "Reveal value"}
                      >
                        <span className="material-symbols-rounded">
                          {show ? "visibility_off" : "visibility"}
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
