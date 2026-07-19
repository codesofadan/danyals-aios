"use client";

// ============================================================
// AIOS · Command Center data hook (admin OVERVIEW read-swap)
// Backs the admin landing page off the single FastAPI aggregate
// `GET /api/v1/command-center` instead of the build-time seeds
// (`audits` / `traffic` / `team` / `clients` in lib/data.ts, the
// budget seeds in lib/cost.ts, and the recommendations in
// lib/policy.ts). One read feeds the stat tiles, the four charts,
// the Policy-Radar digest and the spend snapshot.
//
// The types below mirror `CommandCenterResponse`
// (backend/app/schemas/command_center.py) EXACTLY as SERIALIZED —
// i.e. the camelCase `serialization_alias` keys (`statTiles`,
// `deltaDir`, `totalSpent`, `totalCap`, `dailyStop`).
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Recommendation } from "@/lib/policy";

// One KPI tile — mirrors StatTile (== frontend StatTiles `Tile`).
export type CCStatTile = {
  icon: string;
  label: string;
  value: number;
  unit?: string;
  delta: string;
  deltaDir: "up" | "down";
  note: string;
  hero?: boolean;
};

// Weekly audit-volume point (== AuditPoint).
export type CCAuditPoint = { w: string; v: number };

// Monthly traffic point (== TrafficPoint).
export type CCTrafficPoint = { m: string; v: number };

// Traffic series WRAPPED with the placeholder flag (N8): audits are URL-only, so
// `points` is an audit-derived ESTIMATE and `placeholder` is always true for now.
export type CCTrafficSeries = { placeholder: boolean; points: CCTrafficPoint[] };

// Per-member job bar (== TeamPoint / frontend TeamMember).
export type CCTeamPoint = { nm: string; init: string; c: string; jobs: number };

// Client-progress row (== ClientPoint / frontend Client).
export type CCClientPoint = { cn: string; cd: string; p: number };

// One near/over-cap client in the spend snapshot (== SpendFlag).
export type CCSpendFlag = { cn: string; spent: number; cap: number; pct: number; c: string };

// Platform month-to-date spend rollup (== SpendSnapshot).
export type CCSpendSnapshot = {
  totalSpent: number;
  totalCap: number;
  pct: number;
  flagged: CCSpendFlag[];
  dailyStop: number;
  halted: boolean;
};

// Agency-wide Search Console rollup (== GscSummary, 7C). `placeholder` is
// honest in the OPPOSITE direction from traffic's: real once connected, never
// an estimate — it's just false-by-default until at least one property is.
export type CCGscSummary = {
  placeholder: boolean;
  connected: number;
  total: number;
  clicks28d: number;
  impressions28d: number;
};

// Agency-wide GA4 rollup (== Ga4Summary). Mirrors CCGscSummary exactly.
export type CCGa4Summary = {
  placeholder: boolean;
  connected: number;
  total: number;
  sessions28d: number;
  users28d: number;
};

// The whole admin-home payload (a COMPOSITE — CommandCenterResponse). `digest`
// reuses the already-locked `Recommendation` (== RecommendationResponse, 11 keys).
export type CommandCenter = {
  statTiles: CCStatTile[];
  audits: CCAuditPoint[];
  traffic: CCTrafficSeries;
  team: CCTeamPoint[];
  clients: CCClientPoint[];
  digest: Recommendation[];
  spend: CCSpendSnapshot;
  gsc: CCGscSummary;
  ga4: CCGa4Summary;
};

export const COMMAND_CENTER_KEY = ["command-center"] as const;

/** The admin-home aggregate: KPI tiles + four chart series + digest + spend. */
export function useCommandCenter() {
  return useQuery({
    queryKey: COMMAND_CENTER_KEY,
    queryFn: () => api.get<CommandCenter>("/command-center"),
  });
}
