"use client";

// ============================================================
// AIOS · settings data hooks
// The Settings screen's "My Account" panel reuses GET /me (profile) · PATCH /me —
// the same hooks the team portal owns, re-exported here so the screen has one
// hooks entrypoint. It also owns the caller's own notification preferences via
// GET/PUT /settings/notifications (per-user, real endpoints — app/routers/settings.py).
//
// (The former workspace / security / change-password hooks were removed with
// their now-unreachable panels — Settings no longer surfaces Client Access,
// Team Access, Roles & Permissions, or a change-password form.)
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { NotifPref } from "@/lib/data";

export { useMe, useUpdateMe } from "./portal";

export const NOTIF_PREFS_KEY = ["settings", "notifications"] as const;

/** The caller's own notification preferences (GET /settings/notifications, per-user). */
export function useNotifPrefs() {
  return useQuery({
    queryKey: NOTIF_PREFS_KEY,
    queryFn: () => api.get<NotifPref[]>("/settings/notifications"),
  });
}

export type NotifPrefInput = { key: string; email: boolean; inApp: boolean };

/** PUT /settings/notifications — save the caller's own toggle changes. */
export function useUpdateNotifPrefs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (prefs: NotifPrefInput[]) =>
      api.put<NotifPref[]>("/settings/notifications", { prefs }),
    onSuccess: (data) => qc.setQueryData(NOTIF_PREFS_KEY, data),
  });
}
