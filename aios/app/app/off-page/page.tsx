import TopBar from "@/components/TopBar";
import "./offpage.css";
import OffpageWorkspace from "@/components/offpage/OffpageWorkspace";

export default function OffPage() {
  return (
    <>
      <TopBar
        eyebrow="Off-page · Backlinks, Citations & Web 2.0"
        title="Off-page SEO"
        searchPlaceholder="Search domains, citations, placements…"
      />
      <OffpageWorkspace />
    </>
  );
}
