"use client";

// ============================================================
// AIOS · audit data hooks (the first real read-swap slice)
// Backs the AuditWorkspace off the FastAPI /audits endpoints instead of the
// build-time `audits` seed. AuditRow ↔ AuditResponse is contract-locked 11/11,
// so the JSON drops straight into the existing type — no field mapping.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuditRow, AuditTypeKey, Tier } from "@/lib/audit";

export const AUDITS_KEY = ["audits"] as const;
export const AUDIT_STATS_KEY = ["audits", "stats"] as const;

// Matches AuditStatsResponse (serialized: thisMonth/avgScore/runningNow/turnaroundMin).
export type AuditStats = {
  thisMonth: number;
  avgScore: number;
  runningNow: number;
  turnaroundMin: number;
};

const isPending = (r: AuditRow) => r.status === "queued" || r.status === "running";

/** The audit list. Polls every 2.5s WHILE any job is in flight, then stops. */
export function useAudits() {
  return useQuery({
    queryKey: AUDITS_KEY,
    queryFn: () => api.get<AuditRow[]>("/audits"),
    refetchInterval: (query) => {
      const rows = query.state.data as AuditRow[] | undefined;
      return rows?.some(isPending) ? 2500 : false;
    },
  });
}

export function useAuditStats() {
  return useQuery({
    queryKey: AUDIT_STATS_KEY,
    queryFn: () => api.get<AuditStats>("/audits/stats"),
  });
}

export type CreateAuditInput = {
  client_id: string;
  url: string;
  tier: Tier;
  types: AuditTypeKey[];
};

/**
 * Enqueue a new audit. `retry: 0` (inherited from the client's mutation default)
 * so a transient failure never silently doubles a Paid run's spend. On success the
 * list + stats refetch and the new `queued` row appears, then polls to completion.
 */
export function useCreateAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateAuditInput) => api.post<AuditRow>("/audits", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: AUDITS_KEY });
      void qc.invalidateQueries({ queryKey: AUDIT_STATS_KEY });
    },
  });
}
