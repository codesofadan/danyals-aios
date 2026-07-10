import TopBar from "@/components/TopBar";
import "./milestones.css";
import MilestoneStats from "@/components/milestones/MilestoneStats";
import MilestonesWorkspace from "@/components/milestones/MilestonesWorkspace";

export default function Milestones() {
  return (
    <>
      <TopBar
        eyebrow="Delivery · Project Milestones"
        title="Milestones"
        searchPlaceholder="Search projects, clients, stages…"
      />

      <MilestoneStats />

      <MilestonesWorkspace />
    </>
  );
}
