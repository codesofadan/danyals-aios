"use client";

// ============================================================
// AIOS · cost-control data hooks
// Backs CostWorkspace off the FastAPI /cost endpoints instead of the build-time
// seeds. ClientBudget / DialFeature / CostEntry are contract-locked, so the JSON
// drops straight into the existing types.
//
// Spend HALT: /cost/spend-stop is now a single agency-global kill-switch (the old
// per-day dollar THRESHOLD was removed). The RESPONSE is camelCase
// (halted/todaySpent, from SpendStopResponse serialization_alias); the toggle body
// is { halted } (SpendStopUpdate). `useSpendHalted` is the shared, lightweight read
// every dashboard surface keys its paid-action CTAs off of.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ClientBudget, CostEntry, DialFeature, DialMode } from "@/lib/cost";

export const BUDGETS_KEY = ["cost", "budgets"] as const;
export const DIAL_KEY = ["cost", "dial"] as const;
export const COST_LOG_KEY = ["cost", "log"] as const;
export const SPEND_STOP_KEY = ["cost", "spend-stop"] as const;

// The recent-window size the stat cards (provider breakdown / heatmap / jobs count)
// aggregate over. The cost-log TABLE paginates independently (useCostLogPage).
const COST_LOG_WINDOW = 200;

// --- reads -------------------------------------------------------------------
export function useBudgets() {
  return useQuery({
    queryKey: BUDGETS_KEY,
    queryFn: () => api.get<ClientBudget[]>("/cost/budgets"),
  });
}

export function useDial() {
  return useQuery({
    queryKey: DIAL_KEY,
    queryFn: () => api.get<DialFeature[]>("/cost/dial"),
  });
}

// The recent window used by the aggregate stat cards (NOT the paginated table).
export function useCostLog() {
  return useQuery({
    queryKey: [...COST_LOG_KEY, "window", COST_LOG_WINDOW] as const,
    queryFn: () => api.get<CostEntry[]>(`/cost/log?limit=${COST_LOG_WINDOW}&offset=0`),
  });
}

// One page of the cost log (newest-first). `hasMore` is inferred from a full page:
// a page shorter than `limit` is the last one. Backed by the same paginated
// /cost/log endpoint; each (offset,limit) caches separately + keeps prior data so
// paging feels instant.
export function useCostLogPage(offset: number, limit: number) {
  return useQuery({
    queryKey: [...COST_LOG_KEY, "page", offset, limit] as const,
    queryFn: () => api.get<CostEntry[]>(`/cost/log?limit=${limit}&offset=${offset}`),
    placeholderData: (prev) => prev,
  });
}

// SpendStopResponse (serialized): the global API-spend HALT state + today's live
// paid spend (informational; there is no per-day threshold any more).
export type SpendStop = { halted: boolean; todaySpent: number };

export function useSpendStop() {
  return useQuery({
    queryKey: SPEND_STOP_KEY,
    queryFn: () => api.get<SpendStop>("/cost/spend-stop"),
  });
}

// The shared halt signal. Every paid-action surface (audit run, content generate,
// policy ask, team tool panels) reads this to disable its CTA + show the banner
// when spend is halted agency-wide. `halted` defaults to false while loading so a
// transient read never wrongly blocks a control.
export function useSpendHalted(): { halted: boolean; isLoading: boolean } {
  const q = useSpendStop();
  return { halted: q.data?.halted ?? false, isLoading: q.isLoading };
}

// --- writes ------------------------------------------------------------------
// PUT /cost/budgets/{client_id}: the ClientBudget.id IS the client_id.
export function useSetBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, cap }: { clientId: string; cap: number }) =>
      api.put<ClientBudget>(`/cost/budgets/${clientId}`, { cap }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: BUDGETS_KEY }),
  });
}

// PUT /cost/dial/{feature_key}: flip a feature's cost mode (api/byhand/off).
// Optimistic: flip the row in-cache immediately so the segmented control feels
// instant, roll back on error, then reconcile with the server on settle.
export function useSetDial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, mode }: { key: string; mode: DialMode }) =>
      api.put<DialFeature>(`/cost/dial/${key}`, { mode }),
    onMutate: async ({ key, mode }) => {
      await qc.cancelQueries({ queryKey: DIAL_KEY });
      const prev = qc.getQueryData<DialFeature[]>(DIAL_KEY);
      if (prev) {
        qc.setQueryData<DialFeature[]>(
          DIAL_KEY,
          prev.map((d) => (d.key === key ? { ...d, mode } : d)),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(DIAL_KEY, ctx.prev);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: DIAL_KEY }),
  });
}

// PUT /cost/spend-stop: toggle the global API-spend halt. Body is { halted }.
export type SpendStopUpdate = { halted: boolean };

export function useSetSpendStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SpendStopUpdate) => api.put<SpendStop>("/cost/spend-stop", body),
    // Optimistic: reflect the halt flip immediately so the toggle reads live; roll
    // back on error.
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: SPEND_STOP_KEY });
      const prev = qc.getQueryData<SpendStop>(SPEND_STOP_KEY);
      if (prev) qc.setQueryData<SpendStop>(SPEND_STOP_KEY, { ...prev, halted: body.halted });
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(SPEND_STOP_KEY, ctx.prev);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: SPEND_STOP_KEY }),
  });
}
