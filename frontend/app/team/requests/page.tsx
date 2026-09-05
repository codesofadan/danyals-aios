"use client";

import TopBar from "@/components/TopBar";
import TeamRequests from "@/components/portal/TeamRequests";

export default function TeamRequestsPage() {
  return (
    <>
      <TopBar
        eyebrow="Team Portal · Requests"
        title="Requests"
        searchPlaceholder="Jump to…"
      />
      <TeamRequests />
    </>
  );
}
