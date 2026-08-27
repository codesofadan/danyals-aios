"use client";

import TopBar from "@/components/TopBar";
import TabBar, { useUrlTab, type TabDef } from "@/components/ui/TabBar";
import DesignReplicator from "@/components/wordpress/DesignReplicator";
import WpConnections from "@/components/wordpress/WpConnections";

// Site Builder: the job of PUTTING PAGES ON SITES, split from Content by job
// rather than by tool - Content drafts and reviews; this owns design
// replication and the WordPress connections everything publishes through.
const TABS: TabDef[] = [
  { key: "replicate", label: "Replicate", icon: "auto_fix_high" },
  { key: "wordpress", label: "WordPress", icon: "language" },
];

export default function SiteBuilder() {
  const [tab, setTab] = useUrlTab(TABS);
  return (
    <>
      <TopBar
        eyebrow="Work · Site Builder"
        title="Site Builder"
        searchPlaceholder="Search sites, connections…"
        hideSearch
      />
      <div style={{ margin: "0 26px var(--s-7)" }}>
        <TabBar tabs={TABS} active={tab} onSelect={setTab} />
      </div>
      {tab === "replicate" && <DesignReplicator />}
      {tab === "wordpress" && <WpConnections />}
    </>
  );
}
