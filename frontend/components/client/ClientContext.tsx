"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { SERIES } from "@/lib/data";
import { type ClientRequest, type ReportViz, type RequestKind } from "@/lib/client";
import {
  useClientDashboard,
  useClientReports,
  useClientRequests,
  useCreateRequest,
} from "@/lib/hooks/portalClient";

// The signed-in client's OWN tenant identity, narrowed to what the portal chrome
// renders. A portal login IS the client (the company) — the token is RLS-scoped
// to one tenant, so there is no account switcher and no cross-tenant fallback.
// The dashboard endpoint deliberately never returns a contact PERSON (that is an
// agency-internal field), so the avatar `init`/`c` are DERIVED from the company
// name (a pure display transform, not fabricated data).
export type PortalClient = {
  cn: string; // company name (dashboard.client)
  tier: string; // delivery tier (free | semi | fully)
  init: string; // avatar initials, derived from the name
  c: string; // avatar accent, derived from the name
  site: string; // primary site domain (empty if none)
};

type ClientState = {
  client: PortalClient;
  // The report keys the admin granted this client (what CAN be unlocked).
  grants: Set<string>;
  // key → its live visualization — only GRANTED keys are present (an ungranted
  // report's data is never sent by the backend, so it never appears here).
  reportViz: Record<string, ReportViz>;
  // The report keys the client has actually popped open this session.
  unlocked: Set<string>;
  unlock: (key: string) => void;
  isGranted: (key: string) => boolean;
  isUnlocked: (key: string) => boolean;
  // True when the backend flagged this report's series as representative sample
  // data (`placeholder`) — the card must badge it "Sample", never "Live".
  isPlaceholder: (key: string) => boolean;
  // Requests raised by the client.
  requests: ClientRequest[];
  addRequest: (r: { kind: RequestKind; subject: string; detail: string }) => void;
};

const Ctx = createContext<ClientState | null>(null);

const EMPTY: Set<string> = new Set();
const EMPTY_REPORTS: { key: string; viz: ReportViz; placeholder: boolean }[] = [];
const EMPTY_REQUESTS: ClientRequest[] = [];
const ACCENTS = [SERIES.c1, SERIES.c2, SERIES.c3, SERIES.c4, SERIES.c5] as const;

// Initials from the company name: "NorthPeak Dental" → "ND", "Verde" → "VE".
function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "–";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

// A stable accent picked deterministically from the name (display only).
function accentOf(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return ACCENTS[h % ACCENTS.length];
}

// Holds the signed-in client's identity + granted report viz + which graphs
// they've unlocked this session + their requests, so state survives navigation
// between the dashboard, reports, milestones and requests pages. Every field is
// sourced from the RLS-scoped /portal/* endpoints — no seed, no store, no
// cross-tenant fallback.
export function ClientProvider({ children }: { children: React.ReactNode }) {
  const dashboardQ = useClientDashboard();
  const reportsQ = useClientReports();
  const requestsQ = useClientRequests();
  const createRequest = useCreateRequest();

  // The unlock animation is client-side session state (which granted graphs the
  // user has popped open) — it never leaves the browser.
  const [unlocked, setUnlocked] = useState<Set<string>>(EMPTY);

  const unlock = useCallback((key: string) => {
    setUnlocked((prev) => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }, []);

  const dash = dashboardQ.data;

  const client = useMemo<PortalClient>(() => {
    const name = dash?.client ?? "";
    return {
      cn: name,
      tier: dash?.deliveryTier ?? "",
      init: initialsOf(name),
      c: accentOf(name),
      site: dash?.sites?.[0]?.domain ?? "",
    };
  }, [dash]);

  const reports = reportsQ.data ?? EMPTY_REPORTS;

  const grants = useMemo(() => new Set(reports.map((r) => r.key)), [reports]);
  const reportViz = useMemo(() => {
    const m: Record<string, ReportViz> = {};
    for (const r of reports) m[r.key] = r.viz;
    return m;
  }, [reports]);
  const placeholders = useMemo(
    () => new Set(reports.filter((r) => r.placeholder).map((r) => r.key)),
    [reports],
  );

  const requests = requestsQ.data ?? EMPTY_REQUESTS;

  const isGranted = useCallback((key: string) => grants.has(key), [grants]);
  const isUnlocked = useCallback((key: string) => unlocked.has(key), [unlocked]);
  const isPlaceholder = useCallback((key: string) => placeholders.has(key), [placeholders]);

  const addRequest = useCallback(
    (r: { kind: RequestKind; subject: string; detail: string }) => {
      createRequest.mutate(r);
    },
    [createRequest],
  );

  const value = useMemo<ClientState>(
    () => ({
      client,
      grants,
      reportViz,
      unlocked,
      unlock,
      isGranted,
      isUnlocked,
      isPlaceholder,
      requests,
      addRequest,
    }),
    [client, grants, reportViz, unlocked, unlock, isGranted, isUnlocked, isPlaceholder, requests, addRequest],
  );

  // Until the tenant identity resolves, show the neutral splash — never a seed,
  // never another tenant. (A hard 401 is already bounced to /login by lib/api.)
  if (!dash) {
    return (
      <div className="auth-splash">
        <div className="auth-splash-logo" />
        <div className="auth-splash-txt">Loading your dashboard…</div>
      </div>
    );
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useClient(): ClientState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useClient must be used within a ClientProvider");
  return ctx;
}
