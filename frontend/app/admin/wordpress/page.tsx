import TopBar from "@/components/TopBar";
import WpConnections from "@/components/wordpress/WpConnections";

// WordPress: the sites we publish through.
//
// The Design Replicator card used to sit under this table, which made design work a
// second place an operator had to go: replicate here, then start again in Content to
// build anything on what was measured. It is now one flow - screen 3 of
// /admin/content/new offers all three design sources (measure the client's site,
// replicate any URL, reuse an earlier replication) - so design lives where the pages
// that use it are made. The component is kept and recorded in parked.registry.ts;
// what is gone is the second door, not the capability.
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
    </>
  );
}
