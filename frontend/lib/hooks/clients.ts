"use client";

// Client accounts + their report-access grants. `useClients` (GET /clients →
// ClientResponse[] ≡ ClientRecord[]) backs the audit "run new" picker AND the
// admin Client Directory. The report-grant hooks back the Directory's Report-Access
// view + the Add-Client wizard.
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TIER_PRICE, type ClientRecord, type NewClient } from "@/lib/data";

export const CLIENTS_KEY = ["clients"] as const;
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
    mutationFn: async (input: NewClient): Promise<ClientRecord & { portalWarning?: string }> => {
      const created = await api.post<ClientRecord>("/clients", {
        cn: input.cn,
        industry: input.industry,
        tier: input.tier,
        mrr: TIER_PRICE[input.tier],
        contact: { name: input.contactName, email: input.contactEmail },
        portal: { admin: input.adminLogin },
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
