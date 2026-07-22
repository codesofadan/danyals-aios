"use client";

// ============================================================
// AIOS · team management data hooks
// Backs the admin Team Management screen off the FastAPI endpoints instead of the
// demo store: the roster (GET /admin/users), the task board (GET/POST /tasks +
// /advance + /review), the activity feed (GET /activity) and the RBAC matrix
// (GET /rbac/roles). Response shapes are contract-locked to lib/data.ts, so the
// JSON drops straight into the existing types.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  TeamMemberRecord,
  Task,
  Activity,
  TeamRole,
  PermKey,
  TaskType,
  TaskPriority,
} from "@/lib/data";

export const MEMBERS_KEY = ["members"] as const;
export const TASKS_KEY = ["tasks"] as const;
export const ACTIVITY_KEY = ["activity"] as const;
export const RBAC_ROLES_KEY = ["rbac", "roles"] as const;

// --- reads --------------------------------------------------------------------

/** The agency roster with live performance metrics (GET /admin/users). */
export function useMembers() {
  return useQuery({
    queryKey: MEMBERS_KEY,
    queryFn: () => api.get<TeamMemberRecord[]>("/admin/users"),
  });
}

/** The whole task board (GET /tasks), newest first. */
export function useTasks() {
  return useQuery({
    queryKey: TASKS_KEY,
    queryFn: () => api.get<Task[]>("/tasks"),
  });
}

/** The admin activity monitor (GET /activity), newest first. */
export function useActivity() {
  return useQuery({
    queryKey: ACTIVITY_KEY,
    queryFn: () => api.get<Activity[]>("/activity"),
  });
}

// The RBAC role×permission matrix is server-side REFERENCE data (GET /rbac/roles):
// the six roles and their default permission grants. It is READ-ONLY — the backend
// exposes no endpoint to persist a change (Owner is all-on and locked; the matrix is
// versioned platform code, not per-tenant state). We fold it into the
// Record<TeamRole, PermKey[]> shape the AccessControl grid renders from.
type RoleView = { role: TeamRole; desc: string; color: string; permissions: PermKey[] };

export function useRbac() {
  return useQuery({
    queryKey: RBAC_ROLES_KEY,
    queryFn: async () => {
      const roles = await api.get<RoleView[]>("/rbac/roles");
      const rolePerms = {} as Record<TeamRole, PermKey[]>;
      for (const r of roles) rolePerms[r.role] = r.permissions;
      return rolePerms;
    },
  });
}

// --- mutations ----------------------------------------------------------------

export type AddMemberInput = {
  name: string;
  email: string;
  title: string;
  role: TeamRole;
  color: string;
  features?: string[];
  // The credential pair the wizard DISPLAYED to the admin. Sent to the server so
  // the stored hash matches what the admin copied — omitting these made the
  // server generate a DIFFERENT password and every new member hit
  // "Invalid credentials" at first sign-in.
  username?: string;
  password?: string;
};

export type InviteResult = {
  member: TeamMemberRecord;
  username: string;
  tempPassword: string;
};

/**
 * Invite a team member with SERVER-generated one-time credentials
 * (POST /admin/users/invite → { member, username, tempPassword }).
 *   • The frontend `TeamRole` is Capitalized; the API `role` is lowercase → mapped.
 *   • The wizard's `template` is a display LABEL, not the seo|content|va|super key the
 *     API validates, so we send the explicit `features` list instead (the API treats
 *     an explicit feature list as the override anyway).
 */
export function useAddMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AddMemberInput) =>
      api.post<InviteResult>("/admin/users/invite", {
        name: input.name,
        email: input.email,
        role: input.role.toLowerCase(),
        title: input.title,
        avatar_color: input.color,
        features: input.features ?? [],
        // Store EXACTLY the credentials the wizard showed (server generates only
        // when these are absent).
        ...(input.username ? { username: input.username } : {}),
        ...(input.password ? { password: input.password } : {}),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: MEMBERS_KEY });
      void qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    },
  });
}

export type AssignTaskInput = {
  title: string;
  client_id: string;
  type: TaskType;
  assignee_id: string;
  priority: TaskPriority;
  due?: string; // ISO YYYY-MM-DD
};

/** Assign a new work item (POST /tasks). */
export function useAssignTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AssignTaskInput) => api.post<Task>("/tasks", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TASKS_KEY });
      void qc.invalidateQueries({ queryKey: MEMBERS_KEY }); // activeTasks metric moves
      void qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    },
  });
}

/**
 * Advance a task one legal lifecycle step (POST /tasks/{code}/advance). The server
 * decides the real next state (in_progress → review for content sprints, else → done).
 */
export function useAdvanceTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.post<Task>(`/tasks/${code}/advance`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TASKS_KEY });
      void qc.invalidateQueries({ queryKey: MEMBERS_KEY });
      void qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    },
  });
}

/** Sign off (approve) or reject a task at the content review gate (POST /tasks/{code}/review). */
export function useReviewTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, action }: { code: string; action: "approve" | "reject" }) =>
      api.post<Task>(`/tasks/${code}/review`, { action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TASKS_KEY });
      void qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    },
  });
}

/**
 * Toggle a role's capability in the RBAC matrix.
 *
 * MISMATCH (recorded): the backend serves the role→permission matrix as READ-ONLY
 * reference data (GET /rbac/roles) — there is NO endpoint to persist a change (Owner
 * is all-on and locked; the matrix is versioned platform code, not per-tenant state).
 * The editable access surface is per-USER feature grants (PUT /admin/users/{id}/grants),
 * a different screen (user × 17 features, not role × 8 permissions). So this updates
 * the local query cache ONLY — session-scoped, NOT persisted across a reload.
 */
export function useTogglePerm() {
  const qc = useQueryClient();
  return (role: TeamRole, key: PermKey) => {
    qc.setQueryData<Record<TeamRole, PermKey[]>>(RBAC_ROLES_KEY, (prev) => {
      if (!prev) return prev;
      const cur = prev[role] ?? [];
      const next = cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key];
      return { ...prev, [role]: next };
    });
  };
}
