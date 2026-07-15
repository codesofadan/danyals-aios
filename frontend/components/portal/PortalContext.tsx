"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { PORTAL_MEMBER_ID, type Task, type TeamMemberRecord } from "@/lib/data";
import { type ReviewAction } from "@/lib/portal";
import { useStore } from "@/lib/store";
import { useAuth } from "@/lib/auth";

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

// Reads the shared roster + task board from the global store and scopes it
// to the signed-in member, so tasks the admin assigns land here live and a
// member's actions (start / deliver / approve) flow back to the admin
// activity log. Any member — including one just invited from the admin
// dashboard — can be previewed via the sidebar switcher.
export function PortalProvider({ children }: { children: React.ReactNode }) {
  const { members, tasks, advanceTask, reviewTask } = useStore();
  const { session } = useAuth();
  const [memberId, setMemberId] = useState<string>(
    session?.role === "team" ? session.id : PORTAL_MEMBER_ID,
  );

  // When the signed-in team member resolves (or changes), scope the portal
  // to them. The sidebar switcher can still preview any member afterwards.
  useEffect(() => {
    if (session?.role === "team") setMemberId(session.id);
  }, [session?.role, session?.id]);

  const me = useMemo(
    () => members.find((m) => m.id === memberId) ?? members[0],
    [members, memberId],
  );
  const myTasks = useMemo(() => tasks.filter((t) => t.assignee === me.id), [tasks, me.id]);
  const openCount = myTasks.filter((t) => t.status !== "done").length;
  const reviewCount = myTasks.filter((t) => t.status === "review").length;

  const value: PortalState = {
    me, members, memberId, setMemberId,
    myTasks, openCount, reviewCount, advance: advanceTask, review: reviewTask,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePortal(): PortalState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePortal must be used within a PortalProvider");
  return ctx;
}
