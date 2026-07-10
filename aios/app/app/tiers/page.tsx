import TopBar from "@/components/TopBar";
import "./tiers.css";
import TiersWorkspace from "@/components/tiers/TiersWorkspace";

export default function TiersPage() {
  return (
    <>
      <TopBar
        eyebrow="Platform · Service Tiers"
        title="Service Tiers"
        searchPlaceholder="Search clients, tiers, features…"
      />
      <TiersWorkspace />
    </>
  );
}
