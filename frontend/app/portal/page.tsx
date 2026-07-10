"use client";

import TopBar from "@/components/TopBar";
import DashboardHome from "@/components/portal/DashboardHome";

export default function PortalDashboard() {
  return (
    <>
      <TopBar eyebrow="Team Portal · My Workspace" title="Dashboard" searchPlaceholder="Search my tasks, clients…" />
      <DashboardHome />
    </>
  );
}
