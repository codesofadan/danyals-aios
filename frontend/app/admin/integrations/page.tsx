"use client";

import TopBar from "@/components/TopBar";
import "./vault.css";
import TabBar, { useUrlTab, type TabDef } from "@/components/ui/TabBar";
import VaultWorkspace from "@/components/vault/VaultWorkspace";
import BackupsWorkspace from "@/components/backups/BackupsWorkspace";

// Integrations: everything that connects this platform to the outside - the
// provider keys and the off-site backups. One `key_vault` feature used to be
// split across five surfaces; SiteAnalyticsCard even linked to /admin/settings
// expecting integrations to live there. An Analytics tab (GSC/GA4 connect)
// joins when its data wiring is done - SiteAnalyticsCard takes command-center
// props and is not yet standalone, and mounting a broken tab would be worse
// than an absent one.
const TABS: TabDef[] = [
  { key: "keys", label: "Keys", icon: "key" },
  { key: "backups", label: "Backups", icon: "cloud_done" },
];

export default function Integrations() {
  const [tab, setTab] = useUrlTab(TABS);
  return (
    <>
      <TopBar
        eyebrow="Platform · Integrations"
        title="Integrations"
        searchPlaceholder="Search keys, providers, scopes…"
      />
      <div style={{ marginBottom: "var(--s-7)" }}>
        <TabBar tabs={TABS} active={tab} onSelect={setTab} />
      </div>
      {tab === "keys" && <VaultWorkspace />}
      {tab === "backups" && <BackupsWorkspace />}
    </>
  );
}
