import TopBar from "@/components/TopBar";
import "./site-builder.css";
import SiteBuilderWorkspace from "@/components/site-builder/SiteBuilderWorkspace";

export default function SiteBuilderModule() {
  return (
    <>
      <TopBar
        eyebrow="Automation · Website Reconstruction"
        title="Site Builder"
        searchPlaceholder="Search builds, clients, templates…"
      />
      <SiteBuilderWorkspace />
    </>
  );
}
