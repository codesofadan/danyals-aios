"use client";

import TopBar from "@/components/TopBar";
import ClientRequests from "@/components/client/ClientRequests";

export default function ClientRequestsPage() {
  return (
    <>
      <TopBar eyebrow="Client · Requests" title="Requests" searchPlaceholder="Search requests…" />
      <ClientRequests />
    </>
  );
}
