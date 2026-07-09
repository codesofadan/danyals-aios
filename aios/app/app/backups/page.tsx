import type { Metadata } from "next";
import TopBar from "@/components/TopBar";
import BackupsWorkspace from "@/components/backups/BackupsWorkspace";

export const metadata: Metadata = {
  title: "Backups & Restore · AIOS",
  description: "Nightly Postgres backups, file-artifact snapshots, documented restore and resilience — all owned by the agency.",
};

export default function BackupsPage() {
  return (
    <>
      <TopBar
        eyebrow="Platform · Infrastructure"
        title="Backups & Restore"
        searchPlaceholder="Search snapshots…"
      />
      <BackupsWorkspace />
    </>
  );
}
