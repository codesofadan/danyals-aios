"use client";

// ============================================================
// AIOS · service-tier data hooks
// Backs TiersWorkspace off the FastAPI /tiers endpoints instead of the
// build-time `tierClients` seed. TierClientResponse ↔ TierClient is
// contract-locked, so the JSON drops straight into the existing type.
//
// The tier PRESETS (TIERS) + feature-area matrix (featureAreas) are static
// reference catalogues (hardcoded identically on both sides — see
// backend/app/schemas/tiers.py) with no DB source; they stay local in
// `@/lib/tiers`, like the vault `providers` catalogue. Only the per-client
// delivery-tier ASSIGNMENTS are dynamic and read here.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TierClient, TierKey } from "@/lib/tiers";

export const TIER_CLIENTS_KEY = ["tiers", "clients"] as const;

/** Per-client delivery-tier assignments (GET /tiers/clients → TierClient[]). */
export function useTierClients() {
  return useQuery({
    queryKey: TIER_CLIENTS_KEY,
    queryFn: () => api.get<TierClient[]>("/tiers/clients"),
  });
}

export type SetDeliveryTierInput = { clientId: string; tier: TierKey };

/**
 * Re-dial a client's delivery-tier preset (PUT /tiers/clients/{id}).
 * `manage_clients` on the backend; on success the assignment list refetches
 * and the KPI counts / monthly spend recompute.
 */
export function useSetDeliveryTier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, tier }: SetDeliveryTierInput) =>
      api.put<TierClient>(`/tiers/clients/${clientId}`, { tier }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TIER_CLIENTS_KEY });
    },
  });
}
