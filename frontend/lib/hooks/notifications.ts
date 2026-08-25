"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AppNotification, StaffAlert } from "@/lib/notifications";

export const NOTIFICATIONS_KEY = ["notifications"] as const;
export const UNREAD_KEY = ["notifications", "unread-count"] as const;
export const ALERTS_KEY = ["alerts"] as const;

// The badge polls; the list does not. Opening the dropdown is what fetches bodies, so
// the always-mounted cost is one integer a minute rather than a full inbox.
const POLL_MS = 60_000;

/** The badge number. Cheap by design — its own endpoint, not a client-side length. */
export function useUnreadCount() {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: POLL_MS,
    // A failed poll must not blank a badge that was correct a minute ago.
    placeholderData: (prev) => prev,
  });
}

/** The caller's own inbox, newest first. Fetched only while the panel is open. */
export function useNotifications(enabled: boolean) {
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: () => api.get<AppNotification[]>("/notifications"),
    enabled,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<AppNotification>(`/notifications/${id}/read`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
      void qc.invalidateQueries({ queryKey: UNREAD_KEY });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ unread: number }>("/notifications/read-all"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
      void qc.invalidateQueries({ queryKey: UNREAD_KEY });
    },
  });
}

/** The staff alert queue. Staff-only (`view_reports`); a client is 403'd, so this is
 *  requested only where the caller is staff. */
export function useAlerts(enabled: boolean) {
  return useQuery({
    queryKey: ALERTS_KEY,
    queryFn: () => api.get<StaffAlert[]>("/alerts?unacknowledged=true"),
    enabled,
  });
}

/** Acknowledge one alert. Lead-only server-side — a 403 surfaces as a mutation error. */
export function useAcknowledgeAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<StaffAlert>(`/alerts/${id}/acknowledge`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ALERTS_KEY });
    },
  });
}
