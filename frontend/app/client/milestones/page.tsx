"use client";

import TopBar from "@/components/TopBar";
import ClientMilestones from "@/components/client/ClientMilestones";

export default function ClientMilestonesPage() {
  return (
    <>
      <TopBar eyebrow="Client · Milestones" title="Project Progress" searchPlaceholder="Jump to…" />
      <ClientMilestones />
    </>
  );
}
