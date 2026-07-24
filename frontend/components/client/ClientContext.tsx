"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
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
  // Headline audit figures from GET /portal/dashboard — always-available real
  // data (the tenant's most recent scored audit + total run count), surfaced on
  // the portal home. `latestScore` is null until the first scored run lands.
  latestScore: number | null;
  latestAuditWhen: string;
  totalAudits: number;
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
  // Requests raised by the client, plus the live query status so a screen can
  // tell "no requests yet" apart from "still loading" / "the fetch failed".
  requests: ClientRequest[];
  requestsLoading: boolean;
  requestsError: boolean;
  refetchRequests: () => void;
  addRequest: (
    r: { kind: RequestKind; subject: string; detail: string },
    opts?: { onSuccess?: () => void; onError?: () => void },
  ) => void;
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

  // Which granted graphs this client has popped open. The reveal is a cosmetic
  // expand over data the admin already GRANTED (real access lives in `grants`),
  // so it is persisted PER-TENANT in localStorage rather than the DB: once a
  // client reveals a graph it stays open across refreshes and revisits, while
  // remaining cheap and requiring no server round-trip. Keyed by a STABLE tenant
  // id (the primary site's UUID, unique per tenant) rather than the display name,
  // so two different tenants that happen to share a company name on one browser
  // never collide on this cosmetic state. (Underlying data is RLS-scoped server
  // side regardless — this key only guards which cards render already-expanded.)
  const [unlocked, setUnlocked] = useState<Set<string>>(EMPTY);

  const dash = dashboardQ.data;
  const tenantId = dash?.sites?.[0]?.id || dash?.client || "";
  const storageKey = tenantId ? `aios:portal:unlocked:${tenantId}` : "";

  // Hydrate the persisted unlock set once the tenant identity resolves. Runs
  // client-side only (the provider gates children behind `dash`, so by the time
  // a card can be tapped this has already loaded). A re-sync effect in
  // LockableChart promotes any hydrated card straight to "unlocked" (no replay
  // of the pop animation), so a refresh simply shows the graphs already open.
  const hydratedFor = useRef<string>("");
  useEffect(() => {
    if (!storageKey || hydratedFor.current === storageKey) return;
    hydratedFor.current = storageKey;
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) {
        const arr = JSON.parse(raw) as unknown;
        if (Array.isArray(arr)) setUnlocked(new Set(arr.filter((k): k is string => typeof k === "string")));
      }
    } catch {
      /* private-mode / disabled storage — fall back to session-only unlocking */
    }
  }, [storageKey]);

  const unlock = useCallback((key: string) => {
    setUnlocked((prev) => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      if (storageKey) {
        try {
          window.localStorage.setItem(storageKey, JSON.stringify([...next]));
        } catch {
          /* storage unavailable — the unlock still holds for this session */
        }
      }
      return next;
    });
  }, [storageKey]);

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
  const requestsLoading = requestsQ.isLoading;
  const requestsError = requestsQ.isError;
  // Depend on the (react-query-stable) refetch fn, not the whole query object,
  // so this callback — and the context value that closes over it — stays stable.
  const refetchRequestsFn = requestsQ.refetch;
  const refetchRequests = useCallback(() => {
    void refetchRequestsFn();
  }, [refetchRequestsFn]);

  const isGranted = useCallback((key: string) => grants.has(key), [grants]);
  const isUnlocked = useCallback((key: string) => unlocked.has(key), [unlocked]);
  const isPlaceholder = useCallback((key: string) => placeholders.has(key), [placeholders]);

  const addRequest = useCallback(
    (
      r: { kind: RequestKind; subject: string; detail: string },
      opts?: { onSuccess?: () => void; onError?: () => void },
    ) => {
      // Surface the real POST outcome to the caller so the UI can confirm on
      // success and show an error on failure (never an optimistic "sent" that
      // lies when the request never reached the backend).
      createRequest.mutate(r, { onSuccess: opts?.onSuccess, onError: opts?.onError });
    },
    [createRequest],
  );

  const value = useMemo<ClientState>(
    () => ({
      client,
      latestScore: dash?.latestScore ?? null,
      latestAuditWhen: dash?.latestAuditWhen ?? "",
      totalAudits: dash?.totalAudits ?? 0,
      grants,
      reportViz,
      unlocked,
      unlock,
      isGranted,
      isUnlocked,
      isPlaceholder,
      requests,
      requestsLoading,
      requestsError,
      refetchRequests,
      addRequest,
    }),
    [
      client, dash, grants, reportViz, unlocked, unlock, isGranted, isUnlocked, isPlaceholder,
      requests, requestsLoading, requestsError, refetchRequests, addRequest,
    ],
  );

  // Until the tenant identity resolves, show the neutral splash — never a seed,
  // never another tenant. (A hard 401 is already bounced to /login by lib/api.)
  // If the dashboard fetch HARD-FAILS (503 DB-unconfigured, 500, network) it
  // must NOT hang on the splash forever — react-query won't retry a 4xx and gives
  // up on a 5xx after two tries, leaving `dash` undefined. Surface an explicit
  // error + retry instead of an eternal "Loading…".
  if (!dash) {
    if (dashboardQ.isError) {
      return (
        <div className="auth-splash">
          <div className="auth-splash-logo" />
          <div className="auth-splash-txt">We couldn&apos;t load your dashboard.</div>
          <button
            type="button"
            className="primary-btn"
            onClick={() => dashboardQ.refetch()}
            disabled={dashboardQ.isFetching}
            style={{ marginTop: 16 }}
          >
            <span className={`material-symbols-rounded${dashboardQ.isFetching ? " spin" : ""}`}>
              {dashboardQ.isFetching ? "progress_activity" : "refresh"}
            </span>
            {dashboardQ.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      );
    }
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
