import TopBar from "@/components/TopBar";
import "./reports.css";
import ReportsWorkspace from "@/components/reports/ReportsWorkspace";

export default function ReportsPage() {
  return (
    <>
      <TopBar
        eyebrow="Delivery · Reporting"
        title="Reports"
        searchPlaceholder="Search workbooks, clients, datasets…"
      />
      <ReportsWorkspace />
    </>
  );
}
