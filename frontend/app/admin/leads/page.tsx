import TopBar from "@/components/TopBar";
import "./leads.css";
import LeadsWorkspace from "@/components/leads/LeadsWorkspace";

export default function LeadsPage() {
  return (
    <>
      <TopBar
        eyebrow="Modules · Audit Engine"
        title="Free Audits"
        searchPlaceholder="Search leads, emails, URLs…"
      />
      <LeadsWorkspace />
    </>
  );
}
