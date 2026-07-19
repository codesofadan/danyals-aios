"use client";

// ============================================================
// AIOS · settings data hooks (the admin control-panel read-swap)
// Backs the Settings screen's Workspace / Security / Notifications tabs off the
// FastAPI /settings endpoints instead of the build-time seeds. The response
// shapes are contract-locked to lib/data.ts (WorkspaceSettingsData / SecurityPolicy
// / NotifPref), so the JSON drops straight into the existing types — no mapping.
//
// The account tab reuses GET /me (the same hook the team portal uses — re-exported
// below so the settings screen has one hooks entrypoint), and the roles matrix
// reuses useRbac() / the credential panels reuse useMembers() + useClients() from
// their own hook modules. Those are NOT duplicated here.
//
// Save mutations deliberately do NOT invalidate/refetch their GET: every panel
// seeds its local form state ONCE from the GET and is authoritative thereafter,
// so a refetch mid-edit can never clobber an optimistic toggle. The backend
// records every mutation to the activity log itself (record_activity in the router).
// ============================================================

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { NotifPref, SecurityPolicy, WorkspaceSettingsData } from "@/lib/data";

// The account tab reads/writes the caller's own record via the same hooks (and
// cache key) the team portal already owns; re-exported, not re-created.
export { useMe, useUpdateMe, useChangePassword } from "./portal";

export const WORKSPACE_SETTINGS_KEY = ["settings", "workspace"] as const;
export const SECURITY_SETTINGS_KEY = ["settings", "security"] as const;
export const NOTIF_SETTINGS_KEY = ["settings", "notifications"] as const;

// --- Workspace settings (agency-global; owner/admin) -------------------------

/** GET /settings/workspace → WorkspaceSettingsResponse ≡ WorkspaceSettingsData. */
export function useWorkspaceSettings() {
  return useQuery({
    queryKey: WORKSPACE_SETTINGS_KEY,
    queryFn: () => api.get<WorkspaceSettingsData>("/settings/workspace"),
  });
}

/** PUT /settings/workspace — partial update; returns the full saved settings. */
export function useSaveWorkspaceSettings() {
  return useMutation({
    mutationFn: (patch: Partial<WorkspaceSettingsData>) =>
      api.put<WorkspaceSettingsData>("/settings/workspace", patch),
  });
}

// --- Security policy (agency-global; owner/admin) ----------------------------

/** GET /settings/security → SecurityPolicyResponse ≡ SecurityPolicy. */
export function useSecuritySettings() {
  return useQuery({
    queryKey: SECURITY_SETTINGS_KEY,
    queryFn: () => api.get<SecurityPolicy>("/settings/security"),
  });
}

/** PUT /settings/security — partial update (one field per toggle); returns the policy. */
export function useSaveSecuritySettings() {
  return useMutation({
    mutationFn: (patch: Partial<SecurityPolicy>) =>
      api.put<SecurityPolicy>("/settings/security", patch),
  });
}

// --- Notification preferences (per-user) -------------------------------------

/** GET /settings/notifications → NotifPrefResponse[] ≡ NotifPref[] (the caller's 7 events). */
export function useNotificationSettings() {
  return useQuery({
    queryKey: NOTIF_SETTINGS_KEY,
    queryFn: () => api.get<NotifPref[]>("/settings/notifications"),
  });
}

/**
 * PUT /settings/notifications { prefs: [{ key, email, inApp }] } → NotifPref[].
 * Each item upserts one (user, event) toggle row; unknown keys are ignored server-side.
 */
export function useSaveNotificationSettings() {
  return useMutation({
    mutationFn: (prefs: { key: string; email: boolean; inApp: boolean }[]) =>
      api.put<NotifPref[]>("/settings/notifications", { prefs }),
  });
}
