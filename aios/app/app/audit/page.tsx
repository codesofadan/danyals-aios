import TopBar from "@/components/TopBar";
import "./audit.css";
import AuditWorkspace from "@/components/audit/AuditWorkspace";

export default function AuditPage() {
  return (
    <>
      <TopBar
        eyebrow="Modules · Audit Engine"
        title="Audit"
        searchPlaceholder="Search audits, clients, URLs…"
      />
      <AuditWorkspace />
    </>
  );
}
