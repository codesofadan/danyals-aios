import TopBar from "@/components/TopBar";
import WpConnections from "@/components/wordpress/WpConnections";

export default function WordPressConnectionsPage() {
  return (
    <>
      <TopBar
        eyebrow="Admin · Delivery"
        title="WordPress Connections"
        searchPlaceholder="Search clients, sites…"
        hideSearch
      />
      <WpConnections />
    </>
  );
}
