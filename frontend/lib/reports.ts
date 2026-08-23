// ============================================================
// AIOS · Reports module — the Google Sheets reporting layer.
// v1 reporting runs on Google Sheets via a service account:
// one workbook per client + a master rollup workbook. The
// audit / content / milestone modules push here through a
// Redis write-buffer; the engine applies agency branding.
// Mock values are demo-only — swap for the FastAPI service +
// Sheets API (googleapis) queries when the backend is wired.
// ============================================================

import { SERIES } from "@/lib/data";

// --- Datasets pushed to each workbook ---------------------------------------
export type Dataset = "audit" | "content" | "milestones";

export const DATASET_META: Record<Dataset, { label: string; icon: string; c: string }> = {
  audit: { label: "Audit", icon: "fact_check", c: SERIES.c4 },
  content: { label: "Content", icon: "article", c: SERIES.c3 },
  milestones: { label: "Milestones", icon: "flag", c: SERIES.c1 },
};

// --- Sync state -------------------------------------------------------------
export type SyncStatus = "synced" | "syncing" | "error";

export const STATUS_META: Record<SyncStatus, { label: string; cls: string }> = {
  synced: { label: "Synced", cls: "ok" },
  syncing: { label: "Syncing", cls: "info" },
  error: { label: "Error", cls: "warn" },
};

// --- Per-client workbooks ---------------------------------------------------
export type Workbook = {
  id: string;
  client: string;
  sheet: string; // sheet-id fragment shown in the "open sheet" affordance
  tabs: Dataset[]; // tabs kept in sync on this workbook
  rows: number; // rows synced today across all tabs
  lastSync: string; // relative
  status: SyncStatus;
};

// --- Service account + master workbook (the Sheets connection) --------------
export const sheetsConnection = {
  account: "aios-sheets@aios-prod.iam.gserviceaccount.com",
  accountShort: "aios-sheets@…iam.gserviceaccount.com",
  project: "aios-prod",
  scope: "spreadsheets · drive.file",
  connected: true,
  master: {
    name: "AIOS · Master Rollup",
    sheet: "1M4st…RollupX",
    tabs: 5, // Clients · Audits · Content · Milestones · Health
  },
  buffer: {
    // Redis acts as the write-buffer in front of the Sheets API.
    label: "Redis write-buffer",
    ok: true,
    queued: 3, // rows waiting to flush
    flushedToday: 2174,
  },
};

// --- What each report type writes to the sheet ------------------------------
export type ReportType = {
  key: Dataset;
  title: string;
  desc: string;
  columns: string; // the columns written to the tab
};

// --- Recent sync activity (pushes to Sheets) --------------------------------
export type SyncEvent = {
  id: string;
  client: string;
  dataset: Dataset;
  rows: number;
  ago: string;
};
