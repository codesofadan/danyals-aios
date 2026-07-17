"use client";

// ============================================================
// AIOS · upsells data hooks
// Backs UpsellsWorkspace off the FastAPI /upsells endpoints instead of the
// build-time `upsells` seed. UpsellResponse ↔ Upsell is contract-locked, so
// the JSON drops straight into the existing type. `CONVERSION_RATE` stays a
// frontend const (presentation-only, in `@/lib/upsells`).
//
// Mutations mirror the admin curation surface: add, toggle-active, reorder.
// `clicks30d` is portal-tracked server-side and never sent from the client.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Upsell } from "@/lib/upsells";

export const UPSELLS_KEY = ["upsells"] as const;

/** The full upsell catalogue in curated order (GET /upsells → Upsell[]). */
export function useUpsells() {
  return useQuery({
    queryKey: UPSELLS_KEY,
    queryFn: () => api.get<Upsell[]>("/upsells"),
  });
}

// POST /upsells body. `fiverrUrl` is the camelCase wire key the backend accepts
// (aliased). icon/color are chosen client-side so the new card renders branded.
export type CreateUpsellInput = {
  title: string;
  description: string;
  fiverrUrl: string;
  active: boolean;
  price: number;
  rating: number;
  reviews: number;
  icon: string;
  color: string;
};

/** Add a Fiverr upsell card (POST /upsells, owner/admin). */
export function useCreateUpsell() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateUpsellInput) => api.post<Upsell>("/upsells", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: UPSELLS_KEY });
    },
  });
}

/** Flip an upsell's active flag (POST /upsells/{id}/toggle, owner/admin). */
export function useToggleUpsell() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Upsell>(`/upsells/${id}/toggle`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: UPSELLS_KEY });
    },
  });
}

/** Persist a new curated order (POST /upsells/reorder, owner/admin). */
export function useReorderUpsells() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.post<Upsell[]>("/upsells/reorder", { ids }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: UPSELLS_KEY });
    },
  });
}
