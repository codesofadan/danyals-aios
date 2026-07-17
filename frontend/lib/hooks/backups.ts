"use client";

// ============================================================
// AIOS · Backups data hooks
// Backs BackupsWorkspace off the FastAPI /backups endpoints instead of the
// build-time `snapshots` + `backupConfig` seeds. SnapshotResponse ↔ Snapshot is
// contract-locked, and the config wire shape mirrors the `backupConfig` const.
//
// The `protectedStores` / `storage` / `resilience` catalogues are static
// (the backend serves /backups/stores + /backups/storage as static catalogues)
// and stay local in `@/lib/backups`, like the vault `providers` catalogue.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Snapshot, SnapType } from "@/lib/backups";

export const SNAPSHOTS_KEY = ["backups", "snapshots"] as const;
export const BACKUP_CONFIG_KEY = ["backups", "config"] as const;

// Mirrors the `backupConfig` const object in `@/lib/backups` (a const, not an
// exported type) — the derived counters + schedule toggles GET /backups/config
// returns. Defined here (a hook file) rather than editing the lib type file.
export type BackupConfig = {
  nightlyTime: string;
  retentionDays: number;
  retained: number;
  lastBackupAgoH: number;
  nextBackupInH: number;
  restoreTested: string;
  nightlyOn: boolean;
  offsiteOn: boolean;
};

/** The snapshot ledger, most recent first (GET /backups/snapshots → Snapshot[]). */
export function useSnapshots() {
  return useQuery({
    queryKey: SNAPSHOTS_KEY,
    queryFn: () => api.get<Snapshot[]>("/backups/snapshots"),
  });
}

/** The backup config panel: schedule + toggles + derived counters (GET /backups/config). */
export function useBackupConfig() {
  return useQuery({
    queryKey: BACKUP_CONFIG_KEY,
    queryFn: () => api.get<BackupConfig>("/backups/config"),
  });
}

export type RunBackupInput = { type: SnapType; scope: string };

/**
 * Kick off a manual snapshot now (POST /backups/run, owner/admin). On success
 * the ledger + config refetch so the new row and last-backup counter update.
 */
export function useRunBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: RunBackupInput) => api.post<Snapshot>("/backups/run", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SNAPSHOTS_KEY });
      void qc.invalidateQueries({ queryKey: BACKUP_CONFIG_KEY });
    },
  });
}
