"use client";

// ============================================================
// AIOS · the keyword bank, finally readable
//
// The keyword module stores researched keywords with volume, difficulty, intent
// and cluster membership. Six of its nine endpoints had NO caller anywhere in the
// product - including the entire clustering read surface - so the content flow
// re-researched from scratch every time and threw the results away.
//
// These are the reads the content flow needs to pick pages from what has already
// been researched, instead of guessing.
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type BankKeyword = {
  code: string;
  keyword: string;
  client: string;
  volume: number;
  difficulty: number;
  cpc: number;
  intent: string;
  cluster: string;
  opportunity: number;
  winnable: boolean;
  targetUrl: string;
  geo: string;
};

export type KeywordCluster = {
  name: string;
  pillar: string;
  intent: string;
  size: number;
  volume: number;
  avgDifficulty: number;
  client: string;
};

export type KeywordStats = { saved: number; clusters: number; avgDifficulty: number };

/** The bank, optionally narrowed to one client. Capped explicitly: the backend
 *  paginates at 50 by default and 200 max, and a silent 50 would present a
 *  partial bank as the whole thing. */
export function useKeywordBank(clientId: string | null, enabled = true) {
  const qs = new URLSearchParams({ limit: "200" });
  if (clientId) qs.set("clientId", clientId);
  return useQuery({
    queryKey: ["keyword-bank", clientId ?? "all"] as const,
    queryFn: () => api.get<BankKeyword[]>(`/keyword-research/keywords?${qs}`),
    enabled,
  });
}

export function useKeywordClusters(clientId: string | null, enabled = true) {
  const qs = new URLSearchParams({ limit: "200" });
  if (clientId) qs.set("clientId", clientId);
  return useQuery({
    queryKey: ["keyword-clusters", clientId ?? "all"] as const,
    queryFn: () => api.get<KeywordCluster[]>(`/keyword-research/clusters?${qs}`),
    enabled,
  });
}

export function useKeywordStats(enabled = true) {
  return useQuery({
    queryKey: ["keyword-stats"] as const,
    queryFn: () => api.get<KeywordStats>("/keyword-research/stats"),
    enabled,
  });
}
