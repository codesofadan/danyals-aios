"use client";

import TopBar from "@/components/TopBar";
import ClientPages from "@/components/client/ClientPages";

export default function ClientPagesPage() {
  return (
    <>
      <TopBar eyebrow="Client · Content" title="Your Pages" searchPlaceholder="Jump to…" />
      <ClientPages />
    </>
  );
}
