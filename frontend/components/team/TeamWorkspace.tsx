"use client";

import { useMemo, useState } from "react";
import {
  teamMembers, tasks_seed, activity_seed, defaultRolePerms,
  SERIES,
  type TeamMemberRecord, type Task, type Activity, type TeamRole, type PermKey, type TaskStatus,
} from "@/lib/data";
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

// The signed-in operator — every admin action is attributed to them in the log.
const OPERATOR = { init: "DA", name: "Danyal Ahmed", c: SERIES.c1 };

let idSeq = 0;
const nextId = (p: string) => `${p}-${Date.now().toString(36)}${idSeq++}`;

export default function TeamWorkspace() {
  const [tab, setTab] = useState<TabKey>("roster");
  const [members, setMembers] = useState<TeamMemberRecord[]>(teamMembers);
  const [tasks, setTasks] = useState<Task[]>(tasks_seed);
  const [log, setLog] = useState<Activity[]>(activity_seed);
  const [rolePerms, setRolePerms] = useState<Record<TeamRole, PermKey[]>>(defaultRolePerms);

  const nameById = useMemo(() => {
    const m = new Map(members.map((x) => [x.id, x] as const));
    return m;
  }, [members]);

  function pushLog(entry: Omit<Activity, "id" | "ago">) {
    setLog((prev) => [{ ...entry, id: nextId("a"), ago: "just now" }, ...prev]);
  }

  function handleAddMember(input: NewMember) {
    const id = nextId("u");
    const init = input.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";
    const member: TeamMemberRecord = {
      id, name: input.name, init, c: input.color, title: input.title, email: input.email,
      role: input.role, status: "invited",
      activeTasks: 0, completed: 0, onTime: 0, utilization: 0, quality: 0,
      joined: "Jul 2026",
    };
    setMembers((prev) => [member, ...prev]);
    const tpl = input.template ?? input.role;
    const fcount = input.features?.length ?? 0;
    pushLog({
      kind: "member", actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
      action: "invited", target: input.name, meta: `${tpl} · ${fcount} features granted`,
    });
    setTab("roster");
  }

  function handleAssign(input: NewTask) {
    const id = nextId("J");
    const task: Task = {
      id, title: input.title, client: input.client, type: input.type,
      assignee: input.assignee, priority: input.priority, status: "todo", due: input.due,
    };
    setTasks((prev) => [task, ...prev]);
    setMembers((prev) => prev.map((m) => m.id === input.assignee ? { ...m, activeTasks: m.activeTasks + 1 } : m));
    const who = nameById.get(input.assignee);
    pushLog({
      kind: "task", actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
      action: "assigned", target: `${id} · ${input.type}`, meta: `${who?.name ?? "—"} · ${input.client}`,
    });
    setTab("assign");
  }

  function handleStatusChange(taskId: string, status: TaskStatus) {
    let moved: Task | undefined;
    setTasks((prev) => prev.map((t) => {
      if (t.id === taskId) { moved = { ...t, status }; return moved; }
      return t;
    }));
    if (moved) {
      const who = nameById.get(moved.assignee);
      pushLog({
        kind: "task", actorInit: who?.init ?? "?", actorName: who?.name ?? "—", actorColor: who?.c ?? "var(--muted)",
        action: status === "done" ? "completed" : `moved to ${status.replace("_", " ")}`,
        target: `${moved.id}`, meta: moved.client,
      });
    }
  }

  function handleTogglePerm(role: TeamRole, key: PermKey) {
    let granted = false;
    setRolePerms((prev) => {
      const has = prev[role].includes(key);
      granted = !has;
      const next = has ? prev[role].filter((k) => k !== key) : [...prev[role], key];
      return { ...prev, [role]: next };
    });
    pushLog({
      kind: "access", actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
      action: granted ? "granted" : "revoked", target: key.replace(/_/g, " "), meta: `${role} role`,
    });
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
        {tab === "activity" && <ActivityLog log={log} />}
        {tab === "access" && <AccessControl rolePerms={rolePerms} onToggle={handleTogglePerm} />}
      </div>
    </section>
  );
}
