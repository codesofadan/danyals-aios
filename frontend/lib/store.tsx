"use client";

// ============================================================
// AIOS · shared demo store
// A single client-side source of truth that ALL THREE portals
// (admin dashboard, team portal, client dashboard) read from and
// write to — so an action in one surface is instantly reflected in
// the others: create a client → it appears in the client portal;
// invite a team member → they can sign into the team portal with
// exactly the tools you granted; assign a task → it lands in that
// member's queue.
//
// State is seeded from lib/data.ts and lib/client.ts and then
// persisted to localStorage so it also survives navigation and
// refreshes during a live demo. This is the seam the real backend
// plugs into: swap the mutations for FastAPI/Postgres calls and the
// portals keep working unchanged.
// ============================================================

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import {
  clientDirectory, clientReportGrants, teamMembers, tasks_seed, activity_seed,
  defaultRolePerms, memberGrants as seedMemberGrants, teamCredentials, TIER_PRICE, SERIES,
  type ClientRecord, type NewClient, type TeamMemberRecord, type Task,
  type Activity, type TeamRole, type PermKey, type TaskStatus, type TaskType,
  type TaskPriority,
} from "@/lib/data";
import { nextStatus, type ReviewAction } from "@/lib/portal";
import { seedRequests, type ClientRequest, type RequestKind } from "@/lib/client";

// --- Action input shapes (mirror the wizard payloads) -----------------------
export type AddMemberInput = {
  name: string;
  email: string;
  title: string;
  role: TeamRole;
  color: string;
  template?: string;
  features?: string[];
  // The one-time sign-in credentials minted by the wizard, so a member
  // invited during the demo can immediately log into the team portal.
  username?: string;
  password?: string;
};

// A team member's portal sign-in credential, keyed by member id.
export type TeamLogin = { username: string; pass: string };

export type AssignTaskInput = {
  title: string;
  client: string;
  type: TaskType;
  assignee: string;
  priority: TaskPriority;
  due: string;
};

// The signed-in operator — every admin action is attributed to them.
const OPERATOR = { id: "u-danyal", init: "DA", name: "Danyal Ahmed", c: SERIES.c1 };

type StoreShape = {
  clients: ClientRecord[];
  clientGrants: Record<string, string[]>;
  members: TeamMemberRecord[];
  tasks: Task[];
  activity: Activity[];
  rolePerms: Record<TeamRole, PermKey[]>;
  memberGrants: Record<string, string[]>;
  teamLogins: Record<string, TeamLogin>;
  requests: ClientRequest[];
};

type StoreActions = {
  // Clients
  addClient: (input: NewClient) => string;
  saveClientGrants: (clientId: string, reports: string[]) => void;
  // Team
  addMember: (input: AddMemberInput) => string;
  assignTask: (input: AssignTaskInput) => void;
  setTaskStatus: (taskId: string, status: TaskStatus) => void;
  togglePerm: (role: TeamRole, key: PermKey) => void;
  // Team portal (member-driven task flow)
  advanceTask: (taskId: string) => void;
  reviewTask: (taskId: string, action: ReviewAction) => void;
  // Client portal
  addRequest: (r: { kind: RequestKind; subject: string; detail: string }) => void;
  // Housekeeping
  resetDemo: () => void;
};

type Store = StoreShape & StoreActions;

const STORAGE_KEY = "aios-demo-store-v1";

// Seed each member's portal login: they sign in with their work email and
// the password from teamCredentials (Owners/Admins gate the admin app).
function seedTeamLogins(): Record<string, TeamLogin> {
  const out: Record<string, TeamLogin> = {};
  for (const m of teamMembers) {
    const cred = teamCredentials[m.id];
    if (cred) out[m.id] = { username: m.email, pass: cred.pass };
  }
  return out;
}

function seedState(): StoreShape {
  return {
    clients: clientDirectory,
    clientGrants: clientReportGrants,
    members: teamMembers,
    tasks: tasks_seed,
    activity: activity_seed,
    rolePerms: defaultRolePerms,
    memberGrants: seedMemberGrants,
    teamLogins: seedTeamLogins(),
    requests: seedRequests,
  };
}

// Monotonic id helpers — safe in the browser (the provider is client-only).
let idSeq = 0;
const uid = (p: string) => `${p}-${Date.now().toString(36)}${(idSeq++).toString(36)}`;
const initialsOf = (name: string) =>
  name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";
