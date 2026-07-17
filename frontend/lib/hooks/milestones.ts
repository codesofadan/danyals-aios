"use client";

// ============================================================
// AIOS · milestones data hooks
// Backs the Milestones workspace off the FastAPI /milestones endpoints instead of
// the build-time seeds. ClientProject ↔ ClientProjectResponse and AutoAdvance ↔
// AutoAdvanceResponse are contract-locked, so the JSON drops straight into the
// existing types — no field mapping. Stages are AUTO-ADVANCED at the backend, so
// this surface is read-only (no mutations).
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AutoAdvance, ClientProject } from "@/lib/milestones";

export const MILESTONES_KEY = ["milestones"] as const;
export const AUTO_ADVANCE_KEY = ["milestones", "auto-advance"] as const;

/** The client projects with their ordered 5-stage timelines (newest first). */
export function useMilestones() {
  return useQuery({
    queryKey: MILESTONES_KEY,
    queryFn: () => api.get<ClientProject[]>("/milestones"),
  });
}

/** The recently auto-advanced feed (the most-recently-touched stages, newest first). */
export function useAutoAdvances() {
  return useQuery({
    queryKey: AUTO_ADVANCE_KEY,
    queryFn: () => api.get<AutoAdvance[]>("/milestones/auto-advance"),
  });
}
