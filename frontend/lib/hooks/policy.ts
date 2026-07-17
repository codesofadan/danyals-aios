"use client";

// ============================================================
// AIOS · Policy Radar (Module 05) data hooks
// Backs the Policy Radar workspace off the FastAPI /policy endpoints instead of
// the build-time `policy.ts` seeds. Source / ChangeEvent / KBEntry / Recommendation
// are contract-locked to their response models (test_contract_lock), so the JSON
// drops straight into the existing types — no field mapping.
//
// Reads require any provisioned staff (view_reports); driving a recommendation
// (acknowledge / apply / dismiss) is lead-only (owner/admin/manager) — a 403 there
// surfaces via the mutation error. The change-detection watcher is deferred, so the
// backend serves the evergreen baseline recommendations + whatever the KB holds.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Source, ChangeEvent, KBEntry, Recommendation } from "@/lib/policy";

export const POLICY_SOURCES_KEY = ["policy", "sources"] as const;
export const POLICY_CHANGES_KEY = ["policy", "changes"] as const;
export const POLICY_KB_KEY = ["policy", "kb"] as const;
export const POLICY_RECS_KEY = ["policy", "recommendations"] as const;

/** The watched sources (GET /policy/sources). */
export function useSources() {
  return useQuery({
    queryKey: POLICY_SOURCES_KEY,
    queryFn: () => api.get<Source[]>("/policy/sources"),
  });
}

/** Detected change events, newest first (GET /policy/changes). */
export function useChanges() {
  return useQuery({
    queryKey: POLICY_CHANGES_KEY,
    queryFn: () => api.get<ChangeEvent[]>("/policy/changes"),
  });
}

/** Knowledge-base entries (GET /policy/kb). Fetched unfiltered; the KB panel
 *  filters client-side across the severity / category axes. */
export function useKb() {
  return useQuery({
    queryKey: POLICY_KB_KEY,
    queryFn: () => api.get<KBEntry[]>("/policy/kb"),
  });
}

/** The recommendation queue — DB rows merged with the evergreen baseline recs so
 *  the Command Center is never empty pre-live (GET /policy/recommendations). */
export function useRecommendations() {
  return useQuery({
    queryKey: POLICY_RECS_KEY,
    queryFn: () => api.get<Recommendation[]>("/policy/recommendations"),
  });
}

export type RecAction = "acknowledge" | "apply" | "dismiss";

/**
 * Drive a recommendation's status (lead-only: owner/admin/manager). `apply` also
 * writes the closed-loop audit overlay server-side. `retry: 0` (the client default)
 * so a transient failure never double-applies. On success the queue refetches and the
 * row's new status appears.
 */
export function useTransitionRecommendation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: RecAction }) =>
      api.post<Recommendation>(`/policy/recommendations/${id}/${action}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: POLICY_RECS_KEY });
    },
  });
}
