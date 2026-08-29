"use client";

// Platform settings, restructured: the six agency-global routes
// (workspace / security / danger) had ZERO callers while this screen showed
// only My Account. Tabs are URL-owned; access narrows per tab (workspace +
// security are owner/admin - a 403 renders as the guard's failure state - and
// the danger zone is owner-only).

import TabBar, { useUrlTab } from "@/components/ui/TabBar";
import AccountSettings from "./AccountSettings";
import WorkspaceTab from "./WorkspaceTab";
import ExtensionTab from "./ExtensionTab";
import SecurityTab from "./SecurityTab";
import DangerTab from "./DangerTab";

const TABS = [
  { key: "account", label: "My account", icon: "person" },
  { key: "workspace", label: "Workspace", icon: "corporate_fare" },
  { key: "security", label: "Security", icon: "shield_lock" },
  { key: "extension", label: "Extension", icon: "extension" },
  { key: "danger", label: "Danger zone", icon: "report" },
];

export default function SettingsWorkspace() {
  const [tab, setTab] = useUrlTab(TABS);

  return (
    <section className="card settings-card">
      <div className="card-h">
        <div>
          <div className="ct">Settings</div>
          <div className="cs">
            {tab === "account" && "Your profile & notification preferences."}
            {tab === "workspace" && "Agency-wide identity and defaults (owner/admin)."}
            {tab === "security" && "The agency's stored security policy (owner/admin)."}
            {tab === "extension" && "Pair the Citation Assistant browser extension."}
            {tab === "danger" && "Irreversible platform actions (owner only)."}
          </div>
        </div>
      </div>
      <TabBar tabs={TABS} active={tab} onSelect={setTab} />
      <div className="tw-panel" style={{ marginTop: 14 }}>
        {tab === "account" && <AccountSettings />}
        {tab === "workspace" && <WorkspaceTab />}
        {tab === "security" && <SecurityTab />}
        {tab === "extension" && <ExtensionTab />}
        {tab === "danger" && <DangerTab />}
      </div>
    </section>
  );
}
