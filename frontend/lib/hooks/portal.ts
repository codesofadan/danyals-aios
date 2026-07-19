"use client";

// ============================================================
// AIOS · team-portal data hooks (the member-facing read-swap)
// Backs the team portal off the FastAPI endpoints instead of the demo store.
// The signed-in member is the ONLY member — every read is RLS-scoped to the
// caller server-side, so there is no member id to pass and no switcher:
//   • useMe()        → GET /me           (MemberResponse ≡ TeamMemberRecord)
//   • useMyTasks()   → GET /tasks?mine=1 (TaskResponse[]  ≡ Task[])
//   • useActivity()  → GET /activity     (ActivityResponse[] ≡ Activity[])
//   • useMyGrants()  → GET /me/grants     → the granted feature keys (self-serve)
// plus the lifecycle mutations useAdvanceTask() / useReviewTask(), which
// invalidate the queue (+ me metrics + activity) on success.
// All response shapes are contract-locked to the frontend types — the JSON
// drops straight into the existing type, no field mapping.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Activity, Task, TeamMemberRecord } from "@/lib/data";
import type { ReviewAction } from "@/lib/portal";

export const ME_KEY = ["me"] as const;
export const MY_TASKS_KEY = ["tasks", "mine"] as const;
export const ACTIVITY_KEY = ["activity"] as const;
export const MY_GRANTS_KEY = ["me", "grants"] as const;

/** The signed-in member's own record, with live metrics (RLS-scoped to them). */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => api.get<TeamMemberRecord>("/me"),
  });
}

/** The caller's own task queue (mine=1 scopes the board to the signed-in member). */
export function useMyTasks() {
  return useQuery({
    queryKey: MY_TASKS_KEY,
    queryFn: () => api.get<Task[]>("/tasks?mine=1"),
  });
}

/** The activity feed (the whole staff feed; the view filters to the member). */
export function useActivity() {
  return useQuery({
    queryKey: ACTIVITY_KEY,
    queryFn: () => api.get<Activity[]>("/activity"),
  });
}

// The backend returns every one of the 17 features as full|view|off; the portal
// treats "granted" as any non-off level (mirrors lib/data.ts memberGrants).
type GrantLevel = "full" | "view" | "off";
type GrantsResponse = { grants: Record<string, GrantLevel> };

/**
 * The signed-in member's granted feature keys (`accessFeatures.key[]`), the
 * shape MyAccess / the sidebar / the tool gate expect. Self-serve (GET /me/grants) —
 * no access_control permission required, so every member (not just the owner) sees
 * their real grants instead of a false-locked `[]`.
 */
export function useMyGrants() {
  return useQuery({
    queryKey: MY_GRANTS_KEY,
    queryFn: async () => {
      const res = await api.get<GrantsResponse>("/me/grants");
      return Object.entries(res.grants)
        .filter(([, level]) => level !== "off")
        .map(([key]) => key);
    },
  });
}

export type UpdateMeInput = { name?: string; title?: string; email?: string };

/** PATCH /me — edit the caller's own name/title/email; returns the updated record. */
export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateMeInput) => api.patch<TeamMemberRecord>("/me", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ME_KEY }),
  });
}

export type ChangePasswordInput = { current_password: string; new_password: string };

/** POST /me/password — the caller's own password change (current verified server-side). */
export function useChangePassword() {
  return useMutation({
    mutationFn: (input: ChangePasswordInput) => api.post<void>("/me/password", input),
  });
}

/**
 * Advance a task one legal lifecycle step (POST /tasks/{code}/advance). The
 * frontend Task.id IS the public J-#### code. `retry: 0` (client default) keeps
 * a transient failure from double-advancing. Invalidates the queue, the member's
 * live metrics, and the activity feed on success.
 */
export function useAdvanceTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.post<Task>(`/tasks/${code}/advance`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: MY_TASKS_KEY });
      void qc.invalidateQueries({ queryKey: ME_KEY });
      void qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    },
  });
}

/** Sign off (approve→done) or reject (→in_progress) at the review gate. */
export function useReviewTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, action }: { code: string; action: ReviewAction }) =>
      api.post<Task>(`/tasks/${code}/review`, { action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: MY_TASKS_KEY });
      void qc.invalidateQueries({ queryKey: ME_KEY });
      void qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    },
  });
}
