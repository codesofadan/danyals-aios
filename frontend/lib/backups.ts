// ============================================================
// AIOS · Backups & Restore data layer
// Grounded in the documentation:
//   • System Architecture §09 (Resilience): "Nightly Postgres
//     backups, container restart policies, documented restore,
//     TLS everywhere." Artifacts live on the VPS volume.
//   • Responsibility Matrix: the agency owns the server and
//     "backups you choose to keep or turn off".
//   • Data Model §07: what lives in Postgres (app data + KB).
// Swap these mocks for the FastAPI /backups endpoints later.
// ============================================================

export type SnapStatus = "success" | "running" | "failed";
export type SnapType = "Nightly" | "Manual";

export type Snapshot = {
  id: string;
  ts: string; // display timestamp
  type: SnapType;
  scope: string; // "Database" | "Full (DB + files)"
  size: string; // "1.82 GB" | "—"
  duration: string;
  status: SnapStatus;
};

export type ProtectedStore = {
  key: string;
  name: string;
  desc: string;
  icon: string;
  size: string;
  included: boolean;
  note?: string;
};

export const protectedStores: ProtectedStore[] = [
  {
    key: "postgres",
    name: "Postgres database",
    desc: "App data + knowledge base — clients, sites, audits, content jobs, milestones, and the Policy Radar KB.",
    icon: "database",
    size: "—",
    included: true,
  },
  {
    key: "files",
    name: "File artifacts",
    desc: "Audit PDFs, generated content packages and AI images on the VPS volume.",
    icon: "folder_zip",
    size: "—",
    included: true,
  },
  {
    key: "vault",
    name: "Encrypted key vault",
    desc: "API keys + WordPress credentials (encrypted app-layer vault) — never in logs.",
    icon: "lock",
    size: "—",
    included: true,
  },
  {
    key: "redis",
    name: "Redis · queue + cache",
    desc: "Job queue and cached API responses — ephemeral, rebuilt on restart.",
    icon: "bolt",
    size: "—",
    included: false,
    note: "Ephemeral · not backed up",
  },
];

export const backupConfig = {
  nightlyTime: "02:00 UTC",
  retentionDays: 30,
  retained: 30,
  lastBackupAgoH: 6, // hours since last successful backup
  nextBackupInH: 18, // hours until tonight's run
  restoreTested: "Jul 02, 2026",
  nightlyOn: true,
  offsiteOn: false,
};

export type StorageSeg = { key: string; label: string; gb: number; color: string };
// No fabricated storage usage — real disk measurement is not wired yet.
export const storage = {
  totalGB: 100, // VPS volume
  segments: [] as StorageSeg[],
};
export const storageUsedGB = storage.segments.reduce((s, x) => s + x.gb, 0);

// From System Architecture §09 (Resilience + Security).
export const resilience: string[] = [
  "Nightly Postgres backups",
  "Container restart policies",
  "Documented restore runbook",
  "TLS everywhere (Caddy auto-TLS)",
  "Encrypted key vault — keys never logged",
];
