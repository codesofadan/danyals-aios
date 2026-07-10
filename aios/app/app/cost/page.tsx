import TopBar from "@/components/TopBar";
import "./cost.css";
import CostWorkspace from "@/components/cost/CostWorkspace";

export default function CostControls() {
  return (
    <>
      <TopBar
        eyebrow="Platform · Cost Controls"
        title="Cost Controls"
        searchPlaceholder="Search clients, jobs, providers…"
      />

      <CostWorkspace />
    </>
  );
}
