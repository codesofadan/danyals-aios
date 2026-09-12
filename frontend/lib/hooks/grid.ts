"use client";

// ============================================================
// AIOS · Local search grid data hooks (migration 0138)
// Backs GridWorkspace off the FastAPI /grid endpoints.
//
// Running a grid is a SPEND door (17-41 paid probes), so the mutation here is
// deliberately plain: no optimistic update, no retry. An optimistic "running" that
// the server then refuses would show a run that never started; a retry on a request
// whose outcome is unknown could queue a second one.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  GridDefinition,
  GridLocationOption,
  GridRun,
  GridRunDetail,
  GridRunQueued,
} from "@/lib/grid";

export const GRID_DEFINITIONS_KEY = ["grid", "definitions"] as const;
export const gridRunsKey = (definitionId: string) =>
  ["grid", "definitions", definitionId, "runs"] as const;
export const gridLatestKey = (definitionId: string) =>
  ["grid", "definitions", definitionId, "latest"] as const;

/** Every standing grid, newest first. Optionally one client's. */
export function useGridDefinitions(clientId?: string) {
  return useQuery({
    queryKey: clientId ? [...GRID_DEFINITIONS_KEY, clientId] : GRID_DEFINITIONS_KEY,
    queryFn: () =>
      api.get<GridDefinition[]>(
        clientId ? `/grid/definitions?clientId=${encodeURIComponent(clientId)}` : "/grid/definitions",
      ),
  });
}

/** This grid's run history - the trend behind the current heat map. */
export function useGridRuns(definitionId: string, enabled = true) {
  return useQuery({
    queryKey: gridRunsKey(definitionId),
    queryFn: () => api.get<GridRun[]>(`/grid/definitions/${definitionId}/runs`),
    enabled: enabled && Boolean(definitionId),
  });
}

/**
 * The most recent run WITH its points - the heat map itself.
 *
 * A 404 here means the grid has never run, which is a real state with its own empty
 * view ("no heat map yet"), so it must not be retried into a spinner and must not be
 * rendered as a grid where the business ranks nowhere.
 */
export function useGridLatest(definitionId: string, enabled = true) {
  return useQuery({
    queryKey: gridLatestKey(definitionId),
    queryFn: () => api.get<GridRunDetail>(`/grid/definitions/${definitionId}/latest`),
    enabled: enabled && Boolean(definitionId),
    retry: false,
  });
}

/**
 * POST /grid/definitions body (GridDefinitionCreate).
 *
 * `clientId` is the normal path: the server resolves the location, business name,
 * address and map centre from that client's own business profile - the same NAP the
 * citation module submits, so the two cannot disagree. `profileId` names an explicit
 * location instead, for a client with several.
 */
export type CreateGridInput = {
  clientId?: string;
  profileId?: string;
  keyword: string;
  /** `square` is the market's shape and the default. */
  shape?: "square" | "rings";
  /** N for an N×N grid (odd, 3–11). */
  gridSize?: number;
  /** Omit BOTH to resolve the centre from the client's own Google listing. */
  centerLat?: number;
  centerLng?: number;
  /** Only for a `rings` grid; a square grid ignores it. */
  rings?: number;
  ringSpacingKm: number;
};

export function useCreateGrid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateGridInput) =>
      api.post<GridDefinition>("/grid/definitions", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GRID_DEFINITIONS_KEY });
    },
  });
}

export function useSetGridActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      api.patch<GridDefinition>(`/grid/definitions/${id}`, { isActive }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GRID_DEFINITIONS_KEY });
    },
  });
}

/**
 * Queue one run. Resolves with `queued:false, held:true` for an honest refusal -
 * that is a 202, not an error, and the caller shows its reason rather than a
 * spinner. A 409 (a run already in flight) DOES reject: it is the double-click
 * guard, and the caller should say so rather than silently succeed.
 */
export function useRunGrid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (definitionId: string) =>
      api.post<GridRunQueued>(`/grid/definitions/${definitionId}/run`, {}),
    retry: false,
    onSuccess: (_data, definitionId) => {
      void qc.invalidateQueries({ queryKey: gridRunsKey(definitionId) });
      void qc.invalidateQueries({ queryKey: GRID_DEFINITIONS_KEY });
    },
  });
}

export const GRID_LOCATIONS_KEY = ["grid", "locations"] as const;

/**
 * The client locations a grid can be centred on - the EXISTING `0039` GBP profile
 * ledger, read through its own module's endpoint.
 *
 * Read once and cached for the session: an operator creating three grids should not
 * re-fetch the same list three times, and locations do not change mid-session.
 */
export function useGridLocations() {
  return useQuery({
    queryKey: GRID_LOCATIONS_KEY,
    queryFn: () => api.get<GridLocationOption[]>("/local-seo/profiles?limit=200"),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Minimal client record for the "add a location" path.
 *
 * `cn` is the client NAME, and the field is named that on the wire - not `name`.
 * Assuming `name` here rendered every option in the picker BLANK, which is
 * indistinguishable from "there are no clients" and is exactly how this was reported.
 */
export type GridClientOption = { id: string; cn: string };

export const GRID_CLIENTS_KEY = ["grid", "clients"] as const;

export function useGridClients(enabled = true) {
  return useQuery({
    queryKey: GRID_CLIENTS_KEY,
    // 200, not the default page: this deploy has 108 clients and the picker showing
    // the first 50 would silently hide the rest.
    queryFn: () => api.get<GridClientOption[]>("/clients?limit=200"),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Create a client LOCATION, so the grid form is not a dead end.
 *
 * A grid must centre on a location, and a client has none until somebody makes one -
 * on this deploy that was 108 clients and zero locations, which turned the picker into
 * an empty dropdown with no way forward. This posts to `local_seo`'s OWN upsert
 * (`POST /local-seo/profiles`) rather than the grid module inventing a second location
 * store: `0039` owns that ledger and this reads and writes it.
 */
export type CreateLocationInput = {
  clientId: string;
  locationLabel: string;
  napName: string;
  napAddress: string;
};

export function useCreateGridLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateLocationInput) =>
      api.post<GridLocationOption>("/local-seo/profiles", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GRID_LOCATIONS_KEY });
    },
  });
}
