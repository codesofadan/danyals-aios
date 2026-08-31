"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import type { AppNotification, StaffAlert } from "@/lib/notifications";

export const NOTIFICATIONS_KEY = ["notifications"] as const;
export const UNREAD_KEY = ["notifications", "unread-count"] as const;
export const ALERTS_KEY = ["alerts"] as const;

// The badge polls; the list does not. Opening the dropdown is what fetches bodies, so
// the always-mounted cost is one integer every POLL_MS rather than a full inbox.
//
// 60s -> 15s (QA 4: "a team member with the portal open sees it immediately"). There is
// no WebSocket or SSE anywhere in this codebase, so "instant" here means a tighter poll
// plus a refetch the moment the tab regains focus — NOT push. A minute's latency read
// as "the notification never arrived"; fifteen seconds reads as immediate. Still one
// integer per request, so 4x the polls is still a trivial load.
const POLL_MS = 15_000;

/** The badge number. Cheap by design — its own endpoint, not a client-side length. */
export function useUnreadCount() {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: POLL_MS,
    // Coming back to the tab is the moment an operator most expects to be current;
    // waiting out the remainder of an interval there is the latency people notice.
    refetchOnWindowFocus: true,
    // ...and `refetchOnWindowFocus` only refetches a query it considers STALE. The
    // app-wide default is `staleTime: 30_000` (lib/query.tsx) - longer than this
    // 15s poll - so without this the data is essentially never stale while the tab
    // is foregrounded and a short alt-tab would refetch nothing. A badge count is
    // exactly the kind of value that is never worth serving from cache.
    staleTime: 0,
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

/**
 * Announce newly-arrived notifications as toasts (QA 4).
 *
 * Task assignment already produced everything needed — `assign_task` writes a
 * `task_assigned` row and the bell renders it. What was missing was any reason for a
 * team member to LOOK: the badge changed silently, so a task assigned while they had
 * the portal open sat unseen until they next happened to click the bell.
 *
 * WHY IT KEYS OFF THE COUNT. Polling the full inbox every 15s to spot a new row would
 * fetch every body every time. The unread COUNT is already polled and is one integer;
 * a RISE in it is the only signal that something arrived, and only then is the list
 * fetched — so the steady-state cost is unchanged and a fetch happens exactly when
 * there is something new to show.
 *
 * Three things it must never do, each of which is a real failure mode:
 *   1. Toast the backlog on mount. The first observation only establishes a baseline;
 *      someone signing in with 12 unread does not want 12 toasts.
 *   2. Toast the same row twice. Ids already announced are remembered, so a count that
 *      dips (a read elsewhere) and rises again cannot re-announce anything.
 *   3. Bury the screen. At most MAX_TOASTS fire; the rest are summarised in one line.
 *
 * A count that falls just re-baselines — reading notifications in another tab must not
 * arm a burst of toasts here.
 */
const MAX_TOASTS = 3;

// MODULE scope, not a ref, and that is load-bearing. TopBar (which mounts the bell,
// which calls this hook) is rendered by each PAGE — no layout renders it — so every
// client-side navigation unmounts and remounts it. Per-mount refs meant "already
// announced" was forgotten on every route change: walk from /team/queue to
// /team/deliver and the next arrival re-toasted every unread row again.
//
// Module state outlives the user, so it is stamped with whose it is and reset when
// that changes — otherwise signing out and back in as someone else would inherit the
// previous person's baseline and announce the new user's backlog.
let announcedOwner: string | null = null;
let announcedIds: Set<string> = new Set();
let seenUnread: number | null = null; // null = nothing observed yet (≠ a real 0)

function resetAnnouncedFor(owner: string | null): void {
  announcedOwner = owner;
  announcedIds = new Set();
  seenUnread = null;
}

export function useNotificationToasts(enabled: boolean, userId?: string | null) {
  const qc = useQueryClient();
  const toast = useToast();
  const unreadQ = useUnreadCount();
  const unread = unreadQ.data?.unread;

  useEffect(() => {
    if (!enabled || unread === undefined) return;

    // A different signed-in person: drop the previous one's baseline and ids rather
    // than treating their count as ours.
    const owner = userId ?? null;
    if (owner !== announcedOwner) resetAnnouncedFor(owner);

    const previous = seenUnread;
    seenUnread = unread;

    // First observation, or the count went down/stayed put — nothing new arrived.
    if (previous === null || unread <= previous) return;

    let cancelled = false;
    void (async () => {
      let rows: AppNotification[];
      try {
        rows = await qc.fetchQuery({
          queryKey: NOTIFICATIONS_KEY,
          queryFn: () => api.get<AppNotification[]>("/notifications"),
          // We KNOW the list changed — the count just rose. Without this, the app-wide
          // `staleTime: 30_000` serves the cached list, which is the list from BEFORE
          // the arrival: the new row is missing and the rows the operator was just
          // looking at in the open panel get announced instead. A toast for something
          // already read, and silence for the thing that actually arrived.
          staleTime: 0,
        });
      } catch {
        // A failed fetch must not announce a notification we could not read, and must
        // not wedge the baseline — the next rise tries again.
        return;
      }
      if (cancelled) return;

      const fresh = rows.filter((n) => !n.read && !announcedIds.has(n.id));
      if (fresh.length === 0) return;
      fresh.forEach((n) => announcedIds.add(n.id));

      for (const n of fresh.slice(0, MAX_TOASTS)) {
        toast.info(n.title, n.body || undefined);
      }
      const rest = fresh.length - MAX_TOASTS;
      if (rest > 0) toast.info(`${rest} more notification${rest === 1 ? "" : "s"}`);
    })();

    return () => { cancelled = true; };
  }, [enabled, unread, userId, qc, toast]);
}

/** Forget every announced notification (sign-out). Exported for the auth layer. */
export function resetNotificationToasts(): void {
  resetAnnouncedFor(null);
}
