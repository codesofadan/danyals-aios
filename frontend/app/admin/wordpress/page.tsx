import TopBar from "@/components/TopBar";
import DesignReplicator from "@/components/wordpress/DesignReplicator";
import WpConnections from "@/components/wordpress/WpConnections";

// WordPress: the sites we publish through, and the replication engine that
// rebuilds a page onto them. Stacked on one screen rather than split behind
// tabs - connecting a site and building onto it are the same sitting.
export default function WordPressPage() {
  return (
    <>
      <TopBar
        eyebrow="Admin · SEO Engine"
        title="WordPress"
        searchPlaceholder="Search clients, sites…"
        hideSearch
      />
      <WpConnections />
      <DesignReplicator />
    </>
  );
}
