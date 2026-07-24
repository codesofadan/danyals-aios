"use client";

// ============================================================
// AIOS · multi-client WordPress Connections data hooks
// Backs the admin WordPress screen off the FastAPI /wp-connections endpoints.
// GET returns EVERY client joined with its connection status (unconfigured ->
// placeholder), so the screen needs no separate /clients call. A save/test/delete
// invalidates the list so the table + status pills refresh.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { WpConnection, WpConnectionInput, WpTestResult } from "@/lib/wordpress";

export const WP_CONNECTIONS_KEY = ["wp-connections"] as const;

/** Every client with its WordPress connection state (GET /wp-connections). */
export function useWpConnections() {
  return useQuery({
    queryKey: WP_CONNECTIONS_KEY,
    queryFn: () => api.get<WpConnection[]>("/wp-connections"),
  });
}

/** Set or replace a client's connection (PUT /wp-connections/{id}). The secret is
 * sealed server-side; an omitted api_key/password keeps the stored credential. */
export function useSaveWpConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, input }: { clientId: string; input: WpConnectionInput }) =>
      api.put<WpConnection>(`/wp-connections/${clientId}`, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WP_CONNECTIONS_KEY });
    },
  });
}

/** Probe a client's connection against the real site (POST /wp-connections/{id}/test).
 * Returns { ok, detail, status }; also refreshes the list so the pill reflects it. */
export function useTestWpConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: string) => api.post<WpTestResult>(`/wp-connections/${clientId}/test`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WP_CONNECTIONS_KEY });
    },
  });
}

/** Remove a client's connection (DELETE /wp-connections/{id} → 204). */
export function useDeleteWpConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: string) => api.del<void>(`/wp-connections/${clientId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WP_CONNECTIONS_KEY });
    },
  });
}