const ACCENTS = [SERIES.c1, SERIES.c2, SERIES.c4, SERIES.c3, SERIES.c5];

const Ctx = createContext<Store | null>(null);

export function AiosStoreProvider({ children }: { children: React.ReactNode }) {
  // Seed first so server and first client render match, then hydrate any
  // persisted demo state from localStorage after mount.
  const [state, setState] = useState<StoreShape>(seedState);
  const hydrated = useRef(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as Partial<StoreShape>;
        // Merge onto seeds so newly-added seed fields survive an old save.
        setState((prev) => ({ ...prev, ...saved }));
      }
    } catch {
      /* corrupt/unavailable storage — fall back to seeds */
    }
    hydrated.current = true;
  }, []);

  useEffect(() => {
    if (!hydrated.current) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* storage full/unavailable — demo still works in-memory */
    }
  }, [state]);

  const pushLog = useCallback((entry: Omit<Activity, "id" | "ago">) => {
    setState((s) => ({
      ...s,
      activity: [{ ...entry, id: uid("a"), ago: "just now" }, ...s.activity],
    }));
  }, []);

  // --- Clients --------------------------------------------------------------
  const addClient = useCallback((input: NewClient) => {
    const slug = input.cn.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 20);
    const id = `cl-${slug || "client"}-${(idSeq++).toString(36)}`;
    setState((s) => {
      const accent = ACCENTS[s.clients.length % ACCENTS.length];
      const record: ClientRecord = {
        id, cn: input.cn, industry: input.industry, sites: 1, since: "2026",
        contact: {
          name: input.contactName, role: "Primary Contact", email: input.contactEmail,
          init: initialsOf(input.contactName), c: accent,
        },
        tier: input.tier, status: "trial", renews: "Onboarding", mrr: TIER_PRICE[input.tier],
        portal: { admin: input.adminLogin, pass: input.adminPass, seats: 2, twoFA: false, lastLogin: "just now" },
      };
      return {
        ...s,
        clients: [record, ...s.clients],
        clientGrants: { ...s.clientGrants, [id]: input.reports },
        activity: [{
          id: uid("a"), ago: "just now", kind: "client",
          actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
          action: "onboarded", target: input.cn, meta: `${input.tier} · ${input.reports.length} reports shared`,
        }, ...s.activity],
      };
    });
    return id;
  }, []);

  const saveClientGrants = useCallback((clientId: string, reports: string[]) => {
    setState((s) => ({ ...s, clientGrants: { ...s.clientGrants, [clientId]: reports } }));
    const c = state.clients.find((x) => x.id === clientId);
    pushLog({
      kind: "client", actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
      action: "updated report access for", target: c?.cn ?? clientId, meta: `${reports.length} reports visible`,
    });
  }, [state.clients, pushLog]);

  // --- Team -----------------------------------------------------------------
  const addMember = useCallback((input: AddMemberInput) => {
    const id = uid("u");
    const features = input.features ?? [];
    setState((s) => {
      const member: TeamMemberRecord = {
        id, name: input.name, init: initialsOf(input.name), c: input.color,
        title: input.title, email: input.email, role: input.role, status: "invited",
        activeTasks: 0, completed: 0, onTime: 0, utilization: 0, quality: 0, joined: "Jul 2026",
      };
      return {
        ...s,
        members: [member, ...s.members],
        // Grant the member exactly the tools popped in the wizard, so their
        // team portal unlocks precisely those surfaces.
        memberGrants: { ...s.memberGrants, [id]: features },
        // Persist their sign-in credential so they can log into the portal.
        teamLogins: {
          ...s.teamLogins,
          [id]: { username: input.username ?? input.email, pass: input.password ?? "changeme" },
        },
        activity: [{
          id: uid("a"), ago: "just now", kind: "member",
          actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
          action: "invited", target: input.name, meta: `${input.template ?? input.role} · ${features.length} features granted`,
        }, ...s.activity],
      };
    });
    return id;
  }, []);

  const assignTask = useCallback((input: AssignTaskInput) => {
    const id = uid("J");
    setState((s) => {
      const who = s.members.find((m) => m.id === input.assignee);
      const task: Task = {
        id, title: input.title, client: input.client, type: input.type,
        assignee: input.assignee, priority: input.priority, status: "todo", due: input.due,
      };
      return {
        ...s,
        tasks: [task, ...s.tasks],
        members: s.members.map((m) => m.id === input.assignee ? { ...m, activeTasks: m.activeTasks + 1 } : m),
        activity: [{
          id: uid("a"), ago: "just now", kind: "task",
          actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
          action: "assigned", target: `${id} · ${input.type}`, meta: `${who?.name ?? "—"} · ${input.client}`,
        }, ...s.activity],
      };
    });
  }, []);

  const setTaskStatus = useCallback((taskId: string, status: TaskStatus) => {
    setState((s) => {
      const t = s.tasks.find((x) => x.id === taskId);
      if (!t) return s;
      const who = s.members.find((m) => m.id === t.assignee);
      return {
        ...s,
        tasks: s.tasks.map((x) => x.id === taskId ? { ...x, status } : x),
        activity: [{
          id: uid("a"), ago: "just now", kind: "task",
          actorInit: who?.init ?? "?", actorName: who?.name ?? "—", actorColor: who?.c ?? "var(--muted)",
          action: status === "done" ? "completed" : `moved to ${status.replace("_", " ")}`,
          target: t.id, meta: t.client,
        }, ...s.activity],
      };
    });
  }, []);

  const togglePerm = useCallback((role: TeamRole, key: PermKey) => {
    setState((s) => {
      const has = s.rolePerms[role].includes(key);
      const next = has ? s.rolePerms[role].filter((k) => k !== key) : [...s.rolePerms[role], key];
      return {
        ...s,
        rolePerms: { ...s.rolePerms, [role]: next },
        activity: [{
          id: uid("a"), ago: "just now", kind: "access",
          actorInit: OPERATOR.init, actorName: OPERATOR.name, actorColor: OPERATOR.c,
          action: has ? "revoked" : "granted", target: key.replace(/_/g, " "), meta: `${role} role`,
        }, ...s.activity],
      };
    });
  }, []);

  // --- Team portal (member acts on their own task) --------------------------
  const advanceTask = useCallback((taskId: string) => {
    setState((s) => {
      const t = s.tasks.find((x) => x.id === taskId);
      if (!t) return s;
      const next = nextStatus(t);
      if (!next) return s;
      const who = s.members.find((m) => m.id === t.assignee);
      return {
        ...s,
        tasks: s.tasks.map((x) => x.id === taskId ? { ...x, status: next } : x),
        activity: [{
          id: uid("a"), ago: "just now", kind: next === "review" ? "content" : "task",
          actorInit: who?.init ?? "?", actorName: who?.name ?? "—", actorColor: who?.c ?? "var(--muted)",
          action: next === "done" ? "completed" : next === "review" ? "submitted for review" : "started",
          target: t.id, meta: t.client,
        }, ...s.activity],
      };
    });
  }, []);

  const reviewTask = useCallback((taskId: string, action: ReviewAction) => {
    setState((s) => {
      const t = s.tasks.find((x) => x.id === taskId);
      if (!t) return s;
      const status: TaskStatus = action === "approve" ? "done" : "in_progress";
      const who = s.members.find((m) => m.id === t.assignee);
      return {
        ...s,
        tasks: s.tasks.map((x) => x.id === taskId ? { ...x, status } : x),
        activity: [{
          id: uid("a"), ago: "just now", kind: "content",
          actorInit: who?.init ?? "?", actorName: who?.name ?? "—", actorColor: who?.c ?? "var(--muted)",
          action: action === "approve" ? "approved at the review gate" : "sent back for changes",
          target: t.id, meta: t.client,
        }, ...s.activity],
      };
    });
  }, []);

  // --- Client portal --------------------------------------------------------
  const addRequest = useCallback(({ kind, subject, detail }: { kind: RequestKind; subject: string; detail: string }) => {
    setState((s) => ({
      ...s,
      requests: [{ id: uid("req"), kind, subject, detail, status: "open", ago: "Just now" }, ...s.requests],
    }));
  }, []);

  const resetDemo = useCallback(() => {
    try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    setState(seedState());
  }, []);

  const value = useMemo<Store>(() => ({
    ...state,
    addClient, saveClientGrants, addMember, assignTask, setTaskStatus, togglePerm,
    advanceTask, reviewTask, addRequest, resetDemo,
  }), [state, addClient, saveClientGrants, addMember, assignTask, setTaskStatus, togglePerm, advanceTask, reviewTask, addRequest, resetDemo]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore must be used within an AiosStoreProvider");
  return ctx;
}
