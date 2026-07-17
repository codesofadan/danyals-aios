"use client";

import { useEffect, useRef, useState } from "react";
import { useMe } from "@/lib/hooks/settings";
import { Switch, SettingGroup, SettingRow, PasswordField, SavedFlash } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;

function strength(pw: string): { pct: number; label: string; cls: string } {
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  const map = [
    { pct: 8, label: "—", cls: "weak" },
    { pct: 25, label: "Weak", cls: "weak" },
    { pct: 45, label: "Fair", cls: "fair" },
    { pct: 65, label: "Good", cls: "good" },
    { pct: 85, label: "Strong", cls: "strong" },
    { pct: 100, label: "Excellent", cls: "strong" },
  ];
  return map[Math.min(s, 5)];
}

export default function AccountSettings({ onLog }: { onLog: LogFn }) {
  // The signed-in operator's own record (GET /me). MISMATCH (recorded): /me carries
  // no `phone` and no 2FA field, and there is NO write route (no PUT /me, no
  // password-change endpoint) — so the profile fields READ from the API, but Save
  // profile / password / 2FA remain local confirmations until an account-write
  // endpoint exists. Phone & 2FA are local-only (not backed by /me).
  const meQ = useMe();
  const me = meQ.data;

  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [twoFA, setTwoFA] = useState(false);

  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");

  const [savedProfile, setSavedProfile] = useState(false);
  const [savedPass, setSavedPass] = useState(false);

  // Seed the editable form ONCE from the API record (a refetch never clobbers edits).
  const seeded = useRef(false);
  useEffect(() => {
    if (!seeded.current && me) {
      setName(me.name);
      setTitle(me.title);
      setEmail(me.email);
      seeded.current = true;
    }
  }, [me]);

  const st = strength(next);
  const mismatch = confirm.length > 0 && next !== confirm;
  const canSavePass = cur.length > 0 && next.length >= 8 && next === confirm;

  function saveProfile() {
    setSavedProfile(true);
    setTimeout(() => setSavedProfile(false), 1800);
    onLog("updated own profile", name, "Account");
  }

  function savePassword() {
    if (!canSavePass) return;
    setCur(""); setNext(""); setConfirm("");
    setSavedPass(true);
    setTimeout(() => setSavedPass(false), 1800);
    onLog("changed own password", email, "Security");
  }

  const muted: React.CSSProperties = { padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)" };
  if (meQ.isLoading && !me) return <div className="panel-in"><div style={muted}>Loading your account…</div></div>;
  if (meQ.isError && !me)
    return <div className="panel-in"><div style={muted}>Couldn&apos;t load your account — {(meQ.error as Error)?.message ?? "try again"}.</div></div>;
  if (!me) return null;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">account_circle</span>
          Your profile, sign-in credentials &amp; two-factor authentication
        </div>
      </div>

      <div className="acct-head">
        <span className="acct-av" style={{ background: me.c }}>{me.init}</span>
        <div>
          <div className="acct-name">{name}</div>
          <div className="acct-sub">
            <span className="role-chip" style={{ color: me.c, borderColor: me.c }}>{me.role}</span>
            <span>{email}</span>
          </div>
        </div>
      </div>

      <SettingGroup title="Profile" icon="badge">
        <div className="fld-grid">
          <div className="fld"><label htmlFor="ac-name">Full name</label><input id="ac-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="fld"><label htmlFor="ac-title">Job title</label><input id="ac-title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
          <div className="fld"><label htmlFor="ac-email">Login email</label><input id="ac-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div className="fld"><label htmlFor="ac-phone">Phone</label><input id="ac-phone" value={phone} onChange={(e) => setPhone(e.target.value)} /></div>
        </div>
        <div className="set-actions">
          <SavedFlash show={savedProfile} />
          <button className="primary-btn" onClick={saveProfile}>
            <span className="material-symbols-rounded">save</span>Save profile
          </button>
        </div>
      </SettingGroup>

      <SettingGroup title="Change password" icon="password">
        <div className="fld-grid">
          <div className="fld"><label htmlFor="ac-cur">Current password</label><PasswordField id="ac-cur" value={cur} onChange={setCur} canGenerate={false} /></div>
          <div className="fld"><label htmlFor="ac-new">New password</label><PasswordField id="ac-new" value={next} onChange={setNext} /></div>
          <div className="fld">
            <label htmlFor="ac-conf">Confirm new password</label>
            <PasswordField id="ac-conf" value={confirm} onChange={setConfirm} canGenerate={false} />
            {mismatch && <div className="fld-err">Passwords don’t match</div>}
          </div>
          <div className="fld">
            <label>Strength</label>
            <div className="pw-strength">
              <div className="pw-bar"><span className={st.cls} style={{ width: `${next ? st.pct : 0}%` }} /></div>
              <span className={`pw-label ${st.cls}`}>{next ? st.label : "—"}</span>
            </div>
          </div>
        </div>
        <div className="set-actions">
          <SavedFlash show={savedPass} label="Password updated" />
          <button className="primary-btn" onClick={savePassword} disabled={!canSavePass}>
            <span className="material-symbols-rounded">lock_reset</span>Update password
          </button>
        </div>
      </SettingGroup>

      <SettingGroup title="Two-factor authentication" icon="verified_user">
        <SettingRow icon="phonelink_lock" title="Authenticator app (TOTP)" desc="Require a 6-digit code from your authenticator at sign-in.">
          <Switch checked={twoFA} onChange={(v) => { setTwoFA(v); onLog(v ? "enabled 2FA" : "disabled 2FA", "own account", "Security"); }} label="Toggle two-factor authentication" />
        </SettingRow>
      </SettingGroup>
    </div>
  );
}
