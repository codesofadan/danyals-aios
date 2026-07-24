"use client";

import { useState, type ReactNode } from "react";
import { type TeamRole, type PermKey } from "@/lib/data";
import { useRbac } from "@/lib/hooks/team";
import AccessControl from "@/components/team/AccessControl";
import AccountSettings from "./AccountSettings";
import ClientCredentials from "./ClientCredentials";
import TeamCredentials from "./TeamCredentials";

type TabKey = "account" | "clients" | "team" | "access";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "account", label: "My Account", icon: "account_circle" },
  { key: "clients", label: "Client Access", icon: "key" },
  { key: "team", label: "Team Access", icon: "manage_accounts" },
  { key: "access", label: "Roles & Permissions", icon: "admin_panel_settings" },
];

// Centred muted state for a tab panel (loading / error). Self-styled so it never
// depends on a class that might not exist.
const panelState: React.CSSProperties = {
  padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)",
};

function panelGuard(q: { isLoading: boolean; isError: boolean; error?: unknown }): ReactNode | null {
  if (q.isLoading) return <div style={panelState}>Loading…</div>;
  if (q.isError) return <div style={panelState}>Couldn&apos;t load — {(q.error as Error)?.message ?? "try again"}.</div>;
  return null;
}

export default function SettingsWorkspace() {
  const [tab, setTab] = useState<TabKey>("account");
  // The role×permission matrix is server-side REFERENCE data (GET /rbac/roles):
  // versioned platform code with NO per-role toggle route, so AccessControl renders
  // it strictly read-only (no toggle affordance, no persist).
  const rbacQ = useRbac();
  const rolePerms = rbacQ.data ?? ({} as Record<TeamRole, PermKey[]>);
  const [toast, setToast] = useState<{ n: number; text: string } | null>(null);

  // A transient on-screen confirmation for the panels that DO persist a real
  // mutation (My Account → /me, Team Access → /admin/users/{id}/password). Read-only
  // panels (Client Access, Roles & Permissions) never call this.
  function onLog(action: string, target: string, meta?: string) {
    setToast((prev) => ({ n: (prev?.n ?? 0) + 1, text: `${action} · ${target}${meta ? ` — ${meta}` : ""}` }));
  }

  return (
    <section className="card settings-card">
      <div className="card-h">
        <div>
          <div className="ct">Settings</div>
          <div className="cs">Your account, client &amp; team credentials, roles &amp; access — one control panel.</div>
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
        {tab === "clients" && <ClientCredentials />}
        {tab === "team" && <TeamCredentials onLog={onLog} />}
        {tab === "access" && (panelGuard(rbacQ) ?? <AccessControl rolePerms={rolePerms} />)}
      </div>

      {toast && (
        <div className="set-toast" key={toast.n} role="status">
          <span className="material-symbols-rounded">check_circle</span>
          <span className="st-txt">{toast.text}</span>
        </div>
      )}
    </section>
  );
}
