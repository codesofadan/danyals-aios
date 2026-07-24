"use client";

import TopBar from "@/components/TopBar";
import ClientAudits from "@/components/client/ClientAudits";

export default function ClientAuditsPage() {
  return (
    <>
      <TopBar eyebrow="Client · Audits" title="Your Audits" searchPlaceholder="Jump to…" />
      <ClientAudits />
    </>
  );
}
