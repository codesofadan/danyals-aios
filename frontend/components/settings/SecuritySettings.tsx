"use client";

import { useState } from "react";
import { securityDefaults, PASS_LENGTHS, ROTATION_OPTIONS, SESSION_OPTIONS, type SecurityPolicy } from "@/lib/data";
import { Switch, SettingGroup, SettingRow } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;

export default function SecuritySettings({ onLog }: { onLog: LogFn }) {
  const [p, setP] = useState<SecurityPolicy>(securityDefaults);

  function set<K extends keyof SecurityPolicy>(key: K, value: SecurityPolicy[K], label: string) {
    setP((prev) => ({ ...prev, [key]: value }));
    onLog("changed security policy", label, "Security");
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">security</span>
          Platform-wide security policy for every login on this workspace
        </div>
      </div>

      <SettingGroup title="Authentication" icon="verified_user">
        <SettingRow icon="phonelink_lock" title="Enforce two-factor authentication" desc="Every team member must set up 2FA before they can sign in.">
          <Switch checked={p.enforce2FA} onChange={(v) => set("enforce2FA", v, "enforce 2FA")} label="Enforce 2FA" />
        </SettingRow>
        <SettingRow icon="password" title="Require strong passwords" desc="Mixed case, a number and a symbol are required.">
          <Switch checked={p.strongPasswords} onChange={(v) => set("strongPasswords", v, "strong passwords")} label="Require strong passwords" />
        </SettingRow>
        <SettingRow icon="straighten" title="Minimum password length" desc="Shortest password the platform will accept.">
          <select className="mini-select w" value={p.minPassLength} onChange={(e) => set("minPassLength", Number(e.target.value), "minimum length")}>
            {PASS_LENGTHS.map((n) => <option key={n} value={n}>{n} characters</option>)}
          </select>
        </SettingRow>
        <SettingRow icon="event_repeat" title="Password rotation" desc="Prompt users to change their password on a schedule.">
          <select className="mini-select w" value={p.rotationDays} onChange={(e) => set("rotationDays", Number(e.target.value), "rotation")}>
            {ROTATION_OPTIONS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
        </SettingRow>
      </SettingGroup>

      <SettingGroup title="Sessions & network" icon="lan">
        <SettingRow icon="timer" title="Session timeout" desc="Automatically sign users out after inactivity.">
          <select className="mini-select w" value={p.sessionTimeout} onChange={(e) => set("sessionTimeout", Number(e.target.value), "session timeout")}>
            {SESSION_OPTIONS.map((n) => <option key={n} value={n}>{n >= 60 ? `${n / 60} hour${n > 60 ? "s" : ""}` : `${n} minutes`}</option>)}
          </select>
        </SettingRow>
        <SettingRow icon="devices" title="Single active session" desc="Signing in on a new device ends the previous session.">
          <Switch checked={p.singleSession} onChange={(v) => set("singleSession", v, "single session")} label="Single active session" />
        </SettingRow>
        <SettingRow icon="vpn_lock" title="IP allowlist" desc="Restrict admin sign-in to approved office / VPN addresses.">
          <Switch checked={p.ipAllowlist} onChange={(v) => set("ipAllowlist", v, "IP allowlist")} label="IP allowlist" />
        </SettingRow>
        <SettingRow icon="history" title="Audit logging" desc="Record every credential and access change to the activity log.">
          <Switch checked={p.auditLogging} onChange={(v) => set("auditLogging", v, "audit logging")} label="Audit logging" />
        </SettingRow>
      </SettingGroup>
    </div>
  );
}
