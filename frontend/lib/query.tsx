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

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
