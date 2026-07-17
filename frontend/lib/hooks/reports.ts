"use client";

// ============================================================
// AIOS · Reports module (7D) data hooks
// Backs the Reports workspace off the FastAPI /reports endpoints instead of the
// build-time `reports.ts` seeds. Workbook / SyncEvent / ReportType are contract-
// locked to their response models (test_contract_lock), so the JSON drops straight
// into the existing types — no field mapping.
//
// Reads require any provisioned staff (view_reports); syncing (the push to Sheets)
// is lead-only (owner/admin/manager) — a 403 there surfaces via the mutation error.
// A sync is OPTIMISTIC server-side (buffer flush → per-dataset events → status flips
// to `synced`); with no Google key it degrades (0 rows pushed) but still flips.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Workbook, SyncEvent, ReportType } from "@/lib/reports";

export const WORKBOOKS_KEY = ["reports", "workbooks"] as const;
export const SYNC_EVENTS_KEY = ["reports", "sync-events"] as const;
export const REPORT_TYPES_KEY = ["reports", "types"] as const;
export const CONNECTION_KEY = ["reports", "connection"] as const;

// The Sheets-connection panel shape (GET /reports/connection ≡ ConnectionResponse).
// `reports.ts` `sheetsConnection` is a plain const (not an exported type), so the
// shape is pinned here to match the backend response one-for-one.
export type SheetsConnectionData = {
  account: string;
  accountShort: string;
  project: string;
  scope: string;
  connected: boolean;
  master: { name: string; sheet: string; tabs: number };
  buffer: { label: string; ok: boolean; queued: number; flushedToday: number };
};

/** The per-client workbooks, freshest sync first (GET /reports/workbooks). */
export function useWorkbooks() {
  return useQuery({
    queryKey: WORKBOOKS_KEY,
    queryFn: () => api.get<Workbook[]>("/reports/workbooks"),
  });
}

/** Recent sync pushes, newest first (GET /reports/sync-events). */
export function useSyncEvents() {
  return useQuery({
    queryKey: SYNC_EVENTS_KEY,
    queryFn: () => api.get<SyncEvent[]>("/reports/sync-events"),
  });
}

/** The static report-type catalogue (GET /reports/types). */
export function useReportTypes() {
  return useQuery({
    queryKey: REPORT_TYPES_KEY,
    queryFn: () => api.get<ReportType[]>("/reports/types"),
  });
}

/** The Sheets connection panel: service account, master rollup, buffer stats
 *  (GET /reports/connection). `connected` is true only with a real credential. */
export function useConnection() {
  return useQuery({
    queryKey: CONNECTION_KEY,
    queryFn: () => api.get<SheetsConnectionData>("/reports/connection"),
  });
}

/** Push ONE workbook to its sheet (lead-only, optimistic → synced). On success the
 *  workbooks + sync-events + connection buffer refetch. */
export function useSyncWorkbook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workbookId: string) => api.post<Workbook>("/reports/sync", { workbookId }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WORKBOOKS_KEY });
      void qc.invalidateQueries({ queryKey: SYNC_EVENTS_KEY });
      void qc.invalidateQueries({ queryKey: CONNECTION_KEY });
    },
  });
}

/** Push EVERY client workbook (lead-only, optimistic → synced). */
export function useSyncAllWorkbooks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Workbook[]>("/reports/sync-all"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WORKBOOKS_KEY });
      void qc.invalidateQueries({ queryKey: SYNC_EVENTS_KEY });
      void qc.invalidateQueries({ queryKey: CONNECTION_KEY });
    },
  });
}
