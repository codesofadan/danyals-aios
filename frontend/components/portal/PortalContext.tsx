"use client";

import { createContext, useContext, useMemo, useState } from "react";
import { teamMembers, tasks_seed, PORTAL_MEMBER_ID, type Task, type TeamMemberRecord } from "@/lib/data";
import { nextStatus, type ReviewAction } from "@/lib/portal";

// Members who can actually sign in — invited members have no portal yet.
export const signedInMembers = teamMembers.filter((m) => m.status !== "invited");

type PortalState = {
  me: TeamMemberRecord;
  members: TeamMemberRecord[];
  memberId: string;
  setMemberId: (id: string) => void;
  myTasks: Task[];
  openCount: number;
  reviewCount: number;
  advance: (id: string) => void;
  review: (id: string, action: ReviewAction) => void;
};

const Ctx = createContext<PortalState | null>(null);

// Holds the signed-in member + their task board for the whole team
// portal, so mutations (start / deliver / approve) persist as you move
// between the sidebar pages. This is the seam the real backend plugs
// into: swap the seed + local mutations for /me and /tasks API calls.
export function PortalProvider({ children }: { children: React.ReactNode }) {
  const [memberId, setMemberId] = useState<string>(PORTAL_MEMBER_ID);
  const [tasks, setTasks] = useState<Task[]>(tasks_seed);

  const me = useMemo(
    () => teamMembers.find((m) => m.id === memberId) ?? signedInMembers[0],
    [memberId],
  );
  const myTasks = useMemo(() => tasks.filter((t) => t.assignee === me.id), [tasks, me.id]);
  const openCount = myTasks.filter((t) => t.status !== "done").length;
  const reviewCount = myTasks.filter((t) => t.status === "review").length;

  function advance(id: string) {
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        const next = nextStatus(t);
        return next ? { ...t, status: next } : t;
      }),
    );
  }

  function review(id: string, action: ReviewAction) {
    setTasks((prev) =>
      prev.map((t) =>
        t.id === id ? { ...t, status: action === "approve" ? "done" : "in_progress" } : t,
      ),
    );
  }

  const value: PortalState = {
    me, members: signedInMembers, memberId, setMemberId,
    myTasks, openCount, reviewCount, advance, review,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePortal(): PortalState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePortal must be used within a PortalProvider");
  return ctx;
}
