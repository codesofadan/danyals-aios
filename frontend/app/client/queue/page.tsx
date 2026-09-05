"use client";

import TopBar from "@/components/TopBar";
import ClientQueue from "@/components/client/ClientQueue";

export default function ClientQueuePage() {
  return (
    <>
      <TopBar
        eyebrow="Client · My Queue"
        title="What we're working on"
        searchPlaceholder="Jump to…"
      />
      <ClientQueue />
    </>
  );
}
