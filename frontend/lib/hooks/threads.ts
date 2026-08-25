"use client";

// ============================================================
// AIOS · discussion-thread hooks
//
// Two audiences, two endpoint families, deliberately NOT shared behind one hook:
//
//   staff  → /threads/{entity}/{code}/messages   (internal notes included)
//   client → /portal/requests/{code}/messages    (client-visible only)
//
// A single hook with a role flag would put the decision at a call site. Keeping them
// apart means a client screen has no hook that could return an internal note.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  MessageVisibility,
  PortalMessage,
  ThreadEntity,
  ThreadMessage,
} from "@/lib/threads";

export const threadKey = (entity: ThreadEntity, code: string) =>
  ["threads", entity, code] as const;
export const portalThreadKey = (code: string) => ["portal", "requests", code, "messages"] as const;

/** The whole conversation on a task or request (staff). Empty until someone posts. */
export function useThread(entity: ThreadEntity, code: string | null) {
  return useQuery({
    queryKey: threadKey(entity, code ?? ""),
    queryFn: () => api.get<ThreadMessage[]>(`/threads/${entity}/${code}/messages`),
    enabled: !!code,
  });
}

/** Post a message. `visibility` defaults to internal server-side; pass it explicitly
 *  to address the client. */
export function usePostMessage(entity: ThreadEntity, code: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { body: string; visibility: MessageVisibility }) =>
      api.post<ThreadMessage>(`/threads/${entity}/${code}/messages`, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: threadKey(entity, code) });
    },
  });
}

/** The client's own conversation on their request. Never contains an internal note. */
export function usePortalThread(code: string | null) {
  return useQuery({
    queryKey: portalThreadKey(code ?? ""),
    queryFn: () => api.get<PortalMessage[]>(`/portal/requests/${code}/messages`),
    enabled: !!code,
  });
}

/** The client replies on their own request. Visibility is pinned server-side. */
export function usePostPortalMessage(code: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      api.post<PortalMessage>(`/portal/requests/${code}/messages`, { body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: portalThreadKey(code) });
    },
  });
}
