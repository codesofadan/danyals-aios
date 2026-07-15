"use client";

import TopBar from "@/components/TopBar";
import ClientReports from "@/components/client/ClientReports";

export default function ClientReportsPage() {
  return (
    <>
      <TopBar eyebrow="Client · Reports" title="Reports Library" searchPlaceholder="Search reports…" />
      <ClientReports />
    </>
  );
}
