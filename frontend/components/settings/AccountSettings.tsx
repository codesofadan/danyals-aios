"use client";

import { useEffect, useRef, useState } from "react";
import { useMe, useNotifPrefs, useUpdateMe, useUpdateNotifPrefs } from "@/lib/hooks/settings";
import { useChangePassword } from "@/lib/hooks/portal";
import type { NotifPref } from "@/lib/data";
import { SettingGroup, SettingRow, Switch, SavedFlash } from "./controls";

export default function AccountSettings() {
  // The signed-in operator's own record (GET /me · PATCH /me) — the real
  // self-service profile surface. Only fields the /me contract actually persists
  // are editable here (no local-only avatar-upload / 2FA / phone dressing: the
  // backend has no file-upload or 2FA endpoint, so we don't fake one).
  const meQ = useMe();
  const me = meQ.data;
  const updateMe = useUpdateMe();

  // Per-user notification preferences — real endpoints (GET/PUT /settings/notifications).
  const notifQ = useNotifPrefs();
  const updateNotifs = useUpdateNotifPrefs();

  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");

  const [savedProfile, setSavedProfile] = useState(false);
  const [savedNotifs, setSavedNotifs] = useState(false);

  // Local, optimistic toggle state seeded from the server list, keyed by event.
  const [prefs, setPrefs] = useState<Record<string, { email: boolean; inApp: boolean }>>({});
  const prefsSeeded = useRef(false);

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

  useEffect(() => {
    if (!prefsSeeded.current && notifQ.data) {
      const seed: Record<string, { email: boolean; inApp: boolean }> = {};
      for (const p of notifQ.data) seed[p.key] = { email: p.email, inApp: p.inApp };
      setPrefs(seed);
      prefsSeeded.current = true;
    }
  }, [notifQ.data]);

  function saveProfile() {
    updateMe.mutate(
      { name, title, email },
      {
        onSuccess: () => {
          setSavedProfile(true);
          setTimeout(() => setSavedProfile(false), 1800);
        },
      },
    );
  }

  function toggle(key: string, field: "email" | "inApp") {
    setPrefs((p) => ({ ...p, [key]: { ...p[key], [field]: !p[key]?.[field] } }));
  }

  function saveNotifs() {
    const payload = Object.entries(prefs).map(([key, v]) => ({ key, email: v.email, inApp: v.inApp }));
    updateNotifs.mutate(payload, {
      onSuccess: () => {
        setSavedNotifs(true);
        setTimeout(() => setSavedNotifs(false), 1800);
      },
    });
  }

  const muted: React.CSSProperties = { padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)" };
  if (meQ.isLoading && !me) return <div className="panel-in"><div style={muted}>Loading your account…</div></div>;
  if (meQ.isError && !me)
    return <div className="panel-in"><div style={muted}>Couldn&apos;t load your account — {(meQ.error as Error)?.message ?? "try again"}.</div></div>;
  if (!me) return null;

  const notifList: NotifPref[] = notifQ.data ?? [];

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">account_circle</span>
          Your profile &amp; notification preferences
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
        </div>
        <div className="set-actions">
          <SavedFlash show={savedProfile} />
          <button className="primary-btn" onClick={saveProfile} disabled={updateMe.isPending}>
            <span className="material-symbols-rounded">save</span>
            {updateMe.isPending ? "Saving…" : "Save profile"}
          </button>
        </div>
      </SettingGroup>

      <ChangePassword />

      <SettingGroup title="Notification preferences" icon="notifications">
        {notifQ.isLoading ? (
          <div style={muted}>Loading preferences…</div>
        ) : notifQ.isError ? (
          <div style={muted}>Couldn&apos;t load preferences — {(notifQ.error as Error)?.message ?? "try again"}.</div>
        ) : (
          <>
            {notifList.map((n) => {
              const v = prefs[n.key] ?? { email: n.email, inApp: n.inApp };
              return (
                <SettingRow key={n.key} icon={n.icon} title={n.label} desc={n.desc}>
                  <div className="notif-toggles">
                    <label className="notif-toggle">
                      <Switch checked={v.email} onChange={() => toggle(n.key, "email")} label={`${n.label} — email`} />
                      <span>Email</span>
                    </label>
                    <label className="notif-toggle">
                      <Switch checked={v.inApp} onChange={() => toggle(n.key, "inApp")} label={`${n.label} — in-app`} />
                      <span>In-app</span>
                    </label>
                  </div>
                </SettingRow>
              );
            })}
            <div className="set-actions">
              <SavedFlash show={savedNotifs} label="Preferences saved" />
              <button className="primary-btn" onClick={saveNotifs} disabled={updateNotifs.isPending}>
                <span className="material-symbols-rounded">save</span>
                {updateNotifs.isPending ? "Saving…" : "Save preferences"}
              </button>
            </div>
          </>
        )}
      </SettingGroup>
    </div>
  );
}


// Changing your own password.
//
// `POST /me/password` and `useChangePassword` both existed and NOTHING called them:
// there was no way, anywhere in the product, for a signed-in person to change their
// own password. A team member's only route was to ask an admin to reset it — which
// hands their credential to someone else, and is the opposite of what a self-service
// password change is for.
function ChangePassword() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);

  // Checked here only to spare a round trip on an obvious slip. The password's real
  // rules — and the verification of `current` — are the server's, not this form's.
  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 12;
  const ready = current.length > 0 && next.length >= 12 && next === confirm && !change.isPending;

  function submit() {
    if (!ready) return;
    setDone(false);
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent(""); setNext(""); setConfirm(""); setDone(true);
        },
      },
    );
  }

  return (
    <SettingGroup title="Password" icon="key">
      <div className="fld-grid">
        <div className="fld">
          <label htmlFor="pw-cur">Current password</label>
          <input id="pw-cur" type="password" autoComplete="current-password"
            value={current} onChange={(e) => { setCurrent(e.target.value); setDone(false); }} />
        </div>
        <div className="fld">
          <label htmlFor="pw-new">New password</label>
          <input id="pw-new" type="password" autoComplete="new-password"
            value={next} onChange={(e) => { setNext(e.target.value); setDone(false); }} />
        </div>
        <div className="fld">
          <label htmlFor="pw-confirm">Confirm new password</label>
          <input id="pw-confirm" type="password" autoComplete="new-password"
            value={confirm} onChange={(e) => { setConfirm(e.target.value); setDone(false); }} />
        </div>
      </div>

      {tooShort && <div className="set-hint warn">Use at least 12 characters.</div>}
      {mismatch && <div className="set-hint warn">The two new passwords do not match.</div>}
      {change.error instanceof Error && (
        <div className="set-hint err" role="alert">
          Couldn&apos;t change your password — {change.error.message}
        </div>
      )}

      <div className="set-actions">
        {/* Same flash the profile and preference saves use, so a success reads the
            same way everywhere in this panel. */}
        <SavedFlash show={done} label="Password changed" />
        <button className="primary-btn" onClick={submit} disabled={!ready}>
          <span className="material-symbols-rounded">key</span>
          {change.isPending ? "Changing…" : "Change password"}
        </button>
      </div>
    </SettingGroup>
  );
}
