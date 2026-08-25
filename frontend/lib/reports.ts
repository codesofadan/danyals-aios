// ============================================================
// AIOS · Reports module — the Google Sheets reporting layer.
// v1 reporting runs on Google Sheets via a service account:
// one workbook per client + a master rollup workbook. The
// audit / content / milestone modules push here through a
// Redis write-buffer; the engine applies agency branding.
//
// This module holds TYPES and pure display helpers only. It used to also export a
// `sheetsConnection` const carrying a fabricated service-account address, project id,
// `connected: true`, and buffer counters (`queued: 3`, `flushedToday: 2174`). Nothing
// imported it - GET /reports/connection had already replaced it - so it shipped
// invented infrastructure state to every browser that loaded the bundle. Removed.
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

// --- Opening a workbook in Google Sheets ------------------------------------
// The "open sheet" affordances used to be `href="#"` - a link that looked live,
// took the operator nowhere, and gave no hint that the id beside it was real.
// A sheet id IS the URL, so there is nothing to fetch.
//
// Returns null when there is no id (an unconfigured master, a workbook that has
// never synced). Callers must render a non-interactive state for null rather than
// a link to nowhere.
export function sheetUrl(sheetId: string | null | undefined): string | null {
  const id = (sheetId ?? "").trim();
  return id ? `https://docs.google.com/spreadsheets/d/${encodeURIComponent(id)}` : null;
}

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
