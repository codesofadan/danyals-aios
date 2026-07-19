"use client";

// ============================================================
// AIOS · Site Analytics (live GSC + GA4) data hooks
// Backs the "Connect Google" flow on the admin dashboard: register a
// property, kick off the OAuth consent redirect, and trigger a manual
// sync. The aggregate summary (clicks/impressions/sessions/users) rides
// on the command-center payload (`useCommandCenter`), not here — these
// hooks are for the CRUD/connect actions only.
//
// Types mirror the backend SERVER-AUTHORITATIVE shapes
// (backend/app/modules/site_analytics/schemas.py) exactly as SERIALIZED.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { COMMAND_CENTER_KEY } from "@/lib/hooks/commandCenter";

export type GscProperty = {
  id: string;
  client: string;
  siteUrl: string;
  oauthConnected: boolean;
  lastSyncedAt: string | null;
  clicks28d: number;
  impressions28d: number;
  ctr28d: number;
  avgPosition28d: number;
  topQueries: { query: string; clicks: number; impressions: number }[];
};

export type Ga4Property = {
  id: string;
  client: string;
  propertyId: string;
  oauthConnected: boolean;
  lastSyncedAt: string | null;
  sessions28d: number;
  users28d: number;
  conversions28d: number;
};

export type ConnectGoogleResult = { authorizeUrl: string | null; held: boolean; reason: string };
export type SyncQueuedResult = { id: string; queued: boolean; held: boolean; reason: string };

export const GSC_PROPERTIES_KEY = ["site-analytics", "gsc"] as const;
export const GA4_PROPERTIES_KEY = ["site-analytics", "ga4"] as const;

export function useGscProperties() {
  return useQuery({
    queryKey: GSC_PROPERTIES_KEY,
    queryFn: () => api.get<GscProperty[]>("/site-analytics/gsc/properties"),
  });
}

export function useGa4Properties() {
  return useQuery({
    queryKey: GA4_PROPERTIES_KEY,
    queryFn: () => api.get<Ga4Property[]>("/site-analytics/ga4/properties"),
  });
}

export function useCreateGscProperty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { clientId: string; siteUrl: string }) =>
      api.post<GscProperty>("/site-analytics/gsc/properties", input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: GSC_PROPERTIES_KEY });
      qc.invalidateQueries({ queryKey: COMMAND_CENTER_KEY });
    },
  });
}

export function useCreateGa4Property() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { clientId: string; propertyId: string }) =>
      api.post<Ga4Property>("/site-analytics/ga4/properties", input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: GA4_PROPERTIES_KEY });
      qc.invalidateQueries({ queryKey: COMMAND_CENTER_KEY });
    },
  });
}

/** Fetch the Google consent-screen URL for a property (or an honest `held`
 * when no OAuth client is configured) and navigate the browser there. */
export async function connectAndRedirect(kind: "gsc" | "ga4", propertyId: string): Promise<ConnectGoogleResult> {
  const result = await api.get<ConnectGoogleResult>(`/site-analytics/${kind}/properties/${propertyId}/connect`);
  if (result.authorizeUrl) window.location.assign(result.authorizeUrl);
  return result;
}

export function useSyncGscProperty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (propertyId: string) =>
      api.post<SyncQueuedResult>(`/site-analytics/gsc/properties/${propertyId}/sync`),
    onSuccess: () => qc.invalidateQueries({ queryKey: COMMAND_CENTER_KEY }),
  });
}

export function useSyncGa4Property() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (propertyId: string) =>
      api.post<SyncQueuedResult>(`/site-analytics/ga4/properties/${propertyId}/sync`),
    onSuccess: () => qc.invalidateQueries({ queryKey: COMMAND_CENTER_KEY }),
  });
}
