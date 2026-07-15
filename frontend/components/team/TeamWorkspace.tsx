"use client";

import { useState } from "react";
import type { TeamRole, PermKey, TaskStatus } from "@/lib/data";
import { useStore } from "@/lib/store";
import TeamRoster, { type NewMember } from "./TeamRoster";
import AssignTasks, { type NewTask } from "./AssignTasks";
import TeamPerformance from "./TeamPerformance";
import ActivityLog from "./ActivityLog";
import AccessControl from "./AccessControl";

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
  const {
    members, tasks, activity, rolePerms,
    addMember, assignTask, setTaskStatus, togglePerm,
  } = useStore();

  function handleAddMember(input: NewMember) {
    addMember(input);
    setTab("roster");
  }

  function handleAssign(input: NewTask) {
    assignTask(input);
    setTab("assign");
  }

  function handleStatusChange(taskId: string, status: TaskStatus) {
    setTaskStatus(taskId, status);
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
        {tab === "roster" && <TeamRoster members={members} onAdd={handleAddMember} />}
        {tab === "assign" && (
          <AssignTasks tasks={tasks} members={members} onAssign={handleAssign} onStatusChange={handleStatusChange} />
        )}
        {tab === "performance" && <TeamPerformance members={members} />}
        {tab === "activity" && <ActivityLog log={activity} />}
        {tab === "access" && <AccessControl rolePerms={rolePerms} onToggle={handleTogglePerm} />}
      </div>
    </section>
  );
}
