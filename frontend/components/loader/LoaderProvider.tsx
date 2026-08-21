"use client";

// ============================================================
// AIOS · Loader controller
// ------------------------------------------------------------
// A minimal, opt-in loading tracker — NOT a global per-navigation overlay.
// Next.js already code-splits every route (each page is its own chunk) and
// streams it in fast, so this only tracks in-flight state when a call site
// explicitly asks for it via `useLoader()` (e.g. the post-login redirect,
// or a task with `run()`), never automatically on navigation. Ref-counted
// so overlapping show()/run() calls resolve correctly.
// ============================================================

import { createContext, useCallback, useContext, useMemo, useRef } from "react";

type Task<T> = Promise<T> | (() => Promise<T>);

export type LoaderApi = {
  show: (label?: string) => void;
  hide: () => void;
  run: <T>(task: Task<T>, label?: string) => Promise<T>;
  /** Kept for call sites that mark loading ahead of a programmatic route change. */
  navigate: (label?: string) => void;
};

const Ctx = createContext<LoaderApi | null>(null);

declare global {
  interface Window {
    __aiosLoader?: LoaderApi;
  }
}

export function LoaderProvider({ children }: { children: React.ReactNode }) {
  // Ref-counted so nested/overlapping show()+run() calls balance correctly.
  // `lbl` is accepted (and unused beyond that) purely to keep the public
  // API stable for existing call sites — there's no visual left to label.
  const count = useRef(0);

  const request = useCallback((_lbl?: string) => {
    count.current += 1;
  }, []);

  const release = useCallback(() => {
    count.current = Math.max(0, count.current - 1);
  }, []);

  const run = useCallback(
    async <T,>(task: Task<T>, lbl?: string): Promise<T> => {
      request(lbl);
      try {
        return await (typeof task === "function" ? (task as () => Promise<T>)() : task);
      } finally {
        release();
      }
    },
    [request, release]
  );

  const api = useMemo<LoaderApi>(
    () => ({
      show: (lbl?: string) => request(lbl),
      hide: () => release(),
      run,
      navigate: (lbl?: string) => request(lbl),
    }),
    [request, release, run]
  );

  if (typeof window !== "undefined") window.__aiosLoader = api;

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useLoader(): LoaderApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLoader must be used within a LoaderProvider");
  return ctx;
}
