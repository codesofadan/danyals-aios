"use client";

import { useState } from "react";
import { defaultRolePerms, type TeamRole, type PermKey } from "@/lib/data";
import AccessControl from "@/components/team/AccessControl";
import AccountSettings from "./AccountSettings";
import ClientCredentials from "./ClientCredentials";
import TeamCredentials from "./TeamCredentials";
import SecuritySettings from "./SecuritySettings";
import NotificationSettings from "./NotificationSettings";
import WorkspaceSettings from "./WorkspaceSettings";

type TabKey = "account" | "clients" | "team" | "access" | "security" | "notifications" | "workspace";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "account", label: "Account", icon: "account_circle" },
  { key: "clients", label: "Client Access", icon: "key" },
  { key: "team", label: "Team Access", icon: "manage_accounts" },
  { key: "access", label: "Roles & Permissions", icon: "admin_panel_settings" },
  { key: "security", label: "Security", icon: "security" },
  { key: "notifications", label: "Notifications", icon: "notifications" },
  { key: "workspace", label: "Workspace", icon: "tune" },
];

export default function SettingsWorkspace() {
  const [tab, setTab] = useState<TabKey>("account");
  const [rolePerms, setRolePerms] = useState<Record<TeamRole, PermKey[]>>(defaultRolePerms);
  const [toast, setToast] = useState<{ n: number; text: string } | null>(null);

  // Shared audit-trail hook — every panel reports admin actions here.
  function onLog(action: string, target: string, meta?: string) {
    setToast((prev) => ({ n: (prev?.n ?? 0) + 1, text: `${action} · ${target}${meta ? ` — ${meta}` : ""}` }));
  }

  function handleTogglePerm(role: TeamRole, key: PermKey) {
    let granted = false;
    setRolePerms((prev) => {
      const has = prev[role].includes(key);
      granted = !has;
      return { ...prev, [role]: has ? prev[role].filter((k) => k !== key) : [...prev[role], key] };
    });
    onLog(granted ? "granted" : "revoked", key.replace(/_/g, " "), `${role} role`);
  }

  return (
    <section className="card settings-card">
      <div className="card-h">
        <div>
          <div className="ct">Settings</div>
          <div className="cs">Credentials, roles, access, security &amp; workspace preferences — one control panel.</div>
        </div>
      </div>

      <div className="tw-tabs" role="tablist" aria-label="Settings sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? "tw-tab on" : "tw-tab"}
            onClick={() => setTab(t.key)}
          >
            <span className="material-symbols-rounded">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      <div className="tw-panel" role="tabpanel">
        {tab === "account" && <AccountSettings onLog={onLog} />}
        {tab === "clients" && <ClientCredentials onLog={onLog} />}
        {tab === "team" && <TeamCredentials onLog={onLog} />}
        {tab === "access" && <AccessControl rolePerms={rolePerms} onToggle={handleTogglePerm} />}
        {tab === "security" && <SecuritySettings onLog={onLog} />}
        {tab === "notifications" && <NotificationSettings onLog={onLog} />}
        {tab === "workspace" && <WorkspaceSettings onLog={onLog} />}
      </div>

      {toast && (
        <div className="set-toast" key={toast.n} role="status">
          <span className="material-symbols-rounded">history</span>
          <span className="st-txt">{toast.text}</span>
          <span className="st-tag">logged</span>
        </div>
      )}
    </section>
  );
}
