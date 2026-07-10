import TopBar from "@/components/TopBar";
import "./content.css";
import ContentWorkspace from "@/components/content/ContentWorkspace";

export default function ContentModule() {
  return (
    <>
      <TopBar
        eyebrow="Automation · Content Engine"
        title="Content"
        searchPlaceholder="Search jobs, clients, topics…"
      />
      <ContentWorkspace />
    </>
  );
}
