"use client";

// ============================================================
// AIOS · cost-control data hooks
// Backs CostWorkspace off the FastAPI /cost endpoints instead of the build-time
// seeds. ClientBudget / DialFeature / CostEntry are contract-locked, so the JSON
// drops straight into the existing types.
//
// Spend-stop asymmetry: the RESPONSE is camelCase (dailyStop/halted/todaySpent —
// SpendStopResponse serialization_alias) while the REQUEST body is snake_case
// (daily_stop/halted — SpendStopUpdate has no alias).
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ClientBudget, CostEntry, DialFeature, DialMode } from "@/lib/cost";

export const BUDGETS_KEY = ["cost", "budgets"] as const;
export const DIAL_KEY = ["cost", "dial"] as const;
export const COST_LOG_KEY = ["cost", "log"] as const;
export const SPEND_STOP_KEY = ["cost", "spend-stop"] as const;

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

export function useCostLog() {
  return useQuery({
    queryKey: COST_LOG_KEY,
    queryFn: () => api.get<CostEntry[]>("/cost/log"),
  });
}

// SpendStopResponse (serialized). `todaySpent` is live day-to-date paid spend.
export type SpendStop = { dailyStop: number; halted: boolean; todaySpent: number };

export function useSpendStop() {
  return useQuery({
    queryKey: SPEND_STOP_KEY,
    queryFn: () => api.get<SpendStop>("/cost/spend-stop"),
  });
}

// --- writes ------------------------------------------------------------------
// PUT /cost/budgets/{client_id} — the ClientBudget.id IS the client_id.
export function useSetBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, cap }: { clientId: string; cap: number }) =>
      api.put<ClientBudget>(`/cost/budgets/${clientId}`, { cap }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: BUDGETS_KEY }),
  });
}

// PUT /cost/dial/{feature_key} — flip a feature's cost mode (api/byhand/off).
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

// PUT /cost/spend-stop — snake_case body (SpendStopUpdate). Either field optional.
export type SpendStopUpdate = { daily_stop?: number; halted?: boolean };

export function useSetSpendStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SpendStopUpdate) => api.put<SpendStop>("/cost/spend-stop", body),
    // Optimistic: reflect the halt flip / new threshold immediately so the toggle
    // and threshold read live. The request body is snake_case (daily_stop) while the
    // cache is camelCase (dailyStop) — map across. Roll back on error.
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: SPEND_STOP_KEY });
      const prev = qc.getQueryData<SpendStop>(SPEND_STOP_KEY);
      if (prev) {
        qc.setQueryData<SpendStop>(SPEND_STOP_KEY, {
          ...prev,
          ...(body.halted !== undefined ? { halted: body.halted } : {}),
          ...(body.daily_stop !== undefined ? { dailyStop: body.daily_stop } : {}),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(SPEND_STOP_KEY, ctx.prev);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: SPEND_STOP_KEY }),
  });
}
