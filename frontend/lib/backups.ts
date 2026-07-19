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

// Most recent first. Nightly = Postgres (app data + KB) + vault;
// a weekly/manual "Full" also captures the file artifacts volume.
export const snapshots: Snapshot[] = [
  { id: "bk-0710-0200", ts: "Today · 02:00", type: "Nightly", scope: "Database", size: "1.82 GB", duration: "3m 48s", status: "success" },
  { id: "bk-0709-0200", ts: "Yesterday · 02:00", type: "Nightly", scope: "Database", size: "1.80 GB", duration: "3m 41s", status: "success" },
  { id: "bk-0708-1520", ts: "Jul 08 · 15:20", type: "Manual", scope: "Full (DB + files)", size: "40.9 GB", duration: "21m 12s", status: "success" },
  { id: "bk-0708-0200", ts: "Jul 08 · 02:00", type: "Nightly", scope: "Database", size: "1.79 GB", duration: "3m 39s", status: "success" },
  { id: "bk-0707-0200", ts: "Jul 07 · 02:00", type: "Nightly", scope: "Database", size: "1.78 GB", duration: "3m 44s", status: "success" },
  { id: "bk-0706-0200", ts: "Jul 06 · 02:00", type: "Nightly", scope: "Database", size: "—", duration: "0m 18s", status: "failed" },
  { id: "bk-0705-0200", ts: "Jul 05 · 02:00", type: "Nightly", scope: "Database", size: "1.76 GB", duration: "3m 52s", status: "success" },
];

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
