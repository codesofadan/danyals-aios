"use client";

// ============================================================
// AIOS · demo authentication
// A single login page is the front door: every dashboard (admin,
// team portal, client) sits behind it. The operator picks a role
// (Admin / Team / Client) and signs in; credentials are validated
// against the shared store so a client or team member the admin
// just created can sign straight in with the credentials issued to
// them. The session is persisted to localStorage so a refresh keeps
// you signed in. This is the seam the real FastAPI auth service
// plugs into — swap validateLogin for a POST /auth/login call.
// ============================================================

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { operatorProfile, teamCredentials } from "@/lib/data";
import { useStore } from "@/lib/store";

export type Role = "admin" | "team" | "client";

export const ROLE_META: Record<Role, { label: string; icon: string; home: string; hint: string }> = {
  admin: { label: "Admin", icon: "shield_person", home: "/", hint: "Agency super-admin — the full control dashboard" },
  team: { label: "Team member", icon: "groups", home: "/portal", hint: "Your assigned work, deliverables & tools" },
  client: { label: "Client", icon: "insights", home: "/client", hint: "Your reports, graphs, milestones & requests" },
};

// The agency super-admin credential — grounded in the seeded operator.
export const ADMIN_CREDENTIAL = {
  username: operatorProfile.email,
  password: teamCredentials[operatorProfile.id]?.pass ?? "Xg!Danyal#2026",
};

export type Session = { role: Role; id: string; name: string };

type AuthState = {
  session: Session | null;
  ready: boolean; // false until the persisted session has hydrated
  login: (role: Role, username: string, password: string) => { ok: boolean; error?: string };
  logout: () => void;
};

const Ctx = createContext<AuthState | null>(null);
const SESSION_KEY = "aios-session-v1";

const norm = (s: string) => s.trim().toLowerCase();

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { members, clients, teamLogins } = useStore();
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SESSION_KEY);
      if (raw) setSession(JSON.parse(raw) as Session);
    } catch {
      /* ignore corrupt/unavailable storage */
    }
    setReady(true);
  }, []);

  const persist = useCallback((next: Session | null) => {
    setSession(next);
    try {
      if (next) window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
      else window.localStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const login = useCallback<AuthState["login"]>((role, username, password) => {
    const u = norm(username);
    if (!u || !password) return { ok: false, error: "Enter both a username and password." };

    if (role === "admin") {
      if (u === norm(ADMIN_CREDENTIAL.username) && password === ADMIN_CREDENTIAL.password) {
        persist({ role, id: operatorProfile.id, name: operatorProfile.name });
        return { ok: true };
      }
      return { ok: false, error: "Invalid admin credentials." };
    }

    if (role === "team") {
      const match = members.find((m) => {
        const cred = teamLogins[m.id];
        if (!cred) return false;
        const matchesUser = norm(m.email) === u || norm(cred.username) === u;
        return matchesUser && cred.pass === password;
      });
      if (match) {
        persist({ role, id: match.id, name: match.name });
        return { ok: true };
      }
      return { ok: false, error: "No team member matches those credentials." };
    }

    // client
    const match = clients.find((c) => norm(c.portal.admin) === u && c.portal.pass === password);
    if (match) {
      persist({ role, id: match.id, name: match.cn });
      return { ok: true };
    }
    return { ok: false, error: "No client account matches those credentials." };
  }, [members, clients, teamLogins, persist]);

  const logout = useCallback(() => persist(null), [persist]);

  const value = useMemo<AuthState>(() => ({ session, ready, login, logout }), [session, ready, login, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
