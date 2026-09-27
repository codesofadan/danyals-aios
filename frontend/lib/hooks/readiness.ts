"use client";

// ============================================================
// AIOS · Readiness board (GET /integrations/readiness)
// What this deploy will REALLY deliver if the operator launches work right now -
// per capability, not per key. Any staff role may read it: the person about to run
// a deep audit needs to know whether off-page will be measured, and that answer
// names no credential.
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const READINESS_KEY = ["integrations", "readiness"] as const;

/** One thing that will not happen, why, and the single action that fixes it. */
export type PreflightGap = {
  what: string;
  why: string;
  fix: string;
  /** `blocks` = the run is refused / produces nothing. `degrades` = it runs, thinner. */
  severity: "blocks" | "degrades";
};

export type PreflightCapability = {
  id: string;
  name: string;
  group: string; // "Audit" | "Content"
  verdict: "ready" | "partial" | "blocked";
  summary: string;
  measures: string[];
  gaps: PreflightGap[];
};

export type PreflightBoard = {
  spendHalted: boolean;
  ready: number;
  partial: number;
  blocked: number;
  capabilities: PreflightCapability[];
};

/**
 * The readiness board. Cached for a minute: it reads config, the dials and the engine's
 * env — all things that change when a human changes them, not per second.
 */
export function useReadiness() {
  return useQuery({
    queryKey: READINESS_KEY,
    queryFn: () => api.get<PreflightBoard>("/integrations/readiness"),
    staleTime: 60_000,
  });
}
