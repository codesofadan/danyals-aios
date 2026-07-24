"use client";

// ============================================================
// AIOS · Task Manager data hooks
// Backs the admin Task Manager tab off the FastAPI /tasks endpoints. The admin
// sees EVERY team member's tasks in one place (GET /tasks, no scope) with each
// task's lifecycle status, assignee and PROOF LINK, and a lead can set/clear a
// task's proof-of-completion URL (PATCH /tasks/{code}, assign_tasks).
// Task ↔ TaskResponse is contract-locked to lib/data.ts, so the JSON drops
// straight into the existing type.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Task } from "@/lib/data";

// Reuse the same query key the Team Management screen uses (["tasks"]) so both
// surfaces share one cache entry and invalidations keep them coherent.
export const ALL_TASKS_KEY = ["tasks"] as const;

/** EVERY task on the board (GET /tasks, no scope) — newest first. */
export function useAllTasks() {
  return useQuery({
    queryKey: ALL_TASKS_KEY,
    queryFn: () => api.get<Task[]>("/tasks"),
  });
}

export type SetTaskProofInput = {
  code: string; // the public J-#### task code
  proofUrl: string; // "" clears the link
};

/**
 * Set (or clear) a task's proof-of-completion link (PATCH /tasks/{code}). Lead-only
 * server-side (assign_tasks) — the DB guard also lets the assignee attach theirs via
 * /advance. The backend field is snake_case `proof_url`.
 */
export function useSetTaskProof() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, proofUrl }: SetTaskProofInput) =>
      api.patch<Task>(`/tasks/${code}`, { proof_url: proofUrl }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ALL_TASKS_KEY });
    },
  });
}
