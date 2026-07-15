"use client";

import TopBar from "@/components/TopBar";
import ClientDashboard from "@/components/client/ClientDashboard";

export default function ClientDashboardPage() {
  return (
    <>
      <TopBar eyebrow="Client · Dashboard" title="Client Dashboard" searchPlaceholder="Search your reports…" />
      <ClientDashboard />
    </>
  );
}
