"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  clientReports, reportBundles, REPORT_GROUP_COLOR, TIER_PRICE,
  type ClientReport, type SubTier, type NewClient,
} from "@/lib/data";

// 6 shard vectors (hexagon burst) — reused by every bubble pop.
const SHARDS = [
  { x: 46, y: 0 }, { x: 23, y: 40 }, { x: -23, y: 40 },
  { x: -46, y: 0 }, { x: -23, y: -40 }, { x: 23, y: -40 },
];

const ADJ = ["Solar", "Rapid", "Cobalt", "Lunar", "Amber", "Quartz", "Nimbus", "Vivid", "Onyx", "Cedar", "Zephyr", "Crimson"];
const NOUN = ["Falcon", "Harbor", "Cipher", "Meadow", "Quasar", "Lynx", "Beacon", "Vertex", "Willow", "Ember", "Comet", "Delta"];
const SYM = "!@#$%&*?";

const TIERS: SubTier[] = ["Starter", "Growth", "Scale"];

// Crypto-random index — this password is the REAL stored portal credential (the
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

// Best-effort admin login from the contact email, else from the client name.
function genLogin(email: string, client: string): string {
  if (/\S+@\S+\.\S+/.test(email)) return `admin@${email.split("@")[1]}`;
  const slug = client.trim().toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 18);
  return `admin@${slug || "client"}.com`;
}

type Step = 1 | 2 | 3;
const STEP_LABELS = ["Report Access", "Details", "Credentials"];

