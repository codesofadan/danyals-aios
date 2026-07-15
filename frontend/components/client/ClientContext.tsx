"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { type ClientRecord } from "@/lib/data";
import { type ClientRequest, type RequestKind } from "@/lib/client";
import { useStore } from "@/lib/store";
import { useAuth } from "@/lib/auth";

// The client account that signs in by default (demo). Real auth resolves
// this from the session; the sidebar switcher lets you preview any account.
const DEFAULT_CLIENT_ID = "cl-northpeak";

type ClientState = {
  client: ClientRecord;
  accounts: ClientRecord[];
  clientId: string;
  setClientId: (id: string) => void;
  // The report keys the admin granted this client (what CAN be unlocked).
  grants: Set<string>;
  // The report keys the client has actually popped open this session.
  unlocked: Set<string>;
  unlock: (key: string) => void;
  isGranted: (key: string) => boolean;
  isUnlocked: (key: string) => boolean;
  // Requests raised by the client.
  requests: ClientRequest[];
  addRequest: (r: { kind: RequestKind; subject: string; detail: string }) => void;
};

const Ctx = createContext<ClientState | null>(null);

// Holds the signed-in client + which graphs they've unlocked + their
// requests, so state survives navigation between the dashboard, reports
// and requests pages. This is the seam the real backend plugs into: swap
// the seed grants/requests for /me, /grants and /requests API calls.
export function ClientProvider({ children }: { children: React.ReactNode }) {
  // Roster, grants & the request inbox come from the shared store, so a
  // client the admin just onboarded can sign in here with exactly the
  // reports they were granted, and requests raised here surface to the admin.
  const { clients, clientGrants, requests, addRequest } = useStore();
  const { session } = useAuth();
  const [clientId, setClientId] = useState<string>(
    session?.role === "client" ? session.id : DEFAULT_CLIENT_ID,
  );
  const [unlockedByClient, setUnlockedByClient] = useState<Record<string, Set<string>>>({});

  // Scope the dashboard to the signed-in client once the session resolves.
  useEffect(() => {
    if (session?.role === "client") setClientId(session.id);
  }, [session?.role, session?.id]);

  const client = useMemo(
    () => clients.find((c) => c.id === clientId) ?? clients[0],
    [clients, clientId],
  );

  const grants = useMemo(
    () => new Set(clientGrants[client.id] ?? []),
    [clientGrants, client.id],
  );

  const unlocked = unlockedByClient[client.id] ?? EMPTY;

  const unlock = useCallback((key: string) => {
    setUnlockedByClient((prev) => {
      const cur = prev[clientId] ?? new Set<string>();
      if (cur.has(key)) return prev;
      const next = new Set(cur); next.add(key);
      return { ...prev, [clientId]: next };
    });
  }, [clientId]);

  const isGranted = useCallback((key: string) => grants.has(key), [grants]);
  const isUnlocked = useCallback((key: string) => unlocked.has(key), [unlocked]);

  const value: ClientState = {
    client, accounts: clients, clientId, setClientId,
    grants, unlocked, unlock, isGranted, isUnlocked,
    requests, addRequest,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

const EMPTY: Set<string> = new Set();

export function useClient(): ClientState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useClient must be used within a ClientProvider");
  return ctx;
}
