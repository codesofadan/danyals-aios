"use client";

// ============================================================
// AIOS · Integrations status hook (API Management)
// Backs the vault screen's providers overview off GET /integrations, so every
// supported integration shows a REAL connected/missing verdict computed from live
// config + the vault — not a hard-coded checkmark list.
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const INTEGRATIONS_KEY = ["integrations"] as const;

// GET /integrations ≡ IntegrationStatus (backend app/services/integrations_status.py).
export type IntegrationStatus = {
  id: string;
  name: string;
  category: string;
  connected: boolean;
  source: "config" | "vault";
  detail: string; // short, non-secret reason / how to connect
};

/** Every supported integration with its live connected/missing status (manage_vault). */
export function useIntegrations() {
  return useQuery({
    queryKey: INTEGRATIONS_KEY,
    queryFn: () => api.get<IntegrationStatus[]>("/integrations"),
  });
}
