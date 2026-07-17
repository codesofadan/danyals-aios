"use client";

// ============================================================
// AIOS · off-page data hooks
// Backs the Off-page workspace (Backlinks / Citations / Web 2.0 + KPIs) off the
// FastAPI /offpage endpoints instead of the build-time seeds. Backlink / Citation /
// Web2Property are contract-locked to their responses (camelCase aliases match), so
// the JSON drops straight into the existing types — no field mapping. The one write
// the UI performs is the citation bulk-reconcile.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Backlink, Citation, Web2Property } from "@/lib/offpage";

export const BACKLINKS_KEY = ["offpage", "backlinks"] as const;
export const CITATIONS_KEY = ["offpage", "citations"] as const;
export const WEB2_KEY = ["offpage", "web2"] as const;
export const OFFPAGE_KPIS_KEY = ["offpage", "kpis"] as const;

// GET /offpage/kpis → OffpageKpisResponse (serialized camelCase). No exported TS
// type on the value side, so it is mirrored here.
export type OffpageKpis = {
  referringDomains: number;
  newLinks30d: number;
  lostLinks30d: number;
  toxicFlagged: number;
};

/** The referring-domain profile (freshest first). */
export function useBacklinks() {
  return useQuery({
    queryKey: BACKLINKS_KEY,
    queryFn: () => api.get<Backlink[]>("/offpage/backlinks"),
  });
}

/** The local directory / NAP listings. */
export function useCitations() {
  return useQuery({
    queryKey: CITATIONS_KEY,
    queryFn: () => api.get<Citation[]>("/offpage/citations"),
  });
}

/** The Web 2.0 property ledger (newest-published first). */
export function useWeb2() {
  return useQuery({
    queryKey: WEB2_KEY,
    queryFn: () => api.get<Web2Property[]>("/offpage/web2"),
  });
}

/** The off-page summary tiles (live profile size + 30-day deltas + disavow queue). */
export function useOffpageKpis() {
  return useQuery({
    queryKey: OFFPAGE_KPIS_KEY,
    queryFn: () => api.get<OffpageKpis>("/offpage/kpis"),
  });
}

/**
 * Reconcile many NAP listings to `consistent` in one shot (a batch Submit/Update).
 * Lead-only at the backend. `retry: 0` (client default) so a transient failure never
 * silently double-submits. On success the citations list + KPIs refetch.
 */
export function useBulkUpdateCitations() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.post<Citation[]>("/offpage/citations/bulk", { ids }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
    },
  });
}
