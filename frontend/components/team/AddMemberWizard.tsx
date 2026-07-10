"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  accessFeatures, roleTemplates, GROUP_COLOR,
  type AccessFeature,
} from "@/lib/data";
import type { NewMember } from "./TeamRoster";

// 6 shard vectors (hexagon burst) — reused by every bubble pop.
const SHARDS = [
  { x: 46, y: 0 }, { x: 23, y: 40 }, { x: -23, y: 40 },
  { x: -46, y: 0 }, { x: -23, y: -40 }, { x: 23, y: -40 },
];

const ADJ = ["Solar", "Rapid", "Cobalt", "Lunar", "Amber", "Quartz", "Nimbus", "Vivid", "Onyx", "Cedar", "Zephyr", "Crimson"];
const NOUN = ["Falcon", "Harbor", "Cipher", "Meadow", "Quasar", "Lynx", "Beacon", "Vertex", "Willow", "Ember", "Comet", "Delta"];
const SYM = "!@#$%&*?";

function pick<T>(arr: T[]): T { return arr[Math.floor(Math.random() * arr.length)]; }

function genPassword(): string {
  const digits = String(10 + Math.floor(Math.random() * 90));
  const sym = SYM[Math.floor(Math.random() * SYM.length)];
  return `${pick(ADJ)}-${pick(NOUN)}${digits}${sym}`;
}

function genUsername(name: string): string {
  const parts = name.trim().toLowerCase().replace(/[^a-z\s]/g, "").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "new.member";
  if (parts.length === 1) return `${parts[0]}.aios`;
  return `${parts[0]}.${parts[parts.length - 1]}`;
}

type Step = 1 | 2 | 3;
const STEP_LABELS = ["Permissions", "Details", "Credentials"];

