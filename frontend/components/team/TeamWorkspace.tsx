"use client";

import { useState } from "react";
import type { TeamRole, PermKey, TaskStatus } from "@/lib/data";
import {
  useMembers, useTasks, useActivity, useRbac,
  useAddMember, useAssignTask, useAdvanceTask, useReviewTask, useTogglePerm,
} from "@/lib/hooks/team";
import { useClients } from "@/lib/hooks/clients";
import TeamRoster, { type NewMember } from "./TeamRoster";
import AssignTasks, { type NewTask } from "./AssignTasks";
import TeamPerformance from "./TeamPerformance";
import ActivityLog from "./ActivityLog";
import AccessControl from "./AccessControl";

// Centred muted state for a tab panel (loading / error). Self-styled so it never
// depends on a class that might not exist.
const panelState: React.CSSProperties = {
  padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)",
};

function panelGuard(q: { isLoading: boolean; isError: boolean; error?: unknown }): React.ReactNode | null {
  if (q.isLoading) return <div style={panelState}>Loading…</div>;
  if (q.isError) return <div style={panelState}>Couldn&apos;t load — {(q.error as Error)?.message ?? "try again"}.</div>;
  return null;
}

type TabKey = "roster" | "assign" | "performance" | "activity" | "access";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "roster", label: "Roster", icon: "badge" },
  { key: "assign", label: "Assign Tasks", icon: "assignment_ind" },
  { key: "performance", label: "Performance", icon: "insights" },
  { key: "activity", label: "Activity Log", icon: "history" },
  { key: "access", label: "Access Control", icon: "admin_panel_settings" },
];

export default function TeamWorkspace() {
  const [tab, setTab] = useState<TabKey>("roster");

  const membersQ = useMembers();
  const tasksQ = useTasks();
  const activityQ = useActivity();
  const rbacQ = useRbac();
  const clientsQ = useClients();

  const members = membersQ.data ?? [];
  const tasks = tasksQ.data ?? [];
  const activity = activityQ.data ?? [];
  const rolePerms = rbacQ.data ?? ({} as Record<TeamRole, PermKey[]>);
  const clients = clientsQ.data ?? [];

  const addMember = useAddMember();
  const assignTask = useAssignTask();
  const advanceTask = useAdvanceTask();
  const reviewTask = useReviewTask();
  const togglePerm = useTogglePerm();

  function handleAddMember(input: NewMember) {
    addMember.mutate({
      name: input.name, email: input.email, title: input.title,
      role: input.role, color: input.color, features: input.features,
    });
    setTab("roster");
  }

  function handleAssign(input: NewTask) {
    assignTask.mutate({
      title: input.title,
      client_id: input.client_id,
      type: input.type,
      assignee_id: input.assignee,
      priority: input.priority,
      due: input.due || undefined,
    });
  }

  // The board's status <select> maps onto the REAL lifecycle endpoints: leaving the
  // review gate is a /review approve|reject; any other forward move is a one-step
  // /advance (the server picks review-vs-done by task type). Backward/illegal moves
  // have no API equivalent and are ignored.
  function handleStatusChange(taskId: string, target: TaskStatus) {
    const task = tasks.find((t) => t.id === taskId);
    if (!task || target === task.status) return;
    if (task.status === "review") {
      if (target === "done") reviewTask.mutate({ code: taskId, action: "approve" });
      else if (target === "in_progress") reviewTask.mutate({ code: taskId, action: "reject" });
      return;
    }
    const order: TaskStatus[] = ["todo", "in_progress", "review", "done"];
    if (order.indexOf(target) > order.indexOf(task.status)) advanceTask.mutate(taskId);
  }

  function handleTogglePerm(role: TeamRole, key: PermKey) {
    togglePerm(role, key);
  }

  return (
    <section className="card tw">
      <div className="card-h">
        <div>
          <div className="ct">Team Workspace</div>
          <div className="cs">Roster, assignments, performance, audit trail &amp; role-based access — one place.</div>
        </div>
      </div>

      <div className="tw-tabs" role="tablist" aria-label="Team management sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? "tw-tab on" : "tw-tab"}
            onClick={() => setTab(t.key)}
          >
            <span className="material-symbols-rounded">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      <div className="tw-panel" role="tabpanel">
        {tab === "roster" && (panelGuard(membersQ) ?? <TeamRoster members={members} onAdd={handleAddMember} />)}
        {tab === "assign" && (panelGuard(tasksQ) ?? panelGuard(membersQ) ?? (
          <>
            {assignTask.error instanceof Error && (
              <div style={{ ...panelState, padding: "0.75rem 1rem", color: "var(--warn, #A96913)" }} role="alert">
                Couldn&apos;t assign task — {assignTask.error.message}
              </div>
            )}
            <AssignTasks
              tasks={tasks}
              members={members}
              clients={clients}
              onAssign={handleAssign}
              onStatusChange={handleStatusChange}
            />
          </>
        ))}
        {tab === "performance" && (panelGuard(membersQ) ?? <TeamPerformance members={members} />)}
        {tab === "activity" && (panelGuard(activityQ) ?? <ActivityLog log={activity} />)}
        {tab === "access" && (panelGuard(rbacQ) ?? <AccessControl rolePerms={rolePerms} onToggle={handleTogglePerm} />)}
      </div>
    </section>
  );
}
