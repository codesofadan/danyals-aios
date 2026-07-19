"use client";

import { useState } from "react";
import type { VaultKey } from "@/lib/vault";

// A short, sufficiently-random secret for a "Generate" convenience button — the
// backend re-encrypts whatever it's handed, so this is display-side only.
function genSecret(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/[+/=]/g, "").slice(0, 32);
}

export default function RotateKeyModal({
  keyRow,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  keyRow: VaultKey;
  busy: boolean;
  error?: string | null;
  onClose: () => void;
  onConfirm: (secret: string) => void;
}) {
  const [value, setValue] = useState("");
  const [shown, setShown] = useState(false);
  const valid = value.trim().length >= 4;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" role="dialog" aria-modal="true" aria-label="Rotate key" onClick={(e) => e.stopPropagation()}>
        <div className="bk-modal-head">
          <div>
            <div className="ey">Encrypted vault</div>
            <h2>Rotate {keyRow.label}</h2>
          </div>
          <button className="modal-x" onClick={onClose} aria-label="Cancel">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        <div className="fld">
          <label htmlFor="kv-rotate-value">New secret</label>
          <div className="kv-passwrap">
            <input
              id="kv-rotate-value"
              type={shown ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Paste the replacement secret"
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
          <button type="button" className="ghostbtn" style={{ marginTop: 8 }} onClick={() => setValue(genSecret())}>
            <span className="material-symbols-rounded">casino</span>Generate
          </button>
        </div>

        {error && (
          <div className="login-error" role="alert">
            <span className="material-symbols-rounded">error</span>{error}
          </div>
        )}

        <div className="bk-modal-foot">
          <button className="bk-btn2" onClick={onClose}>Cancel</button>
          <button className="bk-btn2 danger" disabled={!valid || busy} onClick={() => onConfirm(value.trim())}>
            <span className="material-symbols-rounded">cached</span>
            {busy ? "Rotating…" : "Rotate key"}
          </button>
        </div>
      </div>
    </div>
  );
}
