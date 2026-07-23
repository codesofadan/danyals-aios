"use client";

// Client accounts + their report-access grants. `useClients` (GET /clients →
// ClientResponse[] ≡ ClientRecord[]) backs the audit "run new" picker AND the
// admin Client Directory. The report-grant hooks back the Directory's Report-Access
// view + the Add-Client wizard.
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  TIER_PRICE,
  type ClientRecord,
  type NewClient,
  type SubStatus,
  type SubTier,
  type Ticket,
} from "@/lib/data";
import type { ClientBusinessProfile, ClientBusinessProfileInput } from "@/lib/offpage";

export const CLIENTS_KEY = ["clients"] as const;
export const TICKETS_KEY = ["tickets"] as const;

/** The Add-Client payload PLUS the optional NAP the wizard collects at creation. The
 * NAP is a separate table (client_business_profiles, 0051); it rides in the POST body as
 * `business` and is persisted alongside the client. Defined here (not in the reserved
 * data.ts) so the wizard can carry it without changing the shared NewClient shape. */
export type NewClientInput = NewClient & { nap?: ClientBusinessProfileInput };

export const clientBusinessProfileKey = (clientId: string) =>
  ["clients", clientId, "business-profile"] as const;

/** The support-ticket queue (GET /tickets, newest first) for the Directory feed. */
export function useTickets() {
  return useQuery({
    queryKey: TICKETS_KEY,
    queryFn: () => api.get<Ticket[]>("/tickets"),
  });
}
export const reportGrantsKey = (clientId: string) =>
  ["clients", clientId, "report-grants"] as const;

export function useClients() {
  return useQuery({
    queryKey: CLIENTS_KEY,
    queryFn: () => api.get<ClientRecord[]>("/clients"),
  });
}

/** A single client's granted report keys (GET /clients/{id}/report-grants). */
export function useReportGrants(clientId: string | null) {
  return useQuery({
    queryKey: reportGrantsKey(clientId ?? ""),
    queryFn: () => api.get<string[]>(`/clients/${clientId}/report-grants`),
    enabled: !!clientId,
  });
}

/**
 * Report grants for MANY clients, folded into the `{ [clientId]: keys[] }` shape the
 * Directory's Report-Access table renders from (mirrors the old store `clientGrants`).
 * The backend only exposes grants per-client, so this is one GET per client — deduped
 * + cached by React Query, and reused key-for-key by `useReportGrants`/`useSaveGrants`.
 */
export function useAllReportGrants(clientIds: string[]) {
  return useQueries({
    queries: clientIds.map((id) => ({
      queryKey: reportGrantsKey(id),
      queryFn: () => api.get<string[]>(`/clients/${id}/report-grants`),
    })),
    combine: (results) => {
      const grants: Record<string, string[]> = {};
      clientIds.forEach((id, i) => {
        grants[id] = results[i]?.data ?? [];
      });
      return {
        grants,
        isLoading: results.some((r) => r.isLoading),
        isError: results.some((r) => r.isError),
      };
    },
  });
}

/** Replace a client's report-access set (PUT /clients/{id}/report-grants → keys[]). */
export function useSaveGrants() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, reports }: { clientId: string; reports: string[] }) =>
      api.put<string[]>(`/clients/${clientId}/report-grants`, { reports }),
    onSuccess: (_keys, { clientId }) => {
      void qc.invalidateQueries({ queryKey: reportGrantsKey(clientId) });
    },
  });
}

/**
 * Create a client, then grant its initial report set. The wizard emits a `NewClient`;
 * the backend `POST /clients` takes a NESTED {contact, portal} shape and does NOT
 * accept report grants (that is a separate PUT) — and it never persists the portal
 * password. MRR is derived client-side from the tier (TIER_PRICE), since the wizard
 * collects the tier, not a dollar amount.
 *
 * Third step: the wizard's step-3 "temporary password" is generated client-side and
 * shown to the operator — it only WORKS if it's also sent to POST /clients/{id}/
 * portal-users (the real portal-login provisioning route). Best-effort: mirrors the
 * backend's own onboarding-seed pattern (never fails/rolls back the client creation
 * that already succeeded) — a `portalWarning` on the resolved value lets the caller
 * flag it if provisioning the login itself failed (e.g. a duplicate email).
 */
export function useCreateClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: NewClientInput): Promise<ClientRecord & { portalWarning?: string }> => {
      const created = await api.post<ClientRecord>("/clients", {
        cn: input.cn,
        industry: input.industry,
        tier: input.tier,
        mrr: TIER_PRICE[input.tier],
        contact: { name: input.contactName, email: input.contactEmail },
        portal: { admin: input.adminLogin },
        // The NAP the wizard collected (persisted into client_business_profiles); an
        // omitted/empty profile is simply not written server-side.
        ...(input.nap ? { business: input.nap } : {}),
      });
      if (input.reports.length > 0) {
        await api.put<string[]>(`/clients/${created.id}/report-grants`, {
          reports: input.reports,
        });
      }
      try {
        await api.post(`/clients/${created.id}/portal-users`, {
          email: input.contactEmail,
          name: input.contactName,
          username: input.adminLogin,
          password: input.adminPass,
        });
        return created;
      } catch {
        return {
          ...created,
          portalWarning: "Client created, but the portal login couldn't be provisioned — set it up from Settings.",
        };
      }
    },
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: CLIENTS_KEY });
      void qc.invalidateQueries({ queryKey: reportGrantsKey(created.id) });
    },
  });
}

/**
 * Partial account-field edit accepted by PATCH /clients/{id} (ClientUpdate) — only
 * the provided fields are written server-side. The portal password lives elsewhere
 * (never here), and report grants are their own PUT.
 */
export type ClientUpdate = {
  cn?: string;
  industry?: string;
  since?: number;
  tier?: SubTier;
  status?: SubStatus;
  renews?: string;
  mrr?: number;
};

/** Edit a client's account fields (PATCH /clients/{id} → the updated ClientRecord). */
export function useUpdateClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: ClientUpdate }) =>
      api.patch<ClientRecord>(`/clients/${id}`, changes),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CLIENTS_KEY });
    },
  });
}

/** A client's stored NAP (GET /clients/{id}/business-profile). 404 (no profile yet) is
 * surfaced as an error the caller treats as "empty", never a crash. */
export function useClientBusinessProfile(clientId: string | null) {
  return useQuery({
    queryKey: clientBusinessProfileKey(clientId ?? ""),
    queryFn: () => api.get<ClientBusinessProfile>(`/clients/${clientId}/business-profile`),
    enabled: !!clientId,
    retry: false, // a 404 (no NAP captured yet) is an expected state, not a transient fault
  });
}

/** Create or replace a client's NAP (PUT /clients/{id}/business-profile). Lead-only. */
export function useSaveClientBusinessProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, nap }: { clientId: string; nap: ClientBusinessProfileInput }) =>
      api.put<ClientBusinessProfile>(`/clients/${clientId}/business-profile`, nap),
    onSuccess: (_row, { clientId }) => {
      void qc.invalidateQueries({ queryKey: clientBusinessProfileKey(clientId) });
    },
  });
}

/** Remove a client account (DELETE /clients/{id} → 204, ManageClients only). */
export function useDeleteClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<void>(`/clients/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CLIENTS_KEY });
    },
  });
}
