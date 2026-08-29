"use client";

// Client accounts + their report-access grants. `useClients` (GET /clients →
// ClientResponse[] ≡ ClientRecord[]) backs the audit "run new" picker AND the
// admin Client Directory. The report-grant hooks back the Directory's Report-Access
// view + the Add-Client wizard.
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  type ClientRecord,
  type NewClient,
  type SubStatus,
  type SubTier,
  type Task,
  type Ticket,
} from "@/lib/data";
import type { ClientBusinessProfile, ClientBusinessProfileInput } from "@/lib/offpage";

export const CLIENTS_KEY = ["clients"] as const;
export const TICKETS_KEY = ["tickets"] as const;

/** The Add-Client payload PLUS the optional NAP the wizard collects at creation. The
 * NAP is a separate table (client_business_profiles, 0051); it rides in the POST body as
 * `business` and is persisted alongside the client. Defined here (not in the reserved
 * data.ts) so the wizard can carry it without changing the shared NewClient shape. */
// `mrr` is the monthly amount the wizard collects (any value). There is NO
// tier->price fallback: a client's MRR is a real figure an operator enters,
// never one the UI invents.
export type NewClientInput = NewClient & { nap?: ClientBusinessProfileInput; mrr?: number };

export const clientBusinessProfileKey = (clientId: string) =>
  ["clients", clientId, "business-profile"] as const;

/** The support-ticket queue (GET /tickets, newest first) for the Directory feed. */
export function useTickets() {
  return useQuery({
    queryKey: TICKETS_KEY,
    queryFn: () => api.get<Ticket[]>("/tickets"),
  });
}

/** Triage a ticket to a new status (PATCH /tickets/{code}/status). Lead-only. */
export function useUpdateTicketStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, status }: { code: string; status: Ticket["status"] }) =>
      api.patch<Ticket>(`/tickets/${code}/status`, { status }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TICKETS_KEY });
    },
  });
}

// `useReplyToTicket` (POST /tickets/{code}/reply) used to live here. `ThreadPanel`
// replaced it: a reply is now a message on the ticket's thread, which keeps a history
// instead of overwriting one field, and can be an internal note instead. The ENDPOINT
// is deliberately retained server-side so a reply sent before threads existed is still
// readable and an application rollback loses nothing - but nothing in the dashboard
// calls it any more, so the hook is gone rather than left as a caller-less export.
/** Turn a client's request into an assigned task (POST /tickets/{code}/convert-to-task).
 *
 * Lead-only (`assign_tasks`). The tenant is resolved from the TICKET server-side - a
 * ticket never exposes its client id on the wire, and accepting one from here would
 * let a request become work billed against a different client.
 *
 * Invalidates tickets (the thread gains an internal note recording the task) and tasks
 * (a new row is on the board).
 */
export function useConvertTicketToTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      code: string;
      assignee_id: string;
      type?: string;
      priority?: string;
      title?: string;
    }) => {
      const { code, ...body } = input;
      return api.post<Task>(`/tickets/${code}/convert-to-task`, body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TICKETS_KEY });
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void qc.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export const reportGrantsKey = (clientId: string) =>
  ["clients", clientId, "report-grants"] as const;

export function useClients() {
  return useQuery({
    queryKey: CLIENTS_KEY,
    queryFn: () => api.get<ClientRecord[]>("/clients?limit=200"),
  });
}

// `useReportGrants(clientId)` — a single client's grants — used to live here with no
// caller. The Client Directory needs the whole table's grants at once (to show the
// per-client count), so it uses `useAllReportGrants`, which caches under the SAME
// per-client key. A one-client hook is a re-add away if a single-client view ever
// wants one; leaving it exported with nothing calling it is the debt this pass exists
// to remove.

/**
 * Report grants for EVERY client in one request (GET /clients/report-grants →
 * { [clientId]: keys[] }). This replaced a real N+1: the directory used to fire
 * one GET per client, so 200 clients meant 200 requests on load. Clients with no
 * grants are absent from the map — the directory renders those as zero.
 */
export function useAllReportGrants(clientIds: string[]) {
  const q = useQuery({
    queryKey: ["report-grants", "all"],
    queryFn: () => api.get<Record<string, string[]>>("/clients/report-grants"),
  });
  const grants: Record<string, string[]> = q.data
    ? Object.fromEntries(clientIds.map((id) => [id, q.data![id] ?? []]))
    : {};
  return { ...q, grants };
}

/** Replace a client's report-access set (PUT /clients/{id}/report-grants → keys[]). */
export function useSaveGrants() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, reports }: { clientId: string; reports: string[] }) =>
      api.put<string[]>(`/clients/${clientId}/report-grants`, { reports }),
    onSuccess: (_keys, { clientId }) => {
      void qc.invalidateQueries({ queryKey: reportGrantsKey(clientId) });
      void qc.invalidateQueries({ queryKey: ["report-grants", "all"] });
    },
  });
}

/**
 * Create a client, then grant its initial report set. The wizard emits a `NewClient`;
 * the backend `POST /clients` takes a NESTED {contact, portal} shape and does NOT
 * accept report grants (that is a separate PUT) — and it never persists the portal
 * password. MRR is whatever the operator entered; an omitted amount is persisted
 * as 0 (unknown), never back-filled from a hardcoded tier price.
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
        mrr: input.mrr ?? 0,
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
  contact?: { name: string; role: string; email: string; color: string };
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

/** A client's registered sites (GET /clients/{id}/sites).
 *
 * The content flow asked the operator to TYPE a site URL, on a screen shown
 * before they had even chosen the client - and then dropped it: `site` was never
 * in the generate payload, so the backend silently used the client's first site
 * anyway. The sites were in the database the whole time and nothing read them. */
export type ClientSite = { id: string; clientId: string; domain: string; cms: string };

export function useClientSites(clientId: string | null) {
  return useQuery({
    queryKey: ["clients", clientId, "sites"] as const,
    queryFn: () => api.get<ClientSite[]>(`/clients/${clientId}/sites`),
    enabled: Boolean(clientId),
  });
}