export default function AddMemberWizard({ onClose, onAdd }: { onClose: () => void; onAdd: (m: NewMember) => void }) {
  const [step, setStep] = useState<Step>(1);
  const [granted, setGranted] = useState<Set<string>>(new Set());
  const [template, setTemplate] = useState<string>(""); // "" = custom
  const [popping, setPopping] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      timers.current.forEach(clearTimeout);
    };
  }, [onClose]);

  const reduce = typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function playPop(keys: string[]) {
    if (reduce || keys.length === 0) return;
    setPopping((prev) => { const n = new Set(prev); keys.forEach((k) => n.add(k)); return n; });
    const t = setTimeout(() => {
      setPopping((prev) => { const n = new Set(prev); keys.forEach((k) => n.delete(k)); return n; });
    }, 560);
    timers.current.push(t);
  }

  function toggleBubble(key: string) {
    setGranted((prev) => {
      const n = new Set(prev);
      if (n.has(key)) { n.delete(key); } else { n.add(key); playPop([key]); }
      return n;
    });
  }

  function applyTemplate(key: string) {
    setTemplate(key);
    const tpl = roleTemplates.find((t) => t.key === key);
    const next = new Set(tpl ? tpl.grants : []);
    // Pop only the bubbles that are newly switched on (off → on).
    const newlyOn = [...next].filter((k) => !granted.has(k));
    setGranted(next);
    playPop(newlyOn);
  }

  const tpl = roleTemplates.find((t) => t.key === template);
  const customized = useMemo(() => {
    if (!tpl) return false;
    if (tpl.grants.length !== granted.size) return true;
    return tpl.grants.some((k) => !granted.has(k));
  }, [tpl, granted]);

  const emailValid = /\S+@\S+\.\S+/.test(email);
  const nameValid = name.trim().length > 1;

  function goCredentials() {
    if (!nameValid || !emailValid) return;
    setUsername(genUsername(name));
    setPassword(genPassword());
    setStep(3);
  }

  function copy(kind: string, value: string) {
    navigator.clipboard?.writeText(value).then(() => {
      setCopied(kind);
      const t = setTimeout(() => setCopied(null), 1400);
      timers.current.push(t);
    }).catch(() => {});
  }

  function finish() {
    onAdd({
      name: name.trim(),
      email: email.trim(),
      title: tpl ? tpl.label : "Team Member",
      role: tpl ? tpl.role : "Specialist",
      color: tpl ? tpl.color : GROUP_COLOR.Analytics,
      template: tpl ? tpl.label : "Custom",
      features: [...granted],
    });
  }

  return (
    <div className="tw">
      <div className="modal-scrim" onClick={onClose}>
        <div className="modal wide wiz" onClick={(e) => e.stopPropagation()}>
          <div className="modal-h">
            <div>
              <div className="modal-t">Add team member</div>
              <div className="modal-s">
                {step === 1 && "Grant access by popping the features this person needs."}
                {step === 2 && "Who is joining the team?"}
                {step === 3 && "Share these one-time credentials to finish the invite."}
              </div>
            </div>
            <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
              <span className="material-symbols-rounded">close</span>
            </button>
          </div>

          {/* step indicator */}
          <div className="wiz-steps">
            {STEP_LABELS.map((label, i) => {
              const n = (i + 1) as Step;
              const state = n < step ? "done" : n === step ? "on" : "";
              return (
                <div className={`wiz-step ${state}`} key={label}>
                  <span className="wiz-dot">{n < step ? <span className="material-symbols-rounded">check</span> : n}</span>
                  <span className="wiz-slabel">{label}</span>
                </div>
              );
            })}
          </div>

          {/* STEP 1 — permissions */}
          {step === 1 && (
            <div className="wiz-body">
              <div className="tpl-row">
                <label className="tpl-label">Role template</label>
                <div className="tpl-select">
                  <span className="material-symbols-rounded tpl-ic">{tpl ? tpl.icon : "category"}</span>
                  <select value={template} onChange={(e) => applyTemplate(e.target.value)} aria-label="Role template">
                    <option value="">Custom — start from scratch</option>
                    {roleTemplates.map((t) => (
                      <option key={t.key} value={t.key}>{t.label} — {t.tagline}</option>
                    ))}
                  </select>
                </div>
                <div className="grant-count">
                  <b>{granted.size}</b> / {accessFeatures.length} granted
                  {tpl && <span className={`tpl-tag${customized ? " cust" : ""}`}>{customized ? `${tpl.label} · customized` : tpl.label}</span>}
                </div>
                {granted.size > 0 && (
                  <button className="clear-btn" onClick={() => { setGranted(new Set()); setTemplate(""); }}>
                    <span className="material-symbols-rounded">restart_alt</span>Clear
                  </button>
                )}
              </div>

              <div className="bubble-field">
                {accessFeatures.map((f, i) => (
                  <Bubble
                    key={f.key}
                    feature={f}
                    index={i}
                    granted={granted.has(f.key)}
                    popping={popping.has(f.key)}
                    onClick={() => toggleBubble(f.key)}
                  />
                ))}
              </div>

              <div className="bubble-legend">
                <span><span className="lg-swatch open" /> Not granted — tap to pop</span>
                <span><span className="lg-swatch popped" /> Popped &amp; granted</span>
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                <button type="button" className="primary-btn" onClick={() => setStep(2)}>
                  Next<span className="material-symbols-rounded">arrow_forward</span>
                </button>
              </div>
            </div>
          )}

          {/* STEP 2 — identity */}
          {step === 2 && (
            <form className="wiz-body" onSubmit={(e) => { e.preventDefault(); goCredentials(); }}>
              <div className="fld">
                <label>Full name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ali Hassan" autoFocus />
              </div>
              <div className="fld">
                <label>Work email</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ali@xegents.ai" />
              </div>
              <div className="wiz-recap">
                <span className="material-symbols-rounded">{tpl ? tpl.icon : "category"}</span>
                <div>
                  <div className="recap-t">{tpl ? tpl.label : "Custom access"}{customized ? " · customized" : ""}</div>
                  <div className="recap-s">{granted.size} of {accessFeatures.length} features granted</div>
                </div>
                <button type="button" className="recap-edit" onClick={() => setStep(1)}>Edit</button>
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={() => setStep(1)}>
                  <span className="material-symbols-rounded">arrow_back</span>Back
                </button>
                <button type="submit" className="primary-btn" disabled={!nameValid || !emailValid}>
                  Next<span className="material-symbols-rounded">arrow_forward</span>
                </button>
              </div>
            </form>
          )}

          {/* STEP 3 — credentials */}
          {step === 3 && (
            <div className="wiz-body">
              <div className="cred-hero">
                <span className="av" style={{ background: tpl ? tpl.color : GROUP_COLOR.Analytics }}>
                  {name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                </span>
                <div>
                  <div className="cred-name">{name}</div>
                  <div className="cred-role">{tpl ? tpl.label : "Custom access"} · {granted.size} features</div>
                </div>
                <span className="cred-ok"><span className="material-symbols-rounded">verified</span>Ready</span>
              </div>

              <CredRow label="Username" value={username} icon="alternate_email" copied={copied === "user"} onCopy={() => copy("user", username)} />
              <CredRow label="Temporary password" value={password} icon="password" mono copied={copied === "pass"}
                onCopy={() => copy("pass", password)} onRegen={() => setPassword(genPassword())} />

              <div className="cred-note">
                <span className="material-symbols-rounded">lock</span>
                Auto-generated &amp; shown once. The member is prompted to reset the password and enable 2FA at first sign-in.
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={() => setStep(2)}>
                  <span className="material-symbols-rounded">arrow_back</span>Back
                </button>
                <button type="button" className="primary-btn" onClick={finish}>
                  <span className="material-symbols-rounded">send</span>Create &amp; invite
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Bubble({ feature, index, granted, popping, onClick }: {
  feature: AccessFeature; index: number; granted: boolean; popping: boolean; onClick: () => void;
}) {
  const color = GROUP_COLOR[feature.group];
  return (
    <button
      type="button"
      className={`bubble${granted ? " granted" : ""}${popping ? " popping" : ""}`}
      style={{ ["--c" as string]: color, ["--i" as string]: index }}
      onClick={onClick}
      aria-pressed={granted}
      title={`${feature.label} — ${feature.desc}`}
    >
      <span className="bubble-core">
        <span className="bubble-sheen" />
        <span className="bubble-ic material-symbols-rounded">{granted ? "check" : feature.icon}</span>
        <span className="bubble-lbl">{feature.short}</span>
      </span>
      <span className="burst" aria-hidden />
      {SHARDS.map((s, i) => (
        <span key={i} className="shard" aria-hidden style={{ ["--sx" as string]: `${s.x}px`, ["--sy" as string]: `${s.y}px` }} />
      ))}
    </button>
  );
}

function CredRow({ label, value, icon, mono, copied, onCopy, onRegen }: {
  label: string; value: string; icon: string; mono?: boolean; copied: boolean; onCopy: () => void; onRegen?: () => void;
}) {
  return (
    <div className="cred-row">
      <span className="cred-ic material-symbols-rounded">{icon}</span>
      <div className="cred-main">
        <div className="cred-l">{label}</div>
        <div className={`cred-v${mono ? " mono" : ""}`}>{value}</div>
      </div>
      {onRegen && (
        <button className="cred-btn" onClick={onRegen} title="Regenerate" aria-label="Regenerate password">
          <span className="material-symbols-rounded">refresh</span>
        </button>
      )}
      <button className={`cred-btn${copied ? " ok" : ""}`} onClick={onCopy} title="Copy" aria-label={`Copy ${label}`}>
        <span className="material-symbols-rounded">{copied ? "check" : "content_copy"}</span>
      </button>
    </div>
  );
}
