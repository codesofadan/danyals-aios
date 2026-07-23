import TopBar from "@/components/TopBar";
import "./gmb.css";
import GmbWorkspace from "@/components/gmb/GmbWorkspace";

export default function GmbModule() {
  return (
    <>
      <TopBar
        eyebrow="Automation · Local"
        title="GMB Posts"
        searchPlaceholder="Search posts, clients, topics…"
      />
      <GmbWorkspace />
    </>
  );
}
