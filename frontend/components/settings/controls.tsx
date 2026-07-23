"use client";

import { useState, type ReactNode } from "react";

// ---- Toggle switch --------------------------------------------------------
export function Switch({
  checked, onChange, disabled, label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`switch${checked ? " on" : ""}`}
      onClick={() => !disabled && onChange(!checked)}
    >
      <span className="switch-knob" />
    </button>
  );
}

// ---- Setting row (label/desc on the left, control on the right) -----------
export function SettingRow({
  icon, title, desc, children, danger,
}: {
  icon?: string;
  title: string;
  desc?: string;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <div className={`set-row${danger ? " danger" : ""}`}>
      <div className="set-row-main">
        {icon && <span className={`set-ic material-symbols-rounded${danger ? " danger" : ""}`}>{icon}</span>}
        <div>
          <div className="set-l">{title}</div>
          {desc && <div className="set-d">{desc}</div>}
        </div>
      </div>
      <div className="set-ctl">{children}</div>
    </div>
  );
}

// ---- Section group inside a panel -----------------------------------------
export function SettingGroup({
  title, icon, children,
}: {
  title: string;
  icon: string;
  children: ReactNode;
}) {
  return (
    <div className="set-group">
      <div className="set-group-h">
        <span className="material-symbols-rounded">{icon}</span>
        {title}
      </div>
      <div className="set-list">{children}</div>
    </div>
  );
}

// ---- Password generator ----------------------------------------------------
const CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%&*";
export function generatePassword(len = 14): string {
  let out = "";
  for (let i = 0; i < len; i++) out += CHARS[Math.floor(Math.random() * CHARS.length)];
  return out;
}

// ---- Password field (masked, reveal + copy + optional regenerate) ---------
export function PasswordField({
  value, onChange, canGenerate = true, id,
}: {
  value: string;
  onChange?: (v: string) => void;
  canGenerate?: boolean;
  id?: string;
}) {
  const readOnly = !onChange;
  // Stored credentials (read-only displays) are shown by default across the admin
  // dashboard; an editable password entry you are typing stays masked.
  const [shown, setShown] = useState(readOnly);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* clipboard blocked — no-op */ }
  }

  return (
    <div className="pass-field">
      <input
        id={id}
        type={shown ? "text" : "password"}
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange?.(e.target.value)}
        spellCheck={false}
        autoComplete="new-password"
      />
      <button type="button" className="pf-btn" onClick={() => setShown((s) => !s)} title={shown ? "Hide" : "Reveal"} aria-label={shown ? "Hide password" : "Reveal password"}>
        <span className="material-symbols-rounded">{shown ? "visibility_off" : "visibility"}</span>
      </button>
      <button type="button" className="pf-btn" onClick={copy} title="Copy" aria-label="Copy password">
        <span className="material-symbols-rounded">{copied ? "check" : "content_copy"}</span>
      </button>
      {canGenerate && onChange && (
        <button type="button" className="pf-btn" onClick={() => onChange(generatePassword())} title="Generate strong password" aria-label="Generate strong password">
          <span className="material-symbols-rounded">autorenew</span>
        </button>
      )}
    </div>
  );
}

// ---- Small saved/flash toast ----------------------------------------------
export function SavedFlash({ show, label = "Saved" }: { show: boolean; label?: string }) {
  if (!show) return null;
  return (
    <span className="saved-flash" role="status">
      <span className="material-symbols-rounded">check_circle</span>{label}
    </span>
  );
}
