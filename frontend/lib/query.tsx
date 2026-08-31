"use client";

// ============================================================
// AIOS · TanStack Query wiring
// One QueryClient for the app, created once per browser session. Sensible
// defaults for a dashboard on a bearer-auth API:
//   • don't retry 4xx (auth / validation are terminal); retry a transient 5xx twice
//   • mutations never retry (spend/side-effect safety — a double POST is real money)
//   • no refetch-on-focus (screens poll explicitly where it matters, e.g. audits)
// ============================================================

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          const status = (error as { status?: number } | null)?.status;
          if (typeof status === "number" && status < 500) return false; // 4xx → terminal
          return failureCount < 2;
        },
      },
      mutations: { retry: 0 },
    },
  });
}

// The live client, for the ONE caller that cannot reach it through context:
// AuthProvider sits OUTSIDE QueryProvider in app/layout.tsx, so `useQueryClient()`
// there would throw. Sign-out still has to empty this cache — it outlives the
// session (created once per browser session, below), so without a clear the next
// person to sign in on the same machine is served the previous user's cached
// counts and lists until every query happens to refetch.
let activeClient: QueryClient | null = null;

/** Drop every cached response. Called on sign-out. No-op before the app mounts. */
export function clearQueryCache(): void {
  activeClient?.clear();
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeQueryClient);
  activeClient = client;
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
