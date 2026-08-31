"use client";

// Platform settings. Tabs are URL-owned; access narrows per tab (workspace is
// owner/admin - a 403 renders as the guard's failure state).
//
// QA removed Security and the Danger zone from the admin portal: neither is a
// control the agency operates from here. Both panels are kept (parked), and the
// agency-global routes behind them are untouched - this is a change to what the
// portal SURFACES, not to what the platform can do.

import TabBar, { useUrlTab } from "@/components/ui/TabBar";
import AccountSettings from "./AccountSettings";
import WorkspaceTab from "./WorkspaceTab";
import ExtensionTab from "./ExtensionTab";

const TABS = [
  { key: "account", label: "My account", icon: "person" },
  { key: "workspace", label: "Workspace", icon: "corporate_fare" },
  { key: "extension", label: "Extension", icon: "extension" },
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
            {tab === "extension" && "Pair the Citation Assistant browser extension."}
          </div>
        </div>
      </div>
      <TabBar tabs={TABS} active={tab} onSelect={setTab} />
      <div className="tw-panel" style={{ marginTop: 14 }}>
        {tab === "account" && <AccountSettings />}
        {tab === "workspace" && <WorkspaceTab />}
        {tab === "extension" && <ExtensionTab />}
      </div>
    </section>
  );
}
