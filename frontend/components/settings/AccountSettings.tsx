"use client";

import { useEffect, useRef, useState } from "react";
import { useMe, useNotifPrefs, useUpdateMe, useUpdateNotifPrefs } from "@/lib/hooks/settings";
import type { NotifPref } from "@/lib/data";
import { SettingGroup, SettingRow, Switch, SavedFlash } from "./controls";
import ReadMore from "@/components/ui/ReadMore";

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

      {/* The self-service password change (Current / New / Confirm) was REMOVED here
          on the owner's instruction (QA 9: "Remove Current Password and New Password
          options"). Consequence, stated so nobody rediscovers it as a bug: there is
          now no way for a signed-in person to change their own password in-product.
          A forgotten or compromised password is reset by an owner/admin from Team
          Management (Show login -> Reset), which also ends the old sessions.

          `POST /me/password` and `useChangePassword` are both left in place and are
          now caller-less - restoring the block is a UI-only change. */}
      <SettingGroup title="Notification preferences" icon="notifications">
        {notifQ.isLoading ? (
          <div style={muted}>Loading preferences…</div>
        ) : notifQ.isError ? (
          <div style={muted}>Couldn&apos;t load preferences — {(notifQ.error as Error)?.message ?? "try again"}.</div>
        ) : (
          <>
            <ReadMore
              items={notifList}
              initialCount={5}
              getKey={(n) => n.key}
              renderItem={(n) => {
                const v = prefs[n.key] ?? { email: n.email, inApp: n.inApp };
                return (
                  <SettingRow icon={n.icon} title={n.label} desc={n.desc}>
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
              }}
            />
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