export default function AddClientWizard({ onClose, onAdd }: { onClose: () => void; onAdd: (c: NewClient) => void }) {
  const [step, setStep] = useState<Step>(1);
  const [granted, setGranted] = useState<Set<string>>(new Set());
  const [bundle, setBundle] = useState<string>(""); // "" = custom
  const [popping, setPopping] = useState<Set<string>>(new Set());
  const [cn, setCn] = useState("");
  const [industry, setIndustry] = useState("");
  const [tier, setTier] = useState<SubTier>("Growth");
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [adminLogin, setAdminLogin] = useState("");
  const [adminPass, setAdminPass] = useState("");
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

  function applyBundle(key: string) {
    setBundle(key);
    const b = reportBundles.find((x) => x.key === key);
    const next = new Set(b ? b.grants : []);
    const newlyOn = [...next].filter((k) => !granted.has(k));
    setGranted(next);
    playPop(newlyOn);
  }

  const b = reportBundles.find((x) => x.key === bundle);
  const customized = useMemo(() => {
    if (!b) return false;
    if (b.grants.length !== granted.size) return true;
    return b.grants.some((k) => !granted.has(k));
  }, [b, granted]);

  const emailValid = /\S+@\S+\.\S+/.test(contactEmail);
  const nameValid = cn.trim().length > 1;
  const contactValid = contactName.trim().length > 1;

  function goCredentials() {
    if (!nameValid || !contactValid || !emailValid) return;
    setAdminLogin(genLogin(contactEmail, cn));
    setAdminPass(genPassword());
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
      cn: cn.trim(),
      industry: industry.trim() || "General",
      tier,
      contactName: contactName.trim(),
      contactEmail: contactEmail.trim(),
      adminLogin,
      adminPass,
      bundle: b ? b.label : "Custom",
      reports: [...granted],
    });
  }

  return (
    <div className="tw">
      <div className="modal-scrim" onClick={onClose}>
        <div className="modal wide wiz" onClick={(e) => e.stopPropagation()}>
          <div className="modal-h">
            <div>
              <div className="modal-t">Add client</div>
              <div className="modal-s">
                {step === 1 && "Pop the charts, graphs & reports this client is allowed to see. Anything left un-popped stays hidden."}
                {step === 2 && "Who is the client and their primary contact?"}
                {step === 3 && "Share these one-time portal credentials to finish onboarding."}
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

          {/* STEP 1 — report access */}
          {step === 1 && (
            <div className="wiz-body">
              <div className="tpl-row">
                <label className="tpl-label">Access bundle</label>
                <div className="tpl-select">
                  <span className="material-symbols-rounded tpl-ic">{b ? b.icon : "tune"}</span>
                  <select value={bundle} onChange={(e) => applyBundle(e.target.value)} aria-label="Access bundle">
                    <option value="">Custom — start from scratch</option>
                    {reportBundles.map((x) => (
                      <option key={x.key} value={x.key}>{x.label} — {x.tagline}</option>
                    ))}
                  </select>
                </div>
                <div className="grant-count">
                  <b>{granted.size}</b> / {clientReports.length} visible
                  {b && <span className={`tpl-tag${customized ? " cust" : ""}`}>{customized ? `${b.label} · customized` : b.label}</span>}
                </div>
                {granted.size > 0 && (
                  <button className="clear-btn" onClick={() => { setGranted(new Set()); setBundle(""); }}>
                    <span className="material-symbols-rounded">restart_alt</span>Clear
                  </button>
                )}
              </div>

              <div className="bubble-field">
                {clientReports.map((r, i) => (
                  <Bubble
                    key={r.key}
                    report={r}
                    index={i}
                    granted={granted.has(r.key)}
                    popping={popping.has(r.key)}
                    onClick={() => toggleBubble(r.key)}
                  />
                ))}
              </div>

              <div className="bubble-legend">
                <span><span className="lg-swatch open" /> Hidden — the client can&apos;t see it</span>
                <span><span className="lg-swatch popped" /> Popped &amp; visible to the client</span>
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                <button type="button" className="primary-btn" onClick={() => setStep(2)}>
                  Next<span className="material-symbols-rounded">arrow_forward</span>
                </button>
              </div>
            </div>
          )}

          {/* STEP 2 — details */}
          {step === 2 && (
            <form className="wiz-body" onSubmit={(e) => { e.preventDefault(); goCredentials(); }}>
              <div className="fld">
                <label>Client / company name</label>
                <input value={cn} onChange={(e) => setCn(e.target.value)} placeholder="e.g. Harbor Dental Group" autoFocus />
              </div>
              <div className="fld-row">
                <div className="fld">
                  <label>Industry</label>
                  <input value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="e.g. Healthcare" />
                </div>
                <div className="fld">
                  <label>Plan tier</label>
                  <div className="tpl-select">
                    <span className="material-symbols-rounded tpl-ic">workspace_premium</span>
                    <select value={tier} onChange={(e) => setTier(e.target.value as SubTier)} aria-label="Plan tier">
                      {TIERS.map((t) => (
                        <option key={t} value={t}>{t} — ${TIER_PRICE[t]}/mo</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
              <div className="fld">
                <label>Primary contact name</label>
                <input value={contactName} onChange={(e) => setContactName(e.target.value)} placeholder="e.g. Dr. Sana Malik" />
              </div>
              <div className="fld">
                <label>Contact email</label>
                <input type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} placeholder="sana@harbordental.com" />
              </div>

              <div className="wiz-recap">
                <span className="material-symbols-rounded">{b ? b.icon : "tune"}</span>
                <div>
                  <div className="recap-t">{b ? b.label : "Custom access"}{customized ? " · customized" : ""}</div>
                  <div className="recap-s">{granted.size} of {clientReports.length} reports visible</div>
                </div>
                <button type="button" className="recap-edit" onClick={() => setStep(1)}>Edit</button>
              </div>

              <div className="modal-f">
                <button type="button" className="ghostbtn" onClick={() => setStep(1)}>
                  <span className="material-symbols-rounded">arrow_back</span>Back
                </button>
                <button type="submit" className="primary-btn" disabled={!nameValid || !contactValid || !emailValid}>
                  Next<span className="material-symbols-rounded">arrow_forward</span>
                </button>
              </div>
            </form>
          )}

          {/* STEP 3 — credentials */}
          {step === 3 && (
            <div className="wiz-body">
              <div className="cred-hero">
                <span className="av" style={{ background: b ? b.color : REPORT_GROUP_COLOR.Performance }}>
                  {cn.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
                </span>
                <div>
                  <div className="cred-name">{cn}</div>
                  <div className="cred-role">{tier} · {granted.size} reports visible</div>
                </div>
                <span className="cred-ok"><span className="material-symbols-rounded">verified</span>Ready</span>
              </div>

              <CredRow label="Portal admin login" value={adminLogin} icon="alternate_email" copied={copied === "user"} onCopy={() => copy("user", adminLogin)} />
              <CredRow label="Temporary password" value={adminPass} icon="password" mono copied={copied === "pass"}
                onCopy={() => copy("pass", adminPass)} onRegen={() => setAdminPass(genPassword())} />

              <div className="cred-note">
                <span className="material-symbols-rounded">lock</span>
                Auto-generated &amp; shown once. The client is prompted to reset the password and enable 2FA at first sign-in. They will only ever see the {granted.size} reports granted above.
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

function Bubble({ report, index, granted, popping, onClick }: {
  report: ClientReport; index: number; granted: boolean; popping: boolean; onClick: () => void;
}) {
  const color = REPORT_GROUP_COLOR[report.group];
  return (
    <button
      type="button"
      className={`bubble${granted ? " granted" : ""}${popping ? " popping" : ""}`}
      style={{ ["--c" as string]: color, ["--i" as string]: index }}
      onClick={onClick}
      aria-pressed={granted}
      title={`${report.label} — ${report.desc}`}
    >
      <span className="bubble-core">
        <span className="bubble-sheen" />
        <span className="bubble-ic material-symbols-rounded">{granted ? "visibility" : report.icon}</span>
      </span>
      <span className="bubble-lbl">{report.short}</span>
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
