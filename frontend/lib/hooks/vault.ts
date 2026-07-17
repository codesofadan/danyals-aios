"use client";

// ============================================================
// AIOS · Key Vault data hooks
// Backs VaultWorkspace off the FastAPI /vault endpoints instead of the
// build-time `vaultKeys` seed. VaultKeyResponse ↔ VaultKey is contract-locked;
// a LIST never carries a secret (`secret` is always ""), by design.
//
// The `providers` catalogue is static and stays local (`@/lib/vault`).
//
// REVEAL is a plaintext secret: it is a one-shot `useMutation`, NOT a query —
// nothing is cached in the Query store or persisted. Callers hold the returned
// value in transient local state and drop it the moment the row is re-masked.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ProviderId, Scope, VaultKey } from "@/lib/vault";

export const VAULT_KEYS_KEY = ["vault", "keys"] as const;

/** Masked list of vault keys (GET /vault/keys → VaultKey[]; never a secret). */
export function useVaultKeys() {
  return useQuery({
    queryKey: VAULT_KEYS_KEY,
    queryFn: () => api.get<VaultKey[]>("/vault/keys"),
  });
}

export type CreateVaultKeyInput = {
  provider: ProviderId;
  label: string;
  secret: string;
  scope: Scope;
  site?: string;
};

/** Store a new secret (POST /vault/keys, manage_vault). Returns masked metadata. */
export function useAddVaultKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateVaultKeyInput) => api.post<VaultKey>("/vault/keys", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: VAULT_KEYS_KEY });
    },
  });
}

/**
 * Decrypt one secret on demand (GET /vault/keys/{id}/reveal → { id, secret }).
 * SUPER-ADMIN only on the backend. A `useMutation`, so the plaintext is returned
 * once and NEVER written to the Query cache — the caller keeps it in transient
 * component state and discards it on hide.
 */
export function useRevealVaultKey() {
  return useMutation({
    mutationFn: (id: string) =>
      api.get<{ id: string; secret: string }>(`/vault/keys/${id}/reveal`),
  });
}
