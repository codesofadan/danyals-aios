"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GROUP_COLOR, TEMPLATE_COLOR } from "@/lib/data";
import { useRbacTemplates } from "@/lib/hooks/team";
import type { NewMember } from "./TeamRoster";

const ADJ = ["Solar", "Rapid", "Cobalt", "Lunar", "Amber", "Quartz", "Nimbus", "Vivid", "Onyx", "Cedar", "Zephyr", "Crimson"];
const NOUN = ["Falcon", "Harbor", "Cipher", "Meadow", "Quasar", "Lynx", "Beacon", "Vertex", "Willow", "Ember", "Comet", "Delta"];
const SYM = "!@#$%&*?";

// Crypto-random index — this password is now the REAL stored credential (the
// server hashes exactly what the wizard shows), so Math.random isn't enough.
function rand(n: number): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] % n;
}

function pick<T>(arr: T[]): T { return arr[rand(arr.length)]; }

// Mirrors the server's shape: Adjective-Noun####$xxxxxx (4 digits + symbol + 6 hex).
function genPassword(): string {
  const digits = String(1000 + rand(9000));
  const sym = SYM[rand(SYM.length)];
  const tail = Array.from({ length: 6 }, () => "0123456789abcdef"[rand(16)]).join("");
  return `${pick(ADJ)}-${pick(NOUN)}${digits}${sym}${tail}`;
}

function genUsername(name: string): string {
  const parts = name.trim().toLowerCase().replace(/[^a-z\s]/g, "").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "new.member";
  if (parts.length === 1) return `${parts[0]}.aios`;
  return `${parts[0]}.${parts[parts.length - 1]}`;
}

type Step = 1 | 2;
const STEP_LABELS = ["Details", "Credentials"];

export default function AddMemberWizard({ onClose, onAdd }: { onClose: () => void; onAdd: (m: NewMember) => void }) {
  const [step, setStep] = useState<Step>(1);
  // The catalogue is server-owned reference data now (GET /rbac/templates), so it
  // arrives asynchronously and the selection cannot be seeded synchronously.
  const templatesQ = useRbacTemplates();
  const templates = useMemo(() => templatesQ.data ?? [], [templatesQ.data]);
  const [template, setTemplate] = useState<string>("");
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

  // Default to the first template ONCE it arrives, and never override a choice the
  // user has already made — a refetch must not silently reset their selection.
  useEffect(() => {
    if (!template && templates.length) setTemplate(templates[0].key);
  }, [template, templates]);

  const tpl = templates.find((t) => t.key === template);

  const emailValid = /\S+@\S+\.\S+/.test(email);
  const nameValid = name.trim().length > 1;

  function goCredentials() {
    if (!nameValid || !emailValid) return;
    setUsername(genUsername(name));
    setPassword(genPassword());
    setStep(2);
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
      // From TEMPLATE_COLOR, not `tpl.color`: the template catalogue is moving to
      // `GET /rbac/templates`, whose response carries no colour. Reading it here
      // keeps the avatar accent correct across that swap instead of falling through
      // to provisioning's legacy-violet default.
      color: (tpl && TEMPLATE_COLOR[tpl.key]) || GROUP_COLOR.Analytics,
      template: tpl ? tpl.label : "Custom",
      features: tpl ? [...tpl.grants] : [],
      username, // one-time credentials so they can sign into the portal
      password,
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
                {step === 1 && "Who is joining the team?"}
                {step === 2 && "Share these one-time credentials to finish the invite."}
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

          {/* STEP 1 — identity */}
          {step === 1 && (
            <form className="wiz-body" onSubmit={(e) => { e.preventDefault(); goCredentials(); }}>
              <div className="fld">
                <label>Full name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ali Hassan" autoFocus />
              </div>
              <div className="fld">
                <label>Work email</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ali@qanry.com" />
              </div>
              <div className="fld">
                <label>Role</label>
                <div className="tpl-select">
                  <span className="material-symbols-rounded tpl-ic">{tpl ? tpl.icon : "category"}</span>
                  <select value={template} onChange={(e) => setTemplate(e.target.value)} aria-label="Role template">
                    {templatesQ.isPending ? (
                      <option value="">Loading roles…</option>
                    ) : templatesQ.isError ? (
                      // Say so rather than presenting an empty dropdown as "no roles
                      // exist" — the operator needs to know this is a fetch failure.
                      <option value="">Couldn&apos;t load roles</option>
                    ) : (
                      templates.map((t) => (
                        <option key={t.key} value={t.key}>{t.label} — {t.tagline}</option>
                      ))
                    )}
                  </select>
                </div>
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                {/* `!tpl` is not belt-and-braces. The catalogue is fetched now, so a
                    fast operator could type a name and email and press Next before it
                    arrives — and the submit path falls back to `features: []`, which
                    provisions a member with NO feature grants. Silent, and only
                    visible later as "why can't they see anything". */}
                <button
                  type="submit"
                  className="primary-btn"
                  disabled={!nameValid || !emailValid || !tpl}
                >
                  Next<span className="material-symbols-rounded">arrow_forward</span>
                </button>
              </div>
            </form>
          )}

          {/* STEP 2 — credentials */}
          {step === 2 && (
            <div className="wiz-body">
              <div className="cred-hero">
                <span className="av" style={{ background: (tpl && TEMPLATE_COLOR[tpl.key]) || GROUP_COLOR.Analytics }}>
                  {name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                </span>
                <div>
                  <div className="cred-name">{name}</div>
                  <div className="cred-role">{tpl ? tpl.label : "Team Member"}</div>
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
                <button type="button" className="ghostbtn" onClick={() => setStep(1)}>
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
