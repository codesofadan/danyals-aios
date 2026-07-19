"use client";

// ============================================================
// AIOS · Loader controller
// ------------------------------------------------------------
// A minimal, opt-in progress indicator — NOT a global per-navigation
// overlay. Next.js already code-splits every route (each page is its own
// chunk) and streams it in fast; a blocking full-screen loader on every
// link click just adds latency on top of that, so this only shows when a
// call site explicitly asks for it via `useLoader()` (e.g. the post-login
// redirect, or a task with `run()`), never automatically on navigation.
//
// The visual is a slim top progress bar — CSS only, no WebGL/animation
// library — so it costs effectively nothing to mount.
// ============================================================

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

const MIN_VISIBLE = 220; // avoid a 1-frame flash on very fast tasks
const DEFAULT_LABEL = "Loading";

type Task<T> = Promise<T> | (() => Promise<T>);

export type LoaderApi = {
  show: (label?: string) => void;
  hide: () => void;
  run: <T>(task: Task<T>, label?: string) => Promise<T>;
  /** Kept for call sites that arm the bar ahead of a programmatic route change. */
  navigate: (label?: string) => void;
};

const Ctx = createContext<LoaderApi | null>(null);

declare global {
  interface Window {
    __aiosLoader?: LoaderApi;
  }
}

export function LoaderProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState(false);
  const [label, setLabel] = useState(DEFAULT_LABEL);

  const count = useRef(0);
  const shownAt = useRef(0);
  const hideTimer = useRef<number | null>(null);

  const request = useCallback((lbl?: string) => {
    if (lbl) setLabel(lbl);
    count.current += 1;
    if (count.current === 1) {
      if (hideTimer.current !== null) {
        clearTimeout(hideTimer.current);
        hideTimer.current = null;
      }
      shownAt.current = performance.now();
      setActive(true);
    }
  }, []);

  const release = useCallback(() => {
    count.current = Math.max(0, count.current - 1);
    if (count.current > 0) return;
    const elapsed = performance.now() - shownAt.current;
    const wait = Math.max(0, MIN_VISIBLE - elapsed);
    if (hideTimer.current !== null) clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      if (count.current === 0) {
        setActive(false);
        setLabel(DEFAULT_LABEL);
      }
    }, wait);
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

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className={`topbar-progress${active ? " on" : ""}`} role="status" aria-live="polite" aria-label={label} />
    </Ctx.Provider>
  );
}

export function useLoader(): LoaderApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLoader must be used within a LoaderProvider");
  return ctx;
}
