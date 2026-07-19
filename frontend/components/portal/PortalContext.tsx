"use client";

import { createContext, useCallback, useContext, useMemo } from "react";
import { type Task, type TeamMemberRecord } from "@/lib/data";
import { type ReviewAction } from "@/lib/portal";
import {
  useAdvanceTask,
  useMe,
  useMyGrants,
  useMyTasks,
  useReviewTask,
} from "@/lib/hooks/portal";

type PortalState = {
  me: TeamMemberRecord;
  myTasks: Task[];
  myGrants: string[]; // granted accessFeatures.key[] for the signed-in member
  openCount: number;
  reviewCount: number;
  advance: (id: string) => void;
  review: (id: string, action: ReviewAction) => void;
};

const Ctx = createContext<PortalState | null>(null);

// Scopes the portal to the SIGNED-IN member and nothing else: `me` comes from
// GET /me, the queue from GET /tasks?mine=1, and every action posts back to the
// task lifecycle — all RLS-scoped server-side to the caller. There is no member
// switcher (the session IS the identity). Until /me resolves we render a neutral
// splash so no member's workspace — let alone another member's data — flashes.
export function PortalProvider({ children }: { children: React.ReactNode }) {
  const meQ = useMe();
  const tasksQ = useMyTasks();
  const grantsQ = useMyGrants();
  const advanceM = useAdvanceTask();
  const reviewM = useReviewTask();

  // mutate() is a stable reference across renders, so these callbacks are stable.
  const advanceMutate = advanceM.mutate;
  const reviewMutate = reviewM.mutate;
  const advance = useCallback((id: string) => advanceMutate(id), [advanceMutate]);
  const review = useCallback(
    (id: string, action: ReviewAction) => reviewMutate({ code: id, action }),
    [reviewMutate],
  );

  const me = meQ.data;
  const myTasks = useMemo(() => tasksQ.data ?? [], [tasksQ.data]);
  const myGrants = useMemo(() => grantsQ.data ?? [], [grantsQ.data]);
  const openCount = myTasks.filter((t) => t.status !== "done").length;
  const reviewCount = myTasks.filter((t) => t.status === "review").length;

  const value = useMemo<PortalState | null>(
    () =>
      me ? { me, myTasks, myGrants, openCount, reviewCount, advance, review } : null,
    [me, myTasks, myGrants, openCount, reviewCount, advance, review],
  );

  // Loading / not-yet-resolved gate — never render the workspace until the
  // signed-in member's own record has loaded.
  if (!value) {
    return (
      <div className="auth-splash">
        <div className="auth-splash-logo" />
        <div className="auth-splash-txt">
          {meQ.isError ? "Couldn't load your workspace — please retry." : "Loading your workspace…"}
        </div>
      </div>
    );
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePortal(): PortalState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePortal must be used within a PortalProvider");
  return ctx;
}
