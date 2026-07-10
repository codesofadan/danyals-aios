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

// Eight live client workbooks — names mirror the client directory.
export const workbooks: Workbook[] = [
  { id: "wb-northpeak", client: "NorthPeak Dental", sheet: "1a7Fq…D4x", tabs: ["audit", "content", "milestones"], rows: 428, lastSync: "2m ago", status: "synced" },
  { id: "wb-lumen", client: "Lumen Realty", sheet: "1kR2p…9Lm", tabs: ["audit", "content", "milestones"], rows: 512, lastSync: "4m ago", status: "synced" },
  { id: "wb-verde", client: "Verde Cafe", sheet: "1Zx8t…Qw3", tabs: ["audit", "milestones"], rows: 96, lastSync: "syncing…", status: "syncing" },
  { id: "wb-atlas", client: "Atlas Legal", sheet: "1Nm4v…7Hs", tabs: ["audit", "content", "milestones"], rows: 0, lastSync: "1h ago", status: "error" },
  { id: "wb-brighthvac", client: "BrightHVAC", sheet: "1Pd6y…B2k", tabs: ["audit", "content", "milestones"], rows: 337, lastSync: "8m ago", status: "synced" },
  { id: "wb-coastline", client: "Coastline Fit", sheet: "1Tg9w…M5r", tabs: ["audit", "content"], rows: 154, lastSync: "12m ago", status: "synced" },
  { id: "wb-meridian", client: "Meridian Wealth", sheet: "1Yh3s…C8n", tabs: ["audit", "content", "milestones"], rows: 604, lastSync: "3m ago", status: "synced" },
  { id: "wb-orchard", client: "Orchard Pediatrics", sheet: "1Ub5j…F1q", tabs: ["milestones"], rows: 42, lastSync: "34m ago", status: "synced" },
];

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

export const reportTypes: ReportType[] = [
  {
    key: "audit",
    title: "Audit scores",
    desc: "Every free & paid audit run, rolled up per site.",
    columns: "Site · Category · Score · Δ vs last · Issues · Fixed · Run date",
  },
  {
    key: "content",
    title: "Content status",
    desc: "Content-job pipeline state as drafts move to live.",
    columns: "Job · Type · Stage · Assignee · Words · Published URL · Updated",
  },
  {
    key: "milestones",
    title: "Milestone state",
    desc: "Onboarding & delivery milestones per engagement.",
    columns: "Milestone · Owner · Due · Status · Completed · Progress %",
  },
];

// --- Recent sync activity (pushes to Sheets) --------------------------------
export type SyncEvent = {
  id: string;
  client: string;
  dataset: Dataset;
  rows: number;
  ago: string;
};

export const syncActivity: SyncEvent[] = [
  { id: "s-01", client: "Meridian Wealth", dataset: "audit", rows: 128, ago: "3m ago" },
  { id: "s-02", client: "NorthPeak Dental", dataset: "content", rows: 46, ago: "2m ago" },
  { id: "s-03", client: "Lumen Realty", dataset: "milestones", rows: 12, ago: "4m ago" },
  { id: "s-04", client: "BrightHVAC", dataset: "audit", rows: 214, ago: "8m ago" },
  { id: "s-05", client: "Coastline Fit", dataset: "content", rows: 33, ago: "12m ago" },
  { id: "s-06", client: "Master Rollup", dataset: "milestones", rows: 61, ago: "16m ago" },
  { id: "s-07", client: "Orchard Pediatrics", dataset: "milestones", rows: 42, ago: "34m ago" },
  { id: "s-08", client: "Lumen Realty", dataset: "audit", rows: 176, ago: "41m ago" },
];
