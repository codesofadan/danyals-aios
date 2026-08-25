"use client";

import { useState } from "react";
import { copyText } from "@/lib/clipboard";
import { FALLBACK_PROVIDER, providerById, STATUS_META, type VaultKey } from "@/lib/vault";
import { useRevealVaultKey, useRotateVaultKey } from "@/lib/hooks/vault";
import ReadMore from "@/components/ui/ReadMore";

type Props = {
  keys: VaultKey[];
};

export default function VaultTable({ keys }: Props) {
  // The list never carries a secret (reveal is a separate owner-only call). We
  // fetch a plaintext value ON DEMAND and hold it ONLY in transient local state
  // keyed by id — never in the Query cache, never persisted. A row is "revealed"
  // iff its id is present in `secrets`.
  const reveal = useRevealVaultKey();
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The table has always shown a "Last rotated" column. Nothing could rotate: the
  // hook existed with zero call sites, so the column reported a date for an action
  // the product did not offer. `rotatingId` is the row whose replacement value is
  // being entered.
  const [rotatingId, setRotatingId] = useState<string | null>(null);
  const rotate = useRotateVaultKey();

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
      await copyText(value);
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
        <div className="panel-hint" role="alert" style={{ padding: "0 4px 8px", color: "var(--warn, #A96913)" }}>
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
            <ReadMore
              items={keys}
              initialCount={10}
              getKey={(k) => k.id}
              tableColSpan={7}
              renderItem={(k) => {
                // The backend's `provider` field is unvalidated `str` — fall back rather
                // than crash on any value outside the known set.
                const p = providerById[k.provider] ?? FALLBACK_PROVIDER;
                const st = STATUS_META[k.status];
                const show = secrets[k.id] !== undefined;
                const loading = pendingId === k.id;
                return (
                <>
                <tr>
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
                      <button
                        className={`kv-iconbtn${rotatingId === k.id ? " on" : ""}`}
                        onClick={() => setRotatingId(rotatingId === k.id ? null : k.id)}
                        title="Rotate this key"
                        aria-label={`Rotate ${k.label}`}
                        aria-expanded={rotatingId === k.id}
                      >
                        <span className="material-symbols-rounded">autorenew</span>
                      </button>
                    </div>
                  </td>
                </tr>
                {rotatingId === k.id && (
                  <tr className="kv-rotate-row">
                    <td colSpan={7}>
                      <RotateForm
                        label={k.label}
                        busy={rotate.isPending}
                        error={rotate.error instanceof Error ? rotate.error.message : null}
                        onCancel={() => setRotatingId(null)}
                        onRotate={(secret) =>
                          rotate.mutate(
                            { id: k.id, secret },
                            {
                              onSuccess: () => {
                                setRotatingId(null);
                                // The old plaintext must not linger on screen under a
                                // value that is no longer the one in the vault.
                                hide(k.id);
                              },
                            },
                          )
                        }
                      />
                    </td>
                  </tr>
                )}
                </>
                );
              }}
            />
          </tbody>
        </table>
      </div>
    </div>
  );
}


// Replacing a key's value. Deliberately a typed-in secret rather than a one-click
// "regenerate": AIOS does not mint provider credentials, it stores them — the new
// value comes from the provider's own console, and a button implying otherwise would
// promise something no endpoint can do.
function RotateForm({
  label, busy, error, onCancel, onRotate,
}: {
  label: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onRotate: (secret: string) => void;
}) {
  const [secret, setSecret] = useState("");
  const [shown, setShown] = useState(false);

  return (
    <div className="kv-rotate">
      <div className="kv-rotate-h">
        <span className="material-symbols-rounded">autorenew</span>
        Rotate <b>{label}</b> — paste the new value from the provider. The old one is
        replaced immediately and cannot be recovered.
      </div>
      <div className="kv-rotate-row-in">
        <input
          type={shown ? "text" : "password"}
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder="New secret value"
          aria-label={`New value for ${label}`}
          autoComplete="off"
        />
        <button type="button" className="kv-iconbtn" onClick={() => setShown((v) => !v)}
          title={shown ? "Hide" : "Show"} aria-label={shown ? "Hide value" : "Show value"}>
          <span className="material-symbols-rounded">{shown ? "visibility_off" : "visibility"}</span>
        </button>
        <button type="button" className="ghostbtn" onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className="primary-btn sm"
          disabled={busy || secret.trim().length === 0}
          onClick={() => onRotate(secret.trim())}
        >
          {busy ? "Rotating…" : "Rotate key"}
        </button>
      </div>
      {error && <div className="kv-rotate-err" role="alert">Couldn&apos;t rotate — {error}</div>}
    </div>
  );
}
