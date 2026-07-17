"use client";

// ============================================================
// AIOS · authentication (real, token-backed)
// One login page is the front door to all three portals. Login is now a real
// 2-step call against FastAPI:
//   1. POST /auth/login {username,password} → {access_token, role, portal}
//      (the token is persisted by lib/api; the SERVER decides the portal)
//   2. hydrate the display name — GET /me (admin/team) or GET /portal/dashboard
//      (client) — since the token itself carries no name.
// The bearer token in localStorage is the real credential; this Session is a
// convenience snapshot for chrome + routing. The security boundary is the
// backend (RLS + require_perm), NOT this provider or AuthGuard.
// ============================================================

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiFetch, api, setToken } from "@/lib/api";

export type Role = "admin" | "team" | "client";

export const ROLE_META: Record<Role, { label: string; icon: string; home: string; hint: string }> = {
  admin: { label: "Admin", icon: "shield_person", home: "/", hint: "Agency super-admin — the full control dashboard" },
  team: { label: "Team member", icon: "groups", home: "/portal", hint: "Your assigned work, deliverables & tools" },
  client: { label: "Client", icon: "insights", home: "/client", hint: "Your reports, graphs, milestones & requests" },
};

export type Session = { role: Role; id: string; name: string };

export type LoginResult = { ok: true; role: Role } | { ok: false; error: string };

type AuthState = {
  session: Session | null;
  ready: boolean; // false until the persisted session has hydrated
  login: (username: string, password: string) => Promise<LoginResult>;
  logout: () => void;
};

const Ctx = createContext<AuthState | null>(null);
const SESSION_KEY = "aios-session-v1";

// The server's login + identity shapes (portal ∈ admin/team/client maps 1:1 to Role).
type LoginResponse = { access_token: string; role: string; portal: Role };
type MeResponse = { id: string; name: string };
type DashboardResponse = { client: string };

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  // Hydrate the last session snapshot instantly (no network). The bearer token
  // is validated lazily on the first real API call — a stale token 401s and
  // lib/api bounces to /login, so the snapshot never outlives the token.
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

  const login = useCallback<AuthState["login"]>(
    async (username, password) => {
      let res: LoginResponse;
      try {
        // noAuthRedirect: a wrong password is a 401 we want to SHOW, not a
        // session-expiry redirect.
        res = await apiFetch<LoginResponse>("/auth/login", {
          method: "POST",
          body: { username, password },
          noAuthRedirect: true,
        });
      } catch {
        // The backend returns ONE generic 401 for wrong-password AND unknown-user
        // by design (no account-enumeration oracle), so we surface one message.
        return { ok: false, error: "Invalid credentials." };
      }

      setToken(res.access_token);
      const role = res.portal;

      // Step 2: hydrate the display name (the token carries none).
      let name = username;
      let id = "";
      try {
        if (role === "client") {
          const dash = await api.get<DashboardResponse>("/portal/dashboard");
          name = dash.client || username;
        } else {
          const me = await api.get<MeResponse>("/me");
          name = me.name || username;
          id = me.id || "";
        }
      } catch {
        /* name hydration is best-effort; the token is already valid */
      }

      persist({ role, id, name });
      return { ok: true, role };
    },
    [persist],
  );

  const logout = useCallback(() => {
    setToken(null);
    persist(null);
  }, [persist]);

  const value = useMemo<AuthState>(() => ({ session, ready, login, logout }), [session, ready, login, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
