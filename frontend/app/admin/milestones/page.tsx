import TopBar from "@/components/TopBar";
import "./milestones.css";
import MilestoneStats from "@/components/milestones/MilestoneStats";
import MilestonesWorkspace from "@/components/milestones/MilestonesWorkspace";

// Restored 2026-08-25. The tab was removed in 158c204 along with five others, but the
// components were kept — and the removal left the agency unable to see the delivery
// timeline it SHOWS ITS CLIENTS at /client/milestones. Reinstating it is a deliberate
// reversal of that decision, not an oversight being corrected.
//
// Read-only by construction: `/milestones` exposes no write endpoint, because stages
// are meant to advance from delivery events. Only the onboarding stage actually does
// today (`advance_stage` has exactly one caller, in client_onboarding/service.py), so
// the board states that plainly rather than implying a pipeline that is running. The
// event wiring is a separate, coordinated change — it has to reach into the audit and
// content completion paths, which are under active construction.
export default function Milestones() {
  return (
    <>
      <TopBar
        eyebrow="Delivery · Project Milestones"
        title="Milestones"
        searchPlaceholder="Search projects, clients, stages…"
        hideSearch
      />

      <MilestoneStats />

      <MilestonesWorkspace />
    </>
  );
}
